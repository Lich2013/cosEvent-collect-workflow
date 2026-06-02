import os
import sys

# Ensure the root directory is in python search path
sys.path.insert(0, os.getcwd())

import pytest
from click.testing import CliRunner
from src.models.db_models import init_db, get_db_connection
from src.services.db_service import DBService
from src.config import settings
from src.main import cli

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """Test fixture: automatically sets up temporary database to isolate tests"""
    db_file = tmp_path / "test_summary_city.db"
    settings.db_path = str(db_file)
    init_db()
    yield
    if db_file.exists():
        db_file.unlink()

def test_summary_city_filtering():
    """Test the database-level filtering for city parameter"""
    # 1. Register test Cosers
    assert DBService.add_coser("测试姬_上海", weibo_uid="111", bilibili_uid="222") is True
    assert DBService.add_coser("测试姬_广州", weibo_uid="333", bilibili_uid="444") is True
    
    cosers = DBService.list_cosers()
    coser_sh_id = next(c["id"] for c in cosers if c["name"] == "测试姬_上海")
    coser_gz_id = next(c["id"] for c in cosers if c["name"] == "测试姬_广州")
    
    # 2. Insert raw posts
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO raw_posts (coser_id, platform, post_id, content, is_analyzed) VALUES (?, ?, ?, ?, ?);",
        (coser_sh_id, 'weibo', 'p_sh_01', '我要去上海漫展啦', 1)
    )
    raw_post_sh_id = cursor.lastrowid
    
    cursor.execute(
        "INSERT INTO raw_posts (coser_id, platform, post_id, content, is_analyzed) VALUES (?, ?, ?, ?, ?);",
        (coser_gz_id, 'weibo', 'p_gz_01', '我要去广州漫展啦', 1)
    )
    raw_post_gz_id = cursor.lastrowid
    
    # 3. Insert into final_exhibition_view and cosplay_events
    # Shanghai Node (using standard normalized_events table for fallback & final_exhibition_view for materialized view)
    cursor.execute(
        """
        INSERT INTO final_exhibition_view (id, event_fingerprint, standard_name, city, start_date, end_date, event_type, is_frozen)
        VALUES ('sh_event_id_01', 'sh_fingerprint_01', '上海CP30', '上海', '2029-05-02', '2029-05-03', '漫展', 1);
        """
    )
    cursor.execute(
        """
        INSERT INTO cosplay_events (id, raw_post_id, coser_name, event_name, event_date, event_place, status, confidence, event_type)
        VALUES (101, ?, '测试姬_上海', '上海CP30', '2029-05-02', '上海会展中心', '未开始', 0.9, '漫展');
        """,
        (raw_post_sh_id,)
    )
    cursor.execute(
        """
        INSERT INTO event_mappings (raw_event_id, normalized_event_id)
        VALUES (101, 'sh_event_id_01');
        """
    )
    
    # Guangzhou Node
    cursor.execute(
        """
        INSERT INTO final_exhibition_view (id, event_fingerprint, standard_name, city, start_date, end_date, event_type, is_frozen)
        VALUES ('gz_event_id_01', 'gz_fingerprint_01', '广州萤火虫', '广州', '2029-07-15', '2029-07-17', '漫展', 1);
        """
    )
    cursor.execute(
        """
        INSERT INTO cosplay_events (id, raw_post_id, coser_name, event_name, event_date, event_place, status, confidence, event_type)
        VALUES (102, ?, '测试姬_广州', '广州萤火虫', '2029-07-15', '保利世贸博览馆', '未开始', 0.95, '漫展');
        """,
        (raw_post_gz_id,)
    )
    cursor.execute(
        """
        INSERT INTO event_mappings (raw_event_id, normalized_event_id)
        VALUES (102, 'gz_event_id_01');
        """
    )
    
    conn.commit()
    conn.close()
    
    # 4. Verify DBService.get_all_events filters properly by city (Coser-centric)
    all_events = DBService.get_all_events(city=None)
    assert len(all_events) == 2
    
    sh_events = DBService.get_all_events(city="上海")
    assert len(sh_events) == 1
    assert sh_events[0]["event_name"] == "上海CP30"
    assert sh_events[0]["city"] == "上海"
    
    gz_events = DBService.get_all_events(city="广州")
    assert len(gz_events) == 1
    assert gz_events[0]["event_name"] == "广州萤火虫"
    assert gz_events[0]["city"] == "广州"
    
    bj_events = DBService.get_all_events(city="北京")
    assert len(bj_events) == 0
    
    # 5. Verify DBService.get_event_centric_summary filters properly by city (Event-centric)
    all_summaries = DBService.get_event_centric_summary(city=None)
    assert len(all_summaries) == 2
    
    sh_summaries = DBService.get_event_centric_summary(city="上海")
    assert len(sh_summaries) == 1
    assert sh_summaries[0]["standard_name"] == "上海CP30"
    assert sh_summaries[0]["city"] == "上海"
    
    gz_summaries = DBService.get_event_centric_summary(city="广州")
    assert len(gz_summaries) == 1
    assert gz_summaries[0]["standard_name"] == "广州萤火虫"
    assert gz_summaries[0]["city"] == "广州"
    
    bj_summaries = DBService.get_event_centric_summary(city="北京")
    assert len(bj_summaries) == 0

