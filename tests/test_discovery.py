import pytest
import os
import sqlite3
import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from src.models.db_models import init_db, get_db_connection
from src.services.db_service import DBService
from src.services.discovery_service import DiscoveryService
from src.services.db.candidate_repository import CandidateRepository
from src.config import settings

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """测试用例级数据库自动隔离与重构"""
    db_file = tmp_path / "test_discovery.db"
    original_db = settings.db_path
    original_auto_approve = settings.auto_approve_candidates
    settings.db_path = str(db_file)
    settings.auto_approve_candidates = True

    frozen_now = datetime.datetime(2026, 6, 15, 12, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    monkeypatch.setattr("src.utils.time.beijing_now", lambda: frozen_now)
    monkeypatch.setattr("src.utils.time.beijing_today", lambda: frozen_now.date())
    monkeypatch.setattr("src.utils.time.beijing_today_str", lambda: "2026-06-15")
    monkeypatch.setattr("src.utils.time.beijing_now_str", lambda: "2026-06-15 12:00:00")
    monkeypatch.setattr("src.services.db.candidate_repository.beijing_now_str", lambda: "2026-06-15 12:00:00")
    monkeypatch.setattr("src.services.db.coser_repository.beijing_now_str", lambda: "2026-06-15 12:00:00")
    monkeypatch.setattr("src.utils.templates.beijing_today_str", lambda: "2026-06-15")
    init_db()
    yield
    if db_file.exists():
        db_file.unlink()
    settings.db_path = original_db
    settings.auto_approve_candidates = original_auto_approve

def test_extract_mentions():
    """测试提及（@）提取正则表达式，包含否定后顾，防止误判邮箱地址 (Finding 4)"""
    content_with_mentions = "今天和 @池咲misa 还有 @卡特Carter_ 还有 @池咲misa 贴贴！"
    mentions = DiscoveryService.extract_mentions(content_with_mentions)
    
    assert len(mentions) == 2
    assert "池咲misa" in mentions
    assert "卡特Carter_" in mentions
    
    # 邮箱地址测试，应当过滤 example.com
    content_with_email = "联系邮箱: service@example.com，或者私信 @池咲misa 合作"
    email_mentions = DiscoveryService.extract_mentions(content_with_email)
    assert len(email_mentions) == 1
    assert "池咲misa" in email_mentions
    assert "example" not in email_mentions
    
    # 空/无提及文本测试
    assert DiscoveryService.extract_mentions("") == []
    assert DiscoveryService.extract_mentions("普通碎碎念无艾特") == []

def test_prune_weibo_suffix():
    """测试 prune_weibo_suffix 函数对常见后缀的修剪功能"""
    assert DiscoveryService.prune_weibo_suffix("我才不是阿澄的微博") == "我才不是阿澄"
    assert DiscoveryService.prune_weibo_suffix("小明_coser") == "小明"
    assert DiscoveryService.prune_weibo_suffix("某某_cosplay") == "某某"
    assert DiscoveryService.prune_weibo_suffix("某某的B站") == "某某"
    assert DiscoveryService.prune_weibo_suffix("某某的bili") == "某某"
    assert DiscoveryService.prune_weibo_suffix("某某的bilibili") == "某某"
    assert DiscoveryService.prune_weibo_suffix("纯良用户") == "纯良用户"
    assert DiscoveryService.prune_weibo_suffix(None) == ""

def test_candidate_repository_crud():
    """测试 CandidateRepository 候选人增删改查及流转"""
    name = "测试候选Coser"
    platform = "bilibili"
    source_ref = "http://test.com/post/1"
    matched_uid = "123456"
    match_score = 85.5

    # 1. 插入新候选人
    success = CandidateRepository.add_candidate(
        name=name,
        platform=platform,
        source_ref=source_ref,
        matched_bili_uid=matched_uid,
        match_score=match_score
    )
    assert success is True

    # 2. 列出候选人，断言 pending 状态正确
    pending_list = CandidateRepository.list_candidates("pending")
    assert len(pending_list) == 1
    cand = pending_list[0]
    assert cand["name"] == name
    assert cand["matched_bili_uid"] == matched_uid
    assert cand["match_score"] == match_score
    assert cand["status"] == "pending"

    # 3. 批准候选人导入正式库
    cand_id = cand["id"]
    approve_success = CandidateRepository.approve_candidate(cand_id)
    assert approve_success is True

    # 确认在候选人表状态变为 approved
    approved_list = CandidateRepository.list_candidates("approved")
    assert len(approved_list) == 1
    assert approved_list[0]["id"] == cand_id
    assert approved_list[0]["status"] == "approved"

    # 确认正式 cosers 表中已成功录入且处于 active 状态
    cosers = DBService.list_cosers(only_active=True)
    assert len(cosers) == 1
    assert cosers[0]["name"] == name
    assert cosers[0]["bilibili_uid"] == matched_uid

def test_candidate_repository_merge_and_placeholders():
    """测试候选人属性合并逻辑(Finding 5)与占位符更新逻辑(Finding 6)"""
    name = "合并占位测试Coser"
    
    # 1. 初始插入 B站 UID
    CandidateRepository.add_candidate(name=name, platform="bilibili", matched_bili_uid="10001", match_score=60.0)
    
    # 2. 第二次扫描未关联到 B站 UID (None)，但关联到了微博 UID，确认不覆盖抹除 B站 UID
    CandidateRepository.add_candidate(name=name, platform="weibo", matched_bili_uid=None, matched_weibo_uid="20002", match_score=0.0)
    
    pending = CandidateRepository.list_candidates("pending")
    assert len(pending) == 1
    cand = pending[0]
    assert cand["matched_bili_uid"] == "10001"
    assert cand["matched_weibo_uid"] == "20002"
    assert cand["match_score"] == 60.0 # 得分合并为最高分

    # 3. 在正式库中预先存在同名 Coser，且部分 UID 为空字符 "" 或减号占位符 "-"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cosers (name, bilibili_uid, weibo_uid, xhs_uid, is_active) VALUES (?, '-', '', '-', 1);",
        (name,)
    )
    conn.commit()
    cursor.close()
    conn.close()

    # 4. 执行 approve，确认新 UID 成功覆盖占位符，且不清除已有数据
    approve_res = CandidateRepository.approve_candidate(cand["id"])
    assert approve_res is True

    cosers = DBService.list_cosers()
    coser = next(c for c in cosers if c["name"] == name)
    assert coser["bilibili_uid"] == "10001"  # '-' 被覆盖为 '10001'
    assert coser["weibo_uid"] == "20002"     # '' 被覆盖为 '20002'
    assert coser["xhs_uid"] == "-"            # 没有新值的保持 '-' 不变

