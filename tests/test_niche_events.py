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
    
    # 应该抛出 AssertionError 激活熔断机制
    with pytest.raises(AssertionError):
        DBService.save_extracted_events_transactional(raw_post_id, events, confidence_threshold=0.0)

def test_fusion_bypass_for_niche_events():
    """测试非 '漫展' 的小众活动智能闸门控制"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. 专有名词店长活动被放行并成功融合 (Nikke罗森一日店长)
    event_id_1 = EventFusionService.find_or_create_normalized_event(
        cursor, "Nikke罗森一日店长", "上海", "2026-11-08", "一日店长"
    )
    event_id_2 = EventFusionService.find_or_create_normalized_event(
        cursor, "Nikke罗森一日店长", "上海", "2026-11-08", "一日店长"
    )
    
    # 2. 边界四字店长活动被成功放行融合 (罗森店长)
    event_id_3 = EventFusionService.find_or_create_normalized_event(
        cursor, "罗森店长", "上海", "2026-11-08", "一日店长"
    )
    event_id_4 = EventFusionService.find_or_create_normalized_event(
        cursor, "罗森店长", "上海", "2026-11-08", "一日店长"
    )

    # 3. 极简一日店长活动被安全旁路独立建档 (一日店长)
    event_id_5 = EventFusionService.find_or_create_normalized_event(
        cursor, "一日店长", "上海", "2026-11-08", "一日店长"
    )
    event_id_6 = EventFusionService.find_or_create_normalized_event(
        cursor, "一日店长", "上海", "2026-11-08", "一日店长"
    )
    
    conn.commit()
    
    # 验证专有名词和边界四字活动成功融合为同一个超级节点
    assert event_id_1 == event_id_2
    assert event_id_3 == event_id_4
    
    # 验证极简泛称活动触发 100% 旁路，物理独立建档
    assert event_id_5 != event_id_6
    
    # 4. 带有城市名前缀的极简一日店长活动，应成功剥离前缀并触发旁路隔离 (上海一日店长)
    event_id_7 = EventFusionService.find_or_create_normalized_event(
        cursor, "上海一日店长", "上海", "2026-11-08", "一日店长"
    )
    event_id_8 = EventFusionService.find_or_create_normalized_event(
        cursor, "上海一日店长", "上海", "2026-11-08", "一日店长"
    )
    assert event_id_7 != event_id_8  # 触发旁路独立建档

    # 5. 带有城市名前缀但包含品牌的店长活动，应剥离前缀放行常规融合 (上海罗森一日店长)
    event_id_9 = EventFusionService.find_or_create_normalized_event(
        cursor, "上海罗森一日店长", "上海", "2026-11-08", "一日店长"
    )
    event_id_10 = EventFusionService.find_or_create_normalized_event(
        cursor, "上海罗森一日店长", "上海", "2026-11-08", "一日店长"
    )
    assert event_id_9 == event_id_10  # 正常放行融合

    # 6. 测试动态配置黑名单对过滤旁路的控制
    original_bypass = settings.bypass_generic_names
    try:
        # 新增自定义泛称黑名单词汇 "快闪店"
        settings.bypass_generic_names = original_bypass + ["快闪店"]
        event_id_11 = EventFusionService.find_or_create_normalized_event(
            cursor, "北京快闪店", "北京", "2026-11-08", "一日店长"
        )
        event_id_12 = EventFusionService.find_or_create_normalized_event(
            cursor, "北京快闪店", "北京", "2026-11-08", "一日店长"
        )
        assert event_id_11 != event_id_12  # 新配置的词汇成功被拦截并触发旁路
    finally:
        settings.bypass_generic_names = original_bypass
    
    # 验证在 normalized_events 中的 event_type 严格保持对齐
    cursor.execute("SELECT event_type FROM normalized_events WHERE id = ?;", (event_id_1,))
    assert cursor.fetchone()[0] == '一日店长'
    
    cursor.execute("SELECT event_type FROM normalized_events WHERE id = ?;", (event_id_5,))
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


def test_database_deduplication():
    """测试数据库一键式存量去重原子服务与级联重定向、别名表冲突自愈"""
    # 先添加 Coser，避免在打开手动连接时产生 SQLite 锁冲突
    DBService.add_coser("测试Coser")
    coser_id = DBService.list_cosers()[0]["id"]

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. 物理插入两个同城、同天、同名但不同 ID 的小众日程超级节点 (模拟历史去重)
    cursor.execute(
        "INSERT INTO normalized_events (event_fingerprint, standard_name, city, start_date, end_date, event_type) VALUES ('shanghai_nikkedianzhang_1', 'Nikke罗森一日店长', '上海', '2026-11-08', '2026-11-08', '一日店长');"
    )
    winner_id = cursor.lastrowid
    
    cursor.execute(
        "INSERT INTO normalized_events (event_fingerprint, standard_name, city, start_date, end_date, event_type) VALUES ('shanghai_nikkedianzhang_2', 'Nikke罗森一日店长', '上海', '2026-11-08', '2026-11-08', '一日店长');"
    )
    loser_id = cursor.lastrowid
    
    # 2. 插入 cosplay_events 日程记录
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content, is_analyzed) VALUES (?, 'weibo', 'p_test_dedup', 'content', 0);", (coser_id,))
    raw_post_id = cursor.lastrowid
    
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type, normalized_event_id) VALUES (?, '测试Coser', 'Nikke罗森一日店长', '2026-11-08', '上海罗森', '一日店长', ?);",
        (raw_post_id, winner_id)
    )
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type, normalized_event_id) VALUES (?, '测试Coser', 'Nikke罗森一日店长', '2026-11-08', '上海罗森', '一日店长', ?);",
        (raw_post_id, loser_id)
    )
    
    # 3. 注册别名表
    # 3.1 正常别名重定向：别名仅存在于 loser
    cursor.execute(
        "INSERT INTO event_aliases (alias_name, city, normalized_event_id) VALUES ('nikke店长别名1', '上海', ?);",
        (loser_id,)
    )
    # 3.2 冲突别名重定向：别名存在于 loser，且等下通过 patch 模拟 IntegrityError 触发冲突自愈
    cursor.execute(
        "INSERT INTO event_aliases (alias_name, city, normalized_event_id) VALUES ('nikke店长别名2', '上海', ?);",
        (loser_id,)
    )
    alias2_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    
    # 4. 执行 DeduplicationService.deduplicate_database()，并利用 ConnectionProxy 抛出 IntegrityError
    class CursorProxy:
        def __init__(self, real_cursor):
            self._real_cursor = real_cursor
            
        def execute(self, sql, params=None):
            if "UPDATE event_aliases SET" in sql and params and len(params) >= 2 and params[1] == alias2_id:
                raise sqlite3.IntegrityError("UNIQUE constraint failed: event_aliases.alias_name, event_aliases.city")
            if params is not None:
                return self._real_cursor.execute(sql, params)
            return self._real_cursor.execute(sql)
            
        def __getattr__(self, name):
            return getattr(self._real_cursor, name)

    class ConnectionProxy:
        def __init__(self, real_conn):
            self._real_conn = real_conn
            
        def cursor(self):
            return CursorProxy(self._real_conn.cursor())
            
        def __getattr__(self, name):
            return getattr(self._real_conn, name)
            
        def __enter__(self):
            self._real_conn.__enter__()
            return self
            
        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._real_conn.__exit__(exc_type, exc_val, exc_tb)

    real_get_conn = get_db_connection
    def mock_get_conn():
        return ConnectionProxy(real_get_conn())

    with patch('src.services.db.dedup_service.get_db_connection', mock_get_conn):
        from src.services.db.dedup_service import DeduplicationService
        stats = DeduplicationService.deduplicate_database()
    
    # 5. 断言去重结果详情
    assert stats["processed_groups"] >= 1
    assert stats["merged_nodes"] >= 1
    assert stats["alias_redirects"] >= 1
    assert stats["alias_conflicts"] >= 1
    assert stats["deleted_nodes"] >= 1
    
    # 6. 物理自检数据库
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 6.1 Loser 节点已被安全清理
    cursor.execute("SELECT id FROM normalized_events WHERE id = ?;", (loser_id,))
    assert cursor.fetchone() is None
    
    # 6.2 winner 节点依旧完好
    cursor.execute("SELECT id FROM normalized_events WHERE id = ?;", (winner_id,))
    assert cursor.fetchone() is not None
    
    # 6.3 cosplay_events 已全部级联重定向至 winner
    cursor.execute("SELECT normalized_event_id FROM cosplay_events WHERE raw_post_id = ?;", (raw_post_id,))
    rows = cursor.fetchall()
    assert len(rows) == 2
    assert rows[0][0] == winner_id
    assert rows[1][0] == winner_id
    
    # 6.4 正常别名已成功重定向至 winner，而冲突别名由于 IntegrityError 被安全删除
    cursor.execute("SELECT alias_name FROM event_aliases WHERE normalized_event_id = ?;", (winner_id,))
    aliases = {r[0] for r in cursor.fetchall()}
    assert "nikke店长别名1" in aliases
    assert "nikke店长别名2" not in aliases
    assert len(aliases) == 1
    
    conn.close()
    
    # 7. 测试 CLI 控制台命令的正确执行
    runner = CliRunner()
    res = runner.invoke(cli, ["deduplicate"])
    assert res.exit_code == 0
    assert "数据库存量超级节点去重合并成功完成！" in res.output


def test_materialized_view_rebuild():
    """测试物化展示视图重建算法、冷热滑动窗口分区、确定性哈希ID及未知日期逻辑冷冻"""
    import datetime
    import json
    import os
    
    # 1. 动态生成近期与远期日期
    today = datetime.date.today()
    active_date = (today + datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    old_date = (today - datetime.timedelta(days=50)).strftime("%Y-%m-%d")
    
    # 2. 物理初始化 Coser 及对应的冷热博文
    DBService.add_coser("物化测试Coser")
    coser_id = [c for c in DBService.list_cosers() if c["name"] == "物化测试Coser"][0]["id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 插入热博文 (发布于今天)
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content, published_at, is_analyzed) VALUES (?, 'weibo', 'p_hot_post', 'content', ?, 1);", (coser_id, today.strftime("%Y-%m-%d")))
    hot_post_id = cursor.lastrowid
    
    # 插入冷博文 (发布于50天前)
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content, published_at, is_analyzed) VALUES (?, 'weibo', 'p_cold_post', 'content', ?, 1);", (coser_id, old_date))
    cold_post_id = cursor.lastrowid
    
    # 3. 直接在 cosplay_events 写入原始只读日程事实数据
    # 3.1 热日程 1 和 2: 名字相同，日期相同，应合并为同一个活跃超级展示节点
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type, status) VALUES (?, '物化测试Coser', 'Nikke罗森一日店长', ?, '上海罗森', '一日店长', '未开始');",
        (hot_post_id, active_date)
    )
    raw_ev_1 = cursor.lastrowid
    
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type, status) VALUES (?, '物化测试Coser', 'Nikke罗森一日店长', ?, '上海罗森', '一日店长', '未开始');",
        (hot_post_id, active_date)
    )
    raw_ev_2 = cursor.lastrowid
    
    # 3.2 热日程 3: 极简泛称名字在黑名单中，应触发 Gated 旁路生成独立超级节点
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type, status) VALUES (?, '物化测试Coser', '一日店长', ?, '上海罗森', '一日店长', '未开始');",
        (hot_post_id, active_date)
    )
    raw_ev_3 = cursor.lastrowid
    
    # 3.3 冷日程 4: 日期早于 30 天之前，应生成为冻结节点 (is_frozen = 1)
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type, status) VALUES (?, '物化测试Coser', '次元之门漫展', ?, '上海', '漫展', '未开始');",
        (hot_post_id, old_date)
    )
    raw_ev_4 = cursor.lastrowid
    
    # 3.4 冷日程 5: 未知日期但原始博文发布于 50 天前，应触发未知冷冻生成冻结节点 (is_frozen = 1)
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type, status) VALUES (?, '物化测试Coser', '古老未知日程', '未知', '上海', '一日店长', '未开始');",
        (cold_post_id,)
    )
    raw_ev_5 = cursor.lastrowid

    # 3.5 空间自适应纠偏测试日程：
    # 一个具体城市的上海 BW 活跃日程，和一个未知城市的 BW 活跃日程。它们应被智能纠宿融合，统合为“上海”的同一个展示超级节点。
    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type, status) VALUES (?, '物化测试Coser', 'Bilibili World 2026', '2026-07-10', '上海国家会展中心', '漫展', '未开始');",
        (hot_post_id,)
    )
    raw_ev_bw_concrete = cursor.lastrowid

    cursor.execute(
        "INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_type, status) VALUES (?, '物化测试Coser', 'Bilibili World 2026', '2026-07-11', '未知', '漫展', '未开始');",
        (hot_post_id,)
    )
    raw_ev_bw_unknown = cursor.lastrowid
    
    conn.commit()
    conn.close()
    
    # 4. 运行物化视图重建服务
    from src.services.db.materialize_service import MaterializeService
    stats = MaterializeService.rebuild_view()
    
    # 5. 校验统计数据
    assert stats["active_schedules"] == 7
    assert stats["new_clusters"] == 5  # 1和2合并, 3旁路, 4冷日程, 5未知冷日程, BW日程
    assert stats["newly_frozen_nodes"] == 2  # 日程4和日程5被成功冻结
    
    # 6. 自检数据库与物化状态
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 6.1 验证 event_mappings 记录全部完整建立，且 cosplay_events 事实表未受任何破坏
    cursor.execute("SELECT COUNT(*) FROM event_mappings;")
    assert cursor.fetchone()[0] == 7
    
    cursor.execute("SELECT COUNT(*) FROM cosplay_events WHERE status = '未开始';")
    assert cursor.fetchone()[0] == 7  # cosplay_events 完全没有被原地 mutate 软删除
    
    # 6.2 验证合并后的 Nikke店长超级节点处于活跃状态
    cursor.execute("SELECT normalized_event_id FROM event_mappings WHERE raw_event_id = ?;", (raw_ev_1,))
    winner_id_1 = cursor.fetchone()[0]
    cursor.execute("SELECT normalized_event_id FROM event_mappings WHERE raw_event_id = ?;", (raw_ev_2,))
    winner_id_2 = cursor.fetchone()[0]
    
    assert winner_id_1 == winner_id_2  # 成功合并
    
    cursor.execute("SELECT is_frozen, standard_name FROM final_exhibition_view WHERE id = ?;", (winner_id_1,))
    row_act = cursor.fetchone()
    assert row_act[0] == 0  # is_frozen = 0
    assert row_act[1] == "Nikke罗森一日店长"
    
    # 6.3 验证确定性哈希 ID 的防抖能力
    stats_sec = MaterializeService.rebuild_view()
    assert stats_sec["new_normalized_nodes"] == 3  # 重建时，已冻结的2个节点不计入新增，3个活跃节点（店长、旁路店长、BW）更新覆盖，新增为 3
    
    cursor.execute("SELECT id FROM final_exhibition_view WHERE standard_name = 'Nikke罗森一日店长';")
    assert cursor.fetchone()[0] == winner_id_1  # 两次重建 ID 保持完全一致
    
    # 6.4 验证逻辑冷冻节点
    cursor.execute("SELECT normalized_event_id FROM event_mappings WHERE raw_event_id = ?;", (raw_ev_5,))
    frozen_id_5 = cursor.fetchone()[0]
    cursor.execute("SELECT is_frozen, standard_name FROM final_exhibition_view WHERE id = ?;", (frozen_id_5,))
    row_frz = cursor.fetchone()
    assert row_frz[0] == 1  # 逻辑冷冻成功 (is_frozen = 1)
    assert row_frz[1] == "古老未知日程"

    # 6.5 验证空间自适应纠偏与自愈合并
    cursor.execute("SELECT normalized_event_id FROM event_mappings WHERE raw_event_id = ?;", (raw_ev_bw_concrete,))
    bw_winner_id_concrete = cursor.fetchone()[0]
    cursor.execute("SELECT normalized_event_id FROM event_mappings WHERE raw_event_id = ?;", (raw_ev_bw_unknown,))
    bw_winner_id_unknown = cursor.fetchone()[0]

    assert bw_winner_id_concrete == bw_winner_id_unknown  # 空间纠偏自愈合并成功！

    cursor.execute("SELECT city, standard_name FROM final_exhibition_view WHERE id = ?;", (bw_winner_id_concrete,))
    bw_node = cursor.fetchone()
    assert bw_node[0] == "上海"
    assert bw_node[1] == "Bilibili World 2026"
    
    conn.close()
    
    # 7. 验证审计日志物理落盘
    assert os.path.exists("runtime/logs/materialize_audit.json")
    with open("runtime/logs/materialize_audit.json", "r", encoding="utf-8") as f:
        log_data = json.load(f)
        assert len(log_data["new_clusters"]) >= 2
        
    # 8. 验证 CLI 控制台命令的正确执行与展示
    runner = CliRunner()
    res = runner.invoke(cli, ["materialize"])
    assert res.exit_code == 0
    assert "物化展示表及滑动去重重建成功完成" in res.output