def test_cli_summary_city_command():
    """Test Click CLI summary command city filtering option"""
    # Register test Coser and events
    DBService.add_coser("测试姬_上海CLI")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO raw_posts (coser_id, platform, post_id, content, is_analyzed) VALUES (?, ?, ?, ?, ?);",
        (coser_id, 'weibo', 'p_cli_sh_01', '我要去上海漫展啦', 1)
    )
    raw_post_id = cursor.lastrowid
    
    cursor.execute(
        """
        INSERT INTO final_exhibition_view (id, event_fingerprint, standard_name, city, start_date, end_date, event_type, is_frozen)
        VALUES ('sh_cli_event_id', 'sh_cli_fingerprint', '上海CP30_CLI', '上海', '2029-05-02', '2029-05-03', '漫展', 1);
        """
    )
    cursor.execute(
        """
        INSERT INTO cosplay_events (id, raw_post_id, coser_name, event_name, event_date, event_place, status, confidence, event_type)
        VALUES (201, ?, '测试姬_上海CLI', '上海CP30_CLI', '2029-05-02', '上海会展中心', '未开始', 0.9, '漫展');
        """,
        (raw_post_id,)
    )
    cursor.execute(
        """
        INSERT INTO event_mappings (raw_event_id, normalized_event_id)
        VALUES (201, 'sh_cli_event_id');
        """
    )
    conn.commit()
    conn.close()
    
    runner = CliRunner()
    
    # 1. Coser-centric summary with matching city
    res_sh = runner.invoke(cli, ["summary", "--city", "上海"])
    assert res_sh.exit_code == 0
    assert "测试姬_上海CLI" in res_sh.output
    assert "上海CP30_CLI" in res_sh.output
    assert "上海会展中心" in res_sh.output
    
    # 2. Coser-centric summary with non-matching city
    res_gz = runner.invoke(cli, ["summary", "--city", "广州"])
    assert res_gz.exit_code == 0
    assert "测试姬_上海CLI" not in res_gz.output
    assert "上海CP30_CLI" not in res_gz.output
    
    # 3. Event-centric summary with matching city
    res_event_sh = runner.invoke(cli, ["summary", "--by-event", "--city", "上海"])
    assert res_event_sh.exit_code == 0
    assert "超级漫展集结看板" in res_event_sh.output
    assert "上海CP30_CLI" in res_event_sh.output
    assert "测试姬_上海CLI" in res_event_sh.output
    
    # 4. Event-centric summary with non-matching city
    res_event_gz = runner.invoke(cli, ["summary", "--by-event", "--city", "广州"])
    assert res_event_gz.exit_code == 0
    assert "上海CP30_CLI" not in res_event_gz.output