def test_candidate_repository_reject():
    """测试拒绝/忽略候选人流程"""
    name = "被忽略的Coser"
    CandidateRepository.add_candidate(name=name, platform="weibo")
    
    pending = CandidateRepository.list_candidates("pending")
    assert len(pending) == 1
    cand_id = pending[0]["id"]

    # 忽略
    reject_success = CandidateRepository.reject_candidate(cand_id)
    assert reject_success is True

    # 确认状态更新为 ignored
    ignored = CandidateRepository.list_candidates("ignored")
    assert len(ignored) == 1
    assert ignored[0]["name"] == name
    assert ignored[0]["status"] == "ignored"

    # 确认正式表中没有被录入
    assert len(DBService.list_cosers()) == 0

@pytest.mark.asyncio
async def test_discovery_service_integration():
    """测试 DiscoveryService 提取、注册、验证与批量忽略的队列式流转 (Finding 2)"""
    posts = [
        {
            "content": "自由行和 @小红帽_cos 贴贴！",
            "post_url": "http://bili.com/dynamic/1"
        }
    ]

    # 模拟 Bilibili 搜索接口返回候选人列表
    mock_search_results = {
        "小红帽_cos": [
            {
                "uname": "小红帽_cos",
                "mid": 999888,
                "fans": 5000,
                "official_verify": {"type": 0, "desc": "知名Coser"},
                "usign": "工作联系：xxx | Coser/模特/二次元博主"
            }
        ]
    }

    with patch("src.tools.bilibili_scraper.BilibiliScraper.search_bilibili_users_batch", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_search_results

        # 发现与提取 (双步队列式执行)
        inserted_count = await DiscoveryService.discover_candidates_from_posts(posts, limit=5)
        assert inserted_count == 1

        # 检查是否成功验证，且 UID 和分数写入正确
        approved = DBService.list_candidates("approved")
        assert len(approved) == 1
        assert approved[0]["name"] == "小红帽_cos"
        assert approved[0]["matched_bili_uid"] == "999888"
        assert approved[0]["match_score"] > 0.0

@pytest.mark.asyncio
async def test_candidate_post_verification_llm_flow():
    """测试候选人博文抓取及 LLM 智能体分类评估的全套流程"""
    # 1. 注册一个 pending 候选人，且预先绑定 B站 UID
    CandidateRepository.add_candidate(
        name="测试核验用户",
        platform="bilibili",
        matched_bili_uid="1234567"
    )
    
    pending = DBService.list_candidates("pending")
    assert len(pending) == 1
    cand_id = pending[0]["id"]
    
    # 2. 模拟爬虫返回博文
    mock_posts = [
        {"post_id": "1", "content": "今天CP30第一天芙宁娜返图，欢迎来摊位找我！", "post_url": "http://t.bilibili.com/1", "published_at": "2026-06-06 20:00:00"},
        {"post_id": "2", "content": "下周六一日店长排班表出来啦！", "post_url": "http://t.bilibili.com/2", "published_at": "2026-06-05 20:00:00"},
    ]
    
    # 模拟 LLM 智能体评估返回
    mock_llm_res = {
        "is_active_coser": True,
        "confidence": 0.95,
        "reason": "博文中含有漫展返图及一日店长排班信息"
    }
    
    with patch("src.tools.bilibili_scraper.BilibiliScraper.fetch_bilibili_posts", new_callable=AsyncMock) as mock_fetch, \
         patch("src.agents.event_agent.analyze_candidate_posts", new_callable=AsyncMock) as mock_llm:
         
        mock_fetch.return_value = mock_posts
        mock_llm.return_value = mock_llm_res
        
        # 执行核验
        verified_count = await DiscoveryService.verify_pending_candidates(limit=5)
        assert verified_count == 1
        
        # 3. 验证数据库中候选人的状态被更新为 approved
        approved_after = DBService.list_candidates("approved")
        assert len(approved_after) == 1
        cand_after = approved_after[0]
        assert cand_after["is_verified"] == 1
        assert "[LLM]" in cand_after["verify_reason"]
        assert "博文中含有漫展返图及一日店长排班信息" in cand_after["verify_reason"]
        
        # 4. 验证博文在自动核验批准后，已被自动从 candidate_raw_posts 中物理清理
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM candidate_raw_posts WHERE candidate_id = ? ORDER BY id ASC;", (cand_id,))
        rows = cursor.fetchall()
        assert len(rows) == 0
        cursor.close()
        conn.close()

@pytest.mark.asyncio
async def test_candidate_post_verification_llm_negative_flow():
    """测试候选人博文经 LLM 判定为非 Coser 时的忽略逻辑"""
    CandidateRepository.add_candidate(
        name="纯生活分享用户",
        platform="weibo",
        matched_weibo_uid="8888888"
    )
    
    pending = DBService.list_candidates("pending")
    assert len(pending) == 1
    cand_id = pending[0]["id"]
    
    mock_posts = [
        {"post_id": "weibo_1", "content": "今天天气真好，吃了个火锅。", "post_url": "http://weibo.com/1", "published_at": "2026-06-06 20:00:00"},
    ]
    
    mock_llm_res = {
        "is_active_coser": False,
        "confidence": 0.99,
        "reason": "仅为日常生活的碎碎念分享"
    }
    
    with patch("src.tools.weibo_scraper.WeiboScraper.fetch_weibo_posts", new_callable=AsyncMock) as mock_fetch, \
         patch("src.agents.event_agent.analyze_candidate_posts", new_callable=AsyncMock) as mock_llm:
         
        mock_fetch.return_value = mock_posts
        mock_llm.return_value = mock_llm_res
        
        # 执行核验
        verified_count = await DiscoveryService.verify_pending_candidates(limit=5)
        assert verified_count == 0  # 判定失败，未被核验通过
        
        # 确认候选人被标记为 ignored
        ignored = DBService.list_candidates("ignored")
        assert len(ignored) == 1
        assert ignored[0]["id"] == cand_id


def test_database_shadow_table_migration(tmp_path):
    """测试 coser_candidates 的影子表重构热迁移，CHECK 约束升级及数据无损"""
    db_file = tmp_path / "test_migration.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    # 1. 创建旧版表（仅支持 pending, approved, ignored）
    cursor.execute("""
    CREATE TABLE coser_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        platform TEXT NOT NULL,
        source_ref TEXT,
        matched_bili_uid TEXT,
        matched_weibo_uid TEXT,
        matched_xhs_uid TEXT,
        match_score REAL DEFAULT 0.0,
        status TEXT DEFAULT 'pending',
        is_verified INTEGER DEFAULT 0,
        verify_reason TEXT,
        created_at TEXT,
        CHECK (status IN ('pending', 'approved', 'ignored'))
    );
    """)
    # 2. 插入测试数据
    cursor.execute("""
    INSERT INTO coser_candidates (name, platform, status, is_verified) 
    VALUES ('旧用户1', 'weibo', 'pending', 0), ('旧用户2', 'bilibili', 'approved', 1);
    """)
    conn.commit()
    conn.close()

    # 3. 运行 init_db 触发升级
    settings.db_path = str(db_file)
    init_db()

    # 4. 验证数据无损及新约束生效
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, status, is_verified FROM coser_candidates ORDER BY id ASC;")
    rows = cursor.fetchall()
    assert len(rows) == 2
    assert rows[0] == ('旧用户1', 'pending', 0)
    assert rows[1] == ('旧用户2', 'approved', 1)

    # 5. 测试插入 'undetermined'，应当成功
    try:
        cursor.execute("""
        INSERT INTO coser_candidates (name, platform, status, is_verified) 
        VALUES ('新待定用户', 'weibo', 'undetermined', 0);
        """)
        conn.commit()
    except Exception as e:
        pytest.fail(f"插入 undetermined 状态失败: {e}")

    # 6. 测试插入非法状态，应当被 CHECK 约束拒绝
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute("""
        INSERT INTO coser_candidates (name, platform, status, is_verified) 
        VALUES ('非法用户', 'weibo', 'invalid_status', 0);
        """)
        conn.commit()

    conn.close()
    if db_file.exists():
        db_file.unlink()


@pytest.mark.asyncio
async def test_candidate_strong_bio_match_bypass():
    """测试 Bio 强词匹配直接验证通过，绕过爬取和 LLM"""
    # B站官方认证命中强词 "知名Coser"
    CandidateRepository.add_candidate(
        name="强词测试Coser",
        platform="bilibili",
        matched_bili_uid="111222"
    )

    mock_profile = {
        "bio": "普通简介",
        "verify_desc": "知名Coser"
    }

    with patch("src.tools.bilibili_scraper.BilibiliScraper.resolve_uids_batch", new_callable=AsyncMock) as mock_resolve, \
         patch("src.tools.bilibili_scraper.BilibiliScraper.fetch_bilibili_posts", new_callable=AsyncMock) as mock_fetch, \
         patch("src.agents.event_agent.analyze_candidate_posts", new_callable=AsyncMock) as mock_llm:
         
        mock_resolve.return_value = {"111222": mock_profile}
        
        verified_count = await DiscoveryService.verify_pending_candidates(limit=5)
        assert verified_count == 1

        # 验证没有调用 LLM 和博文抓取
        mock_fetch.assert_not_called()
        mock_llm.assert_not_called()

        # 检查是否成功标记通过且原因为 "Bio 关键词匹配成功"
        approved = DBService.list_candidates("approved")
        assert len(approved) == 1
        assert approved[0]["is_verified"] == 1
        assert approved[0]["verify_reason"] == "Bio 关键词匹配成功"


@pytest.mark.asyncio
async def test_adaptive_crawling_limit_and_undetermined():
    """测试弱词下自适应抓取 limit=10 与低置信度下的 undetermined 软状态及博文清理"""
    # 名字含 cos 作为弱特征
    CandidateRepository.add_candidate(
        name="弱特征cos博主",
        platform="weibo",
        matched_weibo_uid="333444"
    )

    # 普通无特征博主
    CandidateRepository.add_candidate(
        name="普通路人博主",
        platform="weibo",
        matched_weibo_uid="555666"
    )

    mock_weibo_user_1 = {"idstr": "333444", "description": "日常分享"}
    mock_weibo_user_2 = {"idstr": "555666", "description": "分享美食与日常生活"}

    mock_posts = [
        {"post_id": "1", "content": "日常发博", "post_url": "http://weibo.com/1", "published_at": "2026-06-06 12:00:00"}
    ]

    # 模拟第一个弱特征博主 LLM 判定为 False 且低置信度 -> undetermined
    mock_llm_res_1 = {
        "is_active_coser": False,
        "confidence": 0.65,
        "reason": "博文暂无明确证据"
    }

    # 模拟第二个普通博主 LLM 判定为 False 且高置信度 -> ignored
    mock_llm_res_2 = {
        "is_active_coser": False,
        "confidence": 0.95,
        "reason": "确定是纯美食生活账号"
    }

    with patch("src.tools.weibo_scraper.WeiboScraper.resolve_screen_names_batch", new_callable=AsyncMock) as mock_resolve_names, \
         patch("src.tools.weibo_scraper.WeiboScraper.fetch_weibo_posts", new_callable=AsyncMock) as mock_fetch, \
         patch("src.agents.event_agent.analyze_candidate_posts", new_callable=AsyncMock) as mock_llm:
         
        mock_resolve_names.return_value = {
            "弱特征cos博主": mock_weibo_user_1,
            "普通路人博主": mock_weibo_user_2
        }
        mock_fetch.return_value = mock_posts
        
        # 依次为两个候选人做 LLM 结果的侧写
        mock_llm.side_effect = [mock_llm_res_1, mock_llm_res_2]

        await DiscoveryService.verify_pending_candidates(limit=5)

        # 检查 fetch 调用的 limit 参数是否自适应：
        # 第一个弱特征：limit=10，第二个普通：limit=3
        fetch_calls = mock_fetch.call_args_list
        assert len(fetch_calls) == 2
        # weibo_uid 333444 的 limit 应为 10
        assert fetch_calls[0][0][0] == "333444"
        assert fetch_calls[0][1]["limit"] == 10
        # weibo_uid 555666 的 limit 应为 3
        assert fetch_calls[1][0][0] == "555666"
        assert fetch_calls[1][1]["limit"] == 3

        # 检查数据库状态流转
        # 弱特征博主由于低置信度，状态更新为 undetermined
        undetermined_list = CandidateRepository.list_candidates("undetermined")
        assert len(undetermined_list) == 1
        assert undetermined_list[0]["name"] == "弱特征cos博主"
        assert undetermined_list[0]["is_verified"] == 0

        # 普通博主由于高置信度，状态更新为 ignored
        ignored_list = CandidateRepository.list_candidates("ignored")
        assert len(ignored_list) == 1
        assert ignored_list[0]["name"] == "普通路人博主"

        # 验证两者的临时博文在 candidate_raw_posts 中均已被物理清理
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM candidate_raw_posts;")
        count = cursor.fetchone()[0]
        assert count == 0
        cursor.close()
        conn.close()


@pytest.mark.asyncio
async def test_priority_queue_and_cooldown_filter():
    """测试验证队列中 undetermined 的 7 天冷却期以及 pending 优先级的 SQL 排序"""
    beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(beijing_tz)

    # 1. 插入四种测试候选人
    conn = get_db_connection()
    cursor = conn.cursor()
    # 候选人A: undetermined 且冷却未过（3天前创建）
    three_days_ago = (now - datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO coser_candidates (name, platform, status, status_updated_at, created_at, is_verified) 
    VALUES ('待定冷却中Coser', 'weibo', 'undetermined', ?, ?, 0);
    """, (three_days_ago, three_days_ago))

    # 候选人B: undetermined 且冷却已过（8天前创建）
    eight_days_ago = (now - datetime.timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO coser_candidates (name, platform, status, status_updated_at, created_at, is_verified) 
    VALUES ('待定已过期Coser', 'weibo', 'undetermined', ?, ?, 0);
    """, (eight_days_ago, eight_days_ago))

    # 候选人C: 全新录入的 pending
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO coser_candidates (name, platform, status, status_updated_at, created_at, is_verified) 
    VALUES ('全新Pending博主', 'weibo', 'pending', ?, ?, 0);
    """, (now_str, now_str))
    conn.commit()
    cursor.close()
    conn.close()

    # 2. 调用真实的 verify_pending_candidates 并通过 Mock 捕获其捞取和排序结果
    with patch("src.tools.weibo_scraper.WeiboScraper.resolve_screen_names_batch", new_callable=AsyncMock) as mock_resolve, \
         patch("src.tools.weibo_scraper.WeiboScraper.fetch_weibo_posts", new_callable=AsyncMock) as mock_fetch, \
         patch("src.agents.event_agent.analyze_candidate_posts", new_callable=AsyncMock) as mock_llm:
         
        mock_resolve.return_value = {}
        mock_fetch.return_value = []
        mock_llm.return_value = {"is_active_coser": False, "confidence": 0.9}
        
        await DiscoveryService.verify_pending_candidates(limit=5)

        # 3. 验证过滤结果与优先级排序：
        # mock_resolve 的 call 参数应该包含且仅包含 "全新Pending博主" 和 "待定已过期Coser"，
        # 且 "全新Pending博主" (pending) 排序优先于 "待定已过期Coser" (undetermined)。
        # "待定冷却中Coser" (在7天冷却期内) 绝不应该被捞出解析。
        assert mock_resolve.called
        called_names = mock_resolve.call_args[0][0]
        assert len(called_names) == 2
        assert called_names[0] == "全新Pending博主"
        assert called_names[1] == "待定已过期Coser"


@pytest.mark.asyncio
async def test_discovery_weibo_uid_cross_verification():
    """测试 B站 来源候选人如果绑定了 weibo_uid，可以通过该 UID 反向解析其微博 profile 进行交叉核验"""
    CandidateRepository.add_candidate(
        name="反向交叉测试Coser",
        platform="bilibili",
        matched_bili_uid="111",
        matched_weibo_uid="888"
    )

    mock_weibo_profile = {
        "idstr": "888",
        "screen_name": "微博小号",
        "description": "二次元排班嘉宾Coser" # 微博命中强词
    }
    
    mock_bili_profile = {
        "bio": "普通非Coser日常",
        "verify_desc": ""
    }

    with patch("src.tools.weibo_scraper.WeiboScraper.resolve_uids_batch", new_callable=AsyncMock) as mock_weibo_uid_resolve, \
         patch("src.tools.bilibili_scraper.BilibiliScraper.resolve_uids_batch", new_callable=AsyncMock) as mock_bili_uid_resolve, \
         patch("src.tools.bilibili_scraper.BilibiliScraper.fetch_bilibili_posts", new_callable=AsyncMock) as mock_fetch, \
         patch("src.agents.event_agent.analyze_candidate_posts", new_callable=AsyncMock) as mock_llm:
         
        mock_weibo_uid_resolve.return_value = {"888": mock_weibo_profile}
        mock_bili_uid_resolve.return_value = {"111": mock_bili_profile}

        verified_count = await DiscoveryService.verify_pending_candidates(limit=5)
        assert verified_count == 1
        
        # 强匹配通过直接确权，不应该调用博文爬取和大模型
        mock_fetch.assert_not_called()
        mock_llm.assert_not_called()

        approved = DBService.list_candidates("approved")
        assert len(approved) == 1
        assert approved[0]["name"] == "反向交叉测试Coser"
        assert approved[0]["is_verified"] == 1
        assert approved[0]["verify_reason"] == "Bio 关键词匹配成功"


@pytest.mark.asyncio
async def test_candidate_verification_no_auto_approve():
    """测试 settings.auto_approve_candidates = False 时，通过核验的候选人保留 pending 状态，不自动导入正式库，且不清理博文"""
    # 启用手动把关，关闭自动审批
    settings.auto_approve_candidates = False
    try:
        # 1. 注册两个候选人：一个强特征的 A，一个走 LLM 核验的 B
        # 候选人 A (强特征)
        CandidateRepository.add_candidate(
            name="强特征未自动审批Coser",
            platform="bilibili",
            matched_bili_uid="999111"
        )
        # 候选人 B (普通特征)
        CandidateRepository.add_candidate(
            name="LLM未自动审批用户",
            platform="bilibili",
            matched_bili_uid="999222"
        )
        
        mock_profile_a = {
            "bio": "普通简介",
            "verify_desc": "知名Coser" # 强特征词
        }
        mock_profile_b = {
            "bio": "普通简介",
            "verify_desc": ""
        }
        
        mock_posts = [
            {"post_id": "b_1", "content": "今天CP30第一天返图，芙宁娜赛高！", "post_url": "http://t.bilibili.com/b_1", "published_at": "2026-06-06 20:00:00"}
        ]
        
        mock_llm_res = {
            "is_active_coser": True,
            "confidence": 0.95,
            "reason": "博文含有漫展返图及角色扮演信息"
        }
        
        with patch("src.tools.bilibili_scraper.BilibiliScraper.resolve_uids_batch", new_callable=AsyncMock) as mock_resolve, \
             patch("src.tools.bilibili_scraper.BilibiliScraper.fetch_bilibili_posts", new_callable=AsyncMock) as mock_fetch, \
             patch("src.agents.event_agent.analyze_candidate_posts", new_callable=AsyncMock) as mock_llm:
             
            mock_resolve.return_value = {
                "999111": mock_profile_a,
                "999222": mock_profile_b
            }
            mock_fetch.return_value = mock_posts
            mock_llm.return_value = mock_llm_res
            
            # 执行核验
            verified_count = await DiscoveryService.verify_pending_candidates(limit=5)
            # 两个候选人都通过了核验（A 通过强特征，B 通过 LLM）
            assert verified_count == 2
            
            # 2. 检查候选人表中的状态：应该都依然是 pending，但 is_verified=1
            pending_list = DBService.list_candidates("pending")
            # 两个候选人都在 pending 列表中
            names_in_pending = {c["name"] for c in pending_list}
            assert "强特征未自动审批Coser" in names_in_pending
            assert "LLM未自动审批用户" in names_in_pending
            
            cand_a = next(c for c in pending_list if c["name"] == "强特征未自动审批Coser")
            cand_b = next(c for c in pending_list if c["name"] == "LLM未自动审批用户")
            
            assert cand_a["is_verified"] == 1
            assert cand_a["verify_reason"] == "Bio 关键词匹配成功"
            
            assert cand_b["is_verified"] == 1
            assert "[LLM]" in cand_b["verify_reason"]
            assert "博文含有漫展返图" in cand_b["verify_reason"]
            
            # 3. 检查正式 cosers 表：不应有这两个 Coser
            cosers = DBService.list_cosers()
            cosers_names = {c["name"] for c in cosers}
            assert "强特征未自动审批Coser" not in cosers_names
            assert "LLM未自动审批用户" not in cosers_names
            
            # 4. 检查隔离的博文表：由于没有自动审批，候选人 B 的博文数据不应该被物理清理
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT content FROM candidate_raw_posts WHERE candidate_id = ?;", (cand_b["id"],))
            rows = cursor.fetchall()
            assert len(rows) > 0
            assert "芙宁娜赛高" in rows[0][0]
            cursor.close()
            conn.close()
            
            # 5. 测试手动审批候选人 B，确认可以成功导入并清理博文
            approve_success = DBService.approve_candidate(cand_b["id"])
            assert approve_success is True
            
            # 验证 B 移出 pending 列表进入 approved
            pending_list_after = DBService.list_candidates("pending")
            assert "LLM未自动审批用户" not in {c["name"] for c in pending_list_after}
            
            approved_list = DBService.list_candidates("approved")
            assert "LLM未自动审批用户" in {c["name"] for c in approved_list}
            
            # 验证 B 成功录入 cosers
            cosers_after = DBService.list_cosers()
            assert "LLM未自动审批用户" in {c["name"] for c in cosers_after}
            
            # 验证 B 的博文已被物理清理
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM candidate_raw_posts WHERE candidate_id = ?;", (cand_b["id"],))
            count = cursor.fetchone()[0]
            assert count == 0
            cursor.close()
            conn.close()
            
    finally:
        # 恢复默认设置
        settings.auto_approve_candidates = True


@pytest.mark.asyncio
async def test_candidate_empty_posts_keep_pending():
    """候选人抓取无可核验证据时保留 pending，不直接 hard-ignore。"""
    CandidateRepository.add_candidate(
        name="空结果待重试候选人",
        platform="bilibili",
        matched_bili_uid="777001"
    )

    with patch("src.tools.bilibili_scraper.BilibiliScraper.resolve_uids_batch", new_callable=AsyncMock) as mock_resolve, \
         patch("src.tools.bilibili_scraper.BilibiliScraper.fetch_bilibili_posts", new_callable=AsyncMock) as mock_fetch, \
         patch("src.agents.event_agent.analyze_candidate_posts", new_callable=AsyncMock) as mock_llm:

        mock_resolve.return_value = {"777001": {"bio": "普通简介", "verify_desc": ""}}
        mock_fetch.return_value = []

        verified_count = await DiscoveryService.verify_pending_candidates(limit=5)

    assert verified_count == 0
    mock_llm.assert_not_called()

    pending = CandidateRepository.list_candidates("pending")
    assert len(pending) == 1
    assert pending[0]["name"] == "空结果待重试候选人"
    assert pending[0]["is_verified"] == 0
    assert CandidateRepository.list_candidates("ignored") == []


def test_candidate_rediscovery_preserves_verified_state():
    """重复发现同名候选人时保留 is_verified 与 verify_reason，并合并新增 UID。"""
    CandidateRepository.add_candidate(
        name="已核验待审批候选人",
        platform="weibo",
        matched_weibo_uid="100001",
        is_verified=1,
        verify_reason="[LLM] 已确认是活跃 Coser"
    )

    CandidateRepository.add_candidate(
        name="已核验待审批候选人",
        platform="bilibili",
        matched_bili_uid="200002",
        is_verified=0,
        verify_reason=None
    )

    pending = CandidateRepository.list_candidates("pending")
    assert len(pending) == 1
    cand = pending[0]
    assert cand["is_verified"] == 1
    assert cand["verify_reason"] == "[LLM] 已确认是活跃 Coser"
    assert cand["matched_weibo_uid"] == "100001"
    assert cand["matched_bili_uid"] == "200002"
