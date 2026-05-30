import os
import sys
import sqlite3
import pytest
import datetime
from unittest.mock import patch

# Ensure workspace root is in python path
sys.path.insert(0, os.getcwd())

from src.models.db_models import init_db, get_db_connection
from src.utils.parsers import parse_city
from src.services.fusion_service import EventFusionService
from src.config import settings

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """Test fixture: automatically sets up a temporary isolated test SQLite database"""
    db_file = tmp_path / "test_event_normalization.db"
    settings.db_path = str(db_file)
    init_db()
    yield
    if db_file.exists():
        db_file.unlink()

def test_parse_city_scenarios():
    """Unit tests for parse_city covering different levels of cleaning and matching"""
    # 1. Province and autonomous region stripping
    assert parse_city("浙江省杭州白马湖微电子博览中心") == "杭州"
    assert parse_city("广东省广州琶洲保利世贸博览馆") == "广州"
    assert parse_city("内蒙古自治区呼和浩特市会展中心") == "呼和浩特"
    assert parse_city("新疆维吾尔自治区乌鲁木齐会展馆") == "乌鲁木齐"
    
    # 2. Major exhibition cities with non-standard lengths or names
    assert parse_city("哈尔滨国际会展中心") == "哈尔滨"
    assert parse_city("石家庄会展中心") == "石家庄"
    assert parse_city("上海世博展览馆") == "上海"
    assert parse_city("北京国家会议中心") == "北京"
    
    # 3. Smart administrative suffix stripping
    assert parse_city("黄冈市黄州区路口镇") == "黄冈"
    assert parse_city("延边朝鲜族自治州延吉市") == "延边"
    
    # 4. Fallback two-character extraction
    assert parse_city("福州海峡国际会展中心") == "福州"
    assert parse_city("攀枝花市会展馆") == "攀枝花"  # Matches major cities first
    
    # 5. Null or unknown placeholders
    assert parse_city("") == "未知"
    assert parse_city(None) == "未知"
    assert parse_city("未知地点") == "未知"

    # 6. 吉林省/吉林市省市同名冲突修复验证
    assert parse_city("吉林动画学院会展馆") == "吉林"
    assert parse_city("吉林省吉林市大同路") == "吉林"
    
    # 7. 动态加载自定义地级市大市匹配 (来自 settings.yaml 的 custom_cities 注入)
    assert parse_city("常德会展馆") == "常德"
    assert parse_city("许昌国际博览中心") == "许昌"


def test_o1_fast_path_and_date_window():
    """Integration test: verify O(1) standard and alias matching with a 7-day date window"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create an initial normalized event
    # Bilibili World 2026: 2026-07-10 to 2026-07-12 in Shanghai
    now_str = "2026-05-30 00:00:00"
    cursor.execute(
        """
        INSERT INTO normalized_events (event_fingerprint, standard_name, city, start_date, end_date, event_type, created_at)
        VALUES ('上海_bilibiliworld2026', 'Bilibili World 2026', '上海', '2026-07-10', '2026-07-12', '漫展', ?);
        """,
        (now_str,)
    )
    bili_event_id = cursor.lastrowid
    
    # Create an alias mapping for "上海bw"
    cursor.execute(
        """
        INSERT INTO event_aliases (alias_name, city, normalized_event_id, created_at)
        VALUES ('上海bilibiliworld', '上海', ?, ?);
        """,
        (bili_event_id, now_str)
    )
    conn.commit()
    
    # Scenario A: Exact standard name matching in the same city & within 7-day window
    # Search date: 2026-07-15 (within 7 days of 2026-07-12)
    matched_id = EventFusionService.find_or_create_normalized_event(
        cursor, "Bilibili World 2026", "上海", "2026-07-15"
    )
    assert matched_id == bili_event_id
    
    # Scenario B: Alias matching in the same city & within 7-day window
    # Search date: 2026-07-05 (within 7 days of 2026-07-10)
    matched_id_alias = EventFusionService.find_or_create_normalized_event(
        cursor, "上海BilibiliWorld", "上海", "2026-07-05"
    )
    assert matched_id_alias == bili_event_id
    
    # Scenario C: Match rejected due to date window violation (different year/edition)
    # Search date: 2027-07-10 (outside 7 days of 2026-07-12)
    # This should fall through and create a NEW normalized event node!
    new_matched_id = EventFusionService.find_or_create_normalized_event(
        cursor, "Bilibili World 2026", "上海", "2027-07-10"
    )
    assert new_matched_id != bili_event_id
    
    cursor.execute("SELECT city, start_date, end_date FROM normalized_events WHERE id = ?;", (new_matched_id,))
    row = cursor.fetchone()
    assert row[0] == "上海"
    assert row[1] == "2027-07-10"
    assert row[2] == "2027-07-10"

    # Scenario D: Match rejected when incoming event_date is "未知", and existing node has a concrete date in a PAST year
    # 1. Create a historical node from 2024 (a past year relative to 2026)
    cursor.execute(
        """
        INSERT INTO normalized_events (event_fingerprint, standard_name, city, start_date, end_date, event_type, created_at)
        VALUES ('上海_bilibiliworld2024', 'Bilibili World 2024', '上海', '2024-07-10', '2024-07-12', '漫展', ?);
        """,
        (now_str,)
    )
    past_event_id = cursor.lastrowid
    conn.commit()
    
    # 2. Search for "Bilibili World 2024" with date "未知".
    # It should NOT match the 2024 node (past_event_id) because 2024 is in the past!
    undated_matched_id = EventFusionService.find_or_create_normalized_event(
        cursor, "Bilibili World 2024", "上海", "未知"
    )
    assert undated_matched_id != past_event_id
    
    # 3. Search for "Bilibili World 2026" with date "未知".
    # It SHOULD match the 2026 node (bili_event_id) because 2026 is the current year!
    current_matched_id = EventFusionService.find_or_create_normalized_event(
        cursor, "Bilibili World 2026", "上海", "未知"
    )
    assert current_matched_id == bili_event_id


def test_spatial_rectification_promotion():
    """Integration test: verify promotion of '未知' city node to a concrete city when target doesn't exist"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Insert an existing "未知" city node
    now_str = "2026-05-30 00:00:00"
    cursor.execute(
        """
        INSERT INTO normalized_events (event_fingerprint, standard_name, city, start_date, end_date, event_type, created_at)
        VALUES ('未知_cp32', 'CP32', '未知', '2026-06-01', '2026-06-02', '漫展', ?);
        """,
        (now_str,)
    )
    unknown_node_id = cursor.lastrowid
    
    # Insert an alias for the unknown node
    cursor.execute(
        """
        INSERT INTO event_aliases (alias_name, city, normalized_event_id, created_at)
        VALUES ('cp32动漫展', '未知', ?, ?);
        """,
        (unknown_node_id, now_str)
    )
    conn.commit()
    
    # 2. Query with a concrete city "上海"
    # Target concrete node doesn't exist. "未知" node should be promoted.
    matched_id = EventFusionService.find_or_create_normalized_event(
        cursor, "CP32", "上海", "2026-06-01"
    )
    
    # Assert that the same node ID is returned (就地物理升级)
    assert matched_id == unknown_node_id
    
    # Assert that the database columns are correctly updated
    cursor.execute("SELECT city, event_fingerprint FROM normalized_events WHERE id = ?;", (unknown_node_id,))
    node_row = cursor.fetchone()
    assert node_row[0] == "上海"
    assert node_row[1] == "上海_comicup32"
    
    # Assert that the alias has also been updated to "上海"
    cursor.execute("SELECT city FROM event_aliases WHERE normalized_event_id = ?;", (unknown_node_id,))
    alias_rows = cursor.fetchall()
    assert len(alias_rows) == 1
    assert alias_rows[0][0] == "上海"


