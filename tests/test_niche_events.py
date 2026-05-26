import os
import sys
import sqlite3
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# 确保项目根目录在 python 搜索路径中
sys.path.insert(0, os.getcwd())

from src.models.db_models import init_db, get_db_connection
from src.services.db_service import DBService
from src.services.fusion_service import EventFusionService
from src.config import settings
from click.testing import CliRunner
from src.main import cli
from src.models.schemas import CosEvent

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """测试夹具：自动配置临时隔离测试数据库"""
    db_file = tmp_path / "test_cosevent_niche.db"
    settings.db_path = str(db_file)
    init_db()
    yield
    # 清理临时文件
    if db_file.exists():
        db_file.unlink()

def test_database_niche_validation_and_check():
    """测试应用层 validate_type 校验与数据库物理 CHECK 约束"""
    DBService.add_coser("测试Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content, is_analyzed) VALUES (?, 'weibo', 'p_test_val', 'content', 0);", (coser_id,))
    raw_post_id = cursor.lastrowid
    
    # 1. 验证合法类型写入正常
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type) VALUES (?, '测试Coser', '店长活动', '2026-11-08', '上海罗森', '一日店长');",
        (raw_post_id,)
    )
    conn.commit()
    
    # 2. 验证非法类型触发 SQLite 物理 CHECK 约束报错
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type) VALUES (?, '测试Coser', '店长活动', '2026-11-08', '上海罗森', '非法类型');",
            (raw_post_id,)
        )
        conn.commit()
        
    # 3. 验证 DBService 中的 validate_type 应用级拦截
    events = [
        {
            "event_name": "店长日程",
            "event_date": "2026-11-08",
            "event_place": "上海",
            "event_type": "非法类型",
            "confidence": 0.95
        }
    ]
    
    # 物理调用 save_extracted_events_transactional 时由于非标状态应断言报错触发回滚
    conn.commit()
    conn.close()
    
    assert DBService.save_extracted_events_transactional(raw_post_id, events, confidence_threshold=0.0) is False

def test_fusion_bypass_for_niche_events():
    """测试非 '漫展' 的小众活动 100% 旁路融合与裁判引擎"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 插入两个同名、同城且同天的小众一日店长活动
    # 常规漫展在此场景下由于 100% 相似会触发合并归一化为一个超级节点
    # 而一日店长等小众活动应当 100% 旁路，独立建超级节点
    event_id_1 = EventFusionService.find_or_create_normalized_event(
        cursor, "Nikke罗森一日店长", "上海", "2026-11-08", "一日店长"
    )
    event_id_2 = EventFusionService.find_or_create_normalized_event(
        cursor, "Nikke罗森一日店长", "上海", "2026-11-08", "一日店长"
    )
    
    conn.commit()
    
    # 验证是否物理独立建档 (ID 不同)
    assert event_id_1 != event_id_2
    
    # 验证在 normalized_events 中的 event_type 严格保持对齐
    cursor.execute("SELECT event_type FROM normalized_events WHERE id = ?;", (event_id_1,))
    assert cursor.fetchone()[0] == '一日店长'
    
    cursor.execute("SELECT event_type FROM normalized_events WHERE id = ?;", (event_id_2,))
    assert cursor.fetchone()[0] == '一日店长'
    
    conn.close()

def test_cli_filtering_by_type(tmp_path):
    """测试 summary, calendar 和 export 命令行工具在传递 --type 时的筛选效果"""
    DBService.add_coser("CoserNiche")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content, is_analyzed) VALUES (?, 'weibo', 'p_niche_1', 'content', 0);", (coser_id,))
    raw_post_id = cursor.lastrowid
    
    # 注册一个漫展和一个一日店长
    event_id_1 = EventFusionService.find_or_create_normalized_event(cursor, "上海CP30", "上海", "2026-07-05", "漫展")
    event_id_2 = EventFusionService.find_or_create_normalized_event(cursor, "罗森一日店长", "上海", "2026-11-08", "一日店长")
    
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, normalized_event_id, event_type) VALUES (?, 'CoserNiche', '上海CP30', '2026-07-05', '会展中心', ?, '漫展');",
        (raw_post_id, event_id_1)
    )
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, normalized_event_id, event_type) VALUES (?, 'CoserNiche', '罗森一日店长', '2026-11-08', '罗森店铺', ?, '一日店长');",
        (raw_post_id, event_id_2)
    )
    conn.commit()
    conn.close()
    
    runner = CliRunner()
    
    # 1. 验证 summary --by-event --type
    res = runner.invoke(cli, ["summary", "--by-event", "--type", "一日店长"])
    assert res.exit_code == 0
    assert "罗森一日店长" in res.output
    assert "上海CP30" not in res.output
    
    # 2. 验证 calendar 默认仅展示 '漫展'
    res = runner.invoke(cli, ["calendar", "--scope", "all"])
    assert res.exit_code == 0
    assert "上海CP30" in res.output
    assert "罗森一日店长" not in res.output
    
    # 3. 验证 calendar --type 一日店长
    res = runner.invoke(cli, ["calendar", "--scope", "all", "--type", "一日店长"])
    assert res.exit_code == 0
    assert "罗森一日店长" in res.output
    assert "上海CP30" not in res.output
    
    # 4. 验证 export --type 一日店长
    txt_file = tmp_path / "niche.txt"
    res = runner.invoke(cli, ["export", "--type", "一日店长", "--output", str(txt_file)])
    assert res.exit_code == 0
    with open(txt_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "罗森一日店长" in content
        assert "上海CP30" not in content