def test_spatial_rectification_redirect_and_delete():
    """Integration test: verify redirection of events and cleanup of the '未知' node when concrete node already exists"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now_str = "2026-05-30 00:00:00"
    
    # 1. Insert a concrete city node (上海_cp32)
    cursor.execute(
        """
        INSERT INTO normalized_events (event_fingerprint, standard_name, city, start_date, end_date, event_type, created_at)
        VALUES ('上海_cp32', 'CP32', '上海', '2026-06-01', '2026-06-02', '漫展', ?);
        """,
        (now_str,)
    )
    concrete_id = cursor.lastrowid
    
    # 2. Insert an unknown city node (未知_cp32)
    cursor.execute(
        """
        INSERT INTO normalized_events (event_fingerprint, standard_name, city, start_date, end_date, event_type, created_at)
        VALUES ('未知_cp32', 'CP32', '未知', '2026-06-01', '2026-06-02', '漫展', ?);
        """,
        (now_str,)
    )
    unknown_id = cursor.lastrowid
    
    # Add an alias for the unknown node
    cursor.execute(
        """
        INSERT INTO event_aliases (alias_name, city, normalized_event_id, created_at)
        VALUES ('cp32动漫展', '未知', ?, ?);
        """,
        (unknown_id, now_str)
    )
    
    # 3. Create dummy raw post and cosplay event pointing to the unknown node
    cursor.execute("INSERT INTO cosers (name) VALUES ('CoserA');")
    coser_id = cursor.lastrowid
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content, is_analyzed) VALUES (?, 'weibo', 'post123', 'content', 0);", (coser_id,))
    raw_post_id = cursor.lastrowid
    
    cursor.execute(
        """
        INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, normalized_event_id)
        VALUES (?, 'CoserA', 'CP32', '2026-06-01', '未知地点', ?);
        """,
        (raw_post_id, unknown_id)
    )
    cos_event_id = cursor.lastrowid
    conn.commit()
    
    # 4. Trigger normalized search with concrete city "上海"
    # Both concrete and unknown exist. The unknown should be merged into concrete and deleted.
    matched_id = EventFusionService.find_or_create_normalized_event(
        cursor, "CP32", "上海", "2026-06-01"
    )
    
    # Assert that it matched the concrete node
    assert matched_id == concrete_id
    
    # Assert that the cosplay_events reference has been redirected to the concrete node
    cursor.execute("SELECT normalized_event_id FROM cosplay_events WHERE id = ?;", (cos_event_id,))
    assert cursor.fetchone()[0] == concrete_id
    
    # Assert that the unknown node was deleted
    cursor.execute("SELECT id FROM normalized_events WHERE id = ?;", (unknown_id,))
    assert cursor.fetchone() is None
    
    # Assert that the unknown node's aliases were deleted cascadingly
    cursor.execute("SELECT id FROM event_aliases WHERE normalized_event_id = ?;", (unknown_id,))
    assert cursor.fetchall() == []
