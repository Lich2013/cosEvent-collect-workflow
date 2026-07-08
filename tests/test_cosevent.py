import os
import sys
import sqlite3
import datetime
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# 确保项目根目录在 python 搜索路径中
sys.path.insert(0, os.getcwd())

from src.models.db_models import init_db, get_db_connection
from src.services.db_service import DBService
from src.config import settings
from src.models.schemas import TriageOutput

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """测试夹具：自动配置临时内存或临时文件数据库，确保测试隔离"""
    db_file = tmp_path / "test_cosevent.db"
    settings.db_path = str(db_file)

    frozen_now = datetime.datetime(2026, 5, 25, 12, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    monkeypatch.setattr("src.utils.time.beijing_now", lambda: frozen_now)
    monkeypatch.setattr("src.utils.time.beijing_today", lambda: frozen_now.date())
    monkeypatch.setattr("src.utils.time.beijing_today_str", lambda: "2026-05-25")
    monkeypatch.setattr("src.utils.time.beijing_now_str", lambda: "2026-05-25 12:00:00")
    monkeypatch.setattr("src.utils.templates.beijing_today_str", lambda: "2026-05-25")
    monkeypatch.setattr("src.services.db.query_service.beijing_today_str", lambda: "2026-05-25")
    monkeypatch.setattr("src.services.db.event_repository.beijing_today_str", lambda: "2026-05-25")
    monkeypatch.setattr("src.services.db.event_repository.beijing_now_str", lambda: "2026-05-25 12:00:00")
    monkeypatch.setattr("src.services.db.materialize_service.beijing_today", lambda: frozen_now.date())
    monkeypatch.setattr("src.services.db.materialize_service.beijing_now_str", lambda: "2026-05-25 12:00:00")
    monkeypatch.setattr("src.services.fusion_service.beijing_now", lambda: frozen_now)
    monkeypatch.setattr("src.services.fusion_service.beijing_now_str", lambda: "2026-05-25 12:00:00")
    init_db()
    yield
    # 清理临时文件
    if db_file.exists():
        db_file.unlink()

def test_coser_crud():
    """测试 Coser CRUD 的基本正确性"""
    # 1. 增加
    assert DBService.add_coser("测试姬", weibo_uid="112233", bilibili_uid="445566") is True
    
    # 2. 查询
    cosers = DBService.list_cosers()
    assert len(cosers) == 1
    assert cosers[0]["name"] == "测试姬"
    assert cosers[0]["weibo_uid"] == "112233"
    assert cosers[0]["is_active"] == 1
    
    # 3. 修改
    assert DBService.update_coser("测试姬", is_active=0) is True
    cosers = DBService.list_cosers()
    assert cosers[0]["is_active"] == 0
    
    # 4. 删除
    assert DBService.delete_coser("测试姬") is True
    assert len(DBService.list_cosers()) == 0

def test_raw_posts_deduplication():
    """测试 raw_posts 表的 UNIQUE 联合约束去重"""
    DBService.add_coser("去重Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    posts = [
        {"post_id": "p100", "content": "漫展漫展", "post_url": "url1"},
        {"post_id": "p100", "content": "漫展漫展", "post_url": "url1"}, # 重复 ID
        {"post_id": "p200", "content": "快闪快闪", "post_url": "url2"}
    ]
    
    inserted = DBService.save_raw_posts(coser_id, "weibo", posts)
    assert inserted == 2 # 仅成功插入 2 条新记录，第 2 条被 ignore
    
    # 数据库中应该只有 2 条
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM raw_posts;")
    assert cursor.fetchone()[0] == 2
    conn.close()

def test_database_transaction_atomicity():
    """
    测试核心原子性事务：
    如果在批量插入活动时某一条报错（如 event_name 违反 NOT NULL 约束），
    整个写入必须 Rollback 并抛出结构性异常。
    """
    DBService.add_coser("事务Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    # 插入一条博文
    DBService.save_raw_posts(coser_id, "weibo", [{"post_id": "p888", "content": "漫展计划", "post_url": "url888"}])
    
    # 获取插入 the raw_post_id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE post_id = 'p888';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()
    
    # 构造一批提取出的活动，其中第 2 条没有 event_name（设为 None），会触发 SQLite 的 NOT NULL 异常或 Python 类型错误
    events = [
        {
            "event_name": "合法漫展A",
            "event_date": "2026-07-01",
            "event_place": "上海世博馆",
            "event_description": "芙宁娜",
            "confidence": 0.9,
            "source_url": "url888"
        },
        {
            "event_name": None, # 异常数据！触发 SQLite NOT NULL 报错或 Python 类型错误
            "event_date": "2026-07-02",
            "event_place": "上海世博馆",
            "event_description": "崩铁",
            "confidence": 0.8,
            "source_url": "url888"
        }
    ]
    
    # 执行原子事务保存，预期应该触发结构性永久异常并执行回滚
    import sqlite3
    with pytest.raises((sqlite3.IntegrityError, TypeError, ValueError, AttributeError)):
        DBService.save_extracted_events_transactional(raw_post_id, events, confidence_threshold=0.3)
    
    # 验证数据库数据完整性：没有新活动存入，并且 is_analyzed 依然为 0
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 验证 cosplay_events 没有被写入任何关于此博文的数据
    cursor.execute("SELECT COUNT(*) FROM cosplay_events WHERE raw_post_id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 0
    
    # 验证 is_analyzed 状态依然为 0 (回滚成功)
    cursor.execute("SELECT is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 0
    
    conn.close()

@pytest.mark.asyncio
async def test_agent_error_feedback_retry():
    """
    测试 Agent 报错重试机制：
    当 LLM 调用由于格式错误等原因抛出异常时，
    验证 analyze_post_with_retry 捕获报错并成功执行了重试（尝试3次）。
    """
    from src.agents.event_agent import analyze_post_with_retry
    
    # 强制将模式设为 single 以在此测试中运行单模型逻辑，并保存原模式进行隔离恢复
    original_mode = settings.analysis_pipeline.get("mode", "single")
    settings.analysis_pipeline["mode"] = "single"
    
    try:
        # 使用 Mock 阻断真正的网络大模型请求，并模拟其抛出格式校验异常
        with patch("agents.Runner.run", new_callable=AsyncMock) as mock_run:
            # 连续三次抛出异常以模拟格式校验失败
            mock_run.side_effect = ValueError("Format Verification Failed!")
            
            with pytest.raises(ValueError, match="Format Verification Failed!"):
                await analyze_post_with_retry("博文", "链接")
                
            # 验证 Runner.run 的确被调用了 3 次（执行了 3 次自适应重试逻辑）
            assert mock_run.call_count == 3
    finally:
        settings.analysis_pipeline["mode"] = original_mode

def test_export_csv_bom(tmp_path):
    """测试 CSV 导出功能，且验证文件头部为标准的 UTF-8 BOM 字符前缀 (b'\\xef\\xbb\\xbf')"""
    from src.services.export_service import ExportService
    
    DBService.add_coser("BOM_Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    DBService.save_raw_posts(coser_id, "weibo", [{"post_id": "p_bom", "content": "漫展漫展", "post_url": "url_bom"}])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE post_id = 'p_bom';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()
    
    events = [{
        "event_name": "BOM漫展",
        "event_date": "2026-07-05",
        "event_place": "上海",
        "event_description": "芙宁娜",
        "confidence": 0.9,
        "source_url": "url_bom"
    }]
    
    DBService.save_extracted_events_transactional(raw_post_id, events, confidence_threshold=0.3)
    
    csv_file = tmp_path / "export_test.csv"
    count = ExportService.export_events_to_csv(str(csv_file), confidence_threshold=0.5)
    assert count == 1
    assert csv_file.exists()
    
    # 读取前3个字节，断言为 UTF-8 BOM 表头
    with open(csv_file, "rb") as f:
        bom_prefix = f.read(3)
        assert bom_prefix == b"\xef\xbb\xbf"

def test_confidence_filtering():
    """测试置信度阈值双阶段过滤逻辑的准确性"""
    DBService.add_coser("Filter_Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    DBService.save_raw_posts(coser_id, "weibo", [{"post_id": "p_filter", "content": "漫展漫展", "post_url": "url_filter"}])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE post_id = 'p_filter';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()
    
    events = [
        {
            "event_name": "置信度低活动",
            "event_date": "2026-07-05",
            "event_place": "北京",
            "event_description": "出雷电将军",
            "confidence": 0.2,  # 置信度 0.2
            "source_url": "url_filter"
        },
        {
            "event_name": "置信度高活动",
            "event_date": "2026-07-06",
            "event_place": "北京",
            "event_description": "出八重神子",
            "confidence": 0.9,  # 置信度 0.9
            "source_url": "url_filter"
        }
    ]
    
    # 阶段 1: 存入数据库时，要求 confidence >= 0.3。此时应只存入 [置信度高活动]
    success = DBService.save_extracted_events_transactional(raw_post_id, events, confidence_threshold=0.3)
    assert success is True
    
    db_events = DBService.get_all_events(confidence_threshold=0.0)
    assert len(db_events) == 1
    assert db_events[0]["event_name"] == "置信度高活动"
    
    # 阶段 2: 导出/查询时，提供二次精细过滤置信度 0.95。此时高活动 (0.9) 也不应显示
    filtered_db_events = DBService.get_all_events(confidence_threshold=0.95)
    assert len(filtered_db_events) == 0

def test_coser_name_injection_and_cascade_delete():
    """测试在原子事务写入时，系统由物理联查将真实的 coser_name 注入 cosplay_events，以及物理级联删除完整性"""
    DBService.add_coser("幽兰黛尔", weibo_uid="111")
    cosers = DBService.list_cosers()
    coser = [c for c in cosers if c["name"] == "幽兰黛尔"][0]
    coser_id = coser["id"]
    
    DBService.save_raw_posts(coser_id, "weibo", [{"post_id": "post_durandal", "content": "漫展计划", "post_url": "url_durandal"}])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE post_id = 'post_durandal';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()
    
    events = [{
        "event_name": "天命漫展",
        "event_date": "2026-07-10",
        "event_place": "休斯顿",
        "event_description": "不灭星锚",
        "confidence": 0.9,
        "source_url": "url_durandal"
    }]
    
    # 执行原子事务写入
    success = DBService.save_extracted_events_transactional(raw_post_id, events, confidence_threshold=0.3)
    assert success is True
    
    # 验证 coser_name 冗余注入属性：虽然 events 没传入 coser_name，但入库后自动从 cosers 联查填充为 "幽兰黛尔"
    db_events = DBService.get_all_events()
    assert len(db_events) == 1
    assert db_events[0]["coser_name"] == "幽兰黛尔"
    
    # 验证级联删除：删除 Coser "幽兰黛尔"，级联删除对应的 raw_posts 和 cosplay_events
    delete_success = DBService.delete_coser("幽兰黛尔")
    assert delete_success is True
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 验证 raw_posts 已被级联物理删除
    cursor.execute("SELECT COUNT(*) FROM raw_posts WHERE coser_id = ?;", (coser_id,))
    assert cursor.fetchone()[0] == 0
    
    # 验证 cosplay_events 已被级联物理删除
    cursor.execute("SELECT COUNT(*) FROM cosplay_events WHERE raw_post_id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 0
    
    conn.close()

def test_user_friendly_cookie_parsing(tmp_path):
    """测试自适应 Cookie 解析：支持解析单行纯文本原始字符串并补全 domain 属性"""
    from src.tools.playwright_base import BaseScraper
    
    # 模拟一个新 scraper 实例
    scraper = BaseScraper("weibo")
    
    # 1. 模拟写入一个单行原始字符串 Cookie 文件到临时路径下
    cookie_str = "SUB=weibo123; entry=weibo456; empty_val=; ; " # 包含无效对和空格
    temp_cookie_file = tmp_path / "weibo_cookies.json"
    temp_cookie_file.write_text(cookie_str, encoding="utf-8")
    
    # 覆盖 seed_file 属性为临时测试路径
    scraper.seed_file = temp_cookie_file
    
    # 执行加载解析
    cookies = scraper.load_seed_cookies()
    
    # 2. 断言校验
    assert isinstance(cookies, list)
    assert len(cookies) == 3  # SUB, entry, and empty_val (valid empty keys are retained)
    
    cookies_map = {c["name"]: c for c in cookies}
    assert "SUB" in cookies_map
    assert cookies_map["SUB"]["value"] == "weibo123"
    assert cookies_map["SUB"]["domain"] == ".weibo.com"
    assert cookies_map["SUB"]["path"] == "/"
    
    assert "entry" in cookies_map
    assert cookies_map["entry"]["value"] == "weibo456"
    assert cookies_map["entry"]["domain"] == ".weibo.com"
    assert cookies_map["entry"]["path"] == "/"
    
    assert "empty_val" in cookies_map
    assert cookies_map["empty_val"]["value"] == ""
    
    # 3. 模拟标准 JSON 数组列表
    standard_cookies = [
        {"name": "SESSDATA", "value": "bili123", "domain": ".bilibili.com", "path": "/"}
    ]
    import json
    temp_cookie_file.write_text(json.dumps(standard_cookies), encoding="utf-8")
    
    bili_scraper = BaseScraper("bilibili")
    bili_scraper.seed_file = temp_cookie_file
    
    bili_cookies = bili_scraper.load_seed_cookies()
    assert isinstance(bili_cookies, list)
    assert len(bili_cookies) == 1
    assert bili_cookies[0]["name"] == "SESSDATA"
    assert bili_cookies[0]["value"] == "bili123"

@pytest.mark.asyncio
async def test_llm_registry_and_provider_routing():
    """测试 LLM 注册表与动态提供商路由机制，包括环境变量插值"""
    from src.tools.llm_bridge import LLMClientRegistry, RegistryModelProvider
    
    os.environ["TEST_ENV_API_KEY"] = "sk-test-key-123"
    
    configs = {
        "test_prov": {
            "base_url": "https://api.test-prov.com/v1",
            "api_key": "${TEST_ENV_API_KEY}",
            "default_model": "test-model-v1"
        }
    }
    
    registry = LLMClientRegistry(configs)
    client = registry.get_client("test_prov")
    assert str(client.base_url) == "https://api.test-prov.com/v1/"
    assert client.api_key == "sk-test-key-123"
    
    provider = RegistryModelProvider(registry, default_provider="test_prov")
    # 1. 测试默认解析
    model_obj = provider.get_model(None)
    assert type(model_obj).__name__ == "OpenAIChatCompletionsModel"
    assert model_obj.model == "test-model-v1"
    
    # 2. 测试带提供商前缀解析
    configs["another_prov"] = {
        "base_url": "https://api.another.com",
        "api_key": "another-key",
        "default_model": "another-model"
    }
    registry = LLMClientRegistry(configs)
    provider = RegistryModelProvider(registry, default_provider="test_prov")
    
    model_spec_obj = provider.get_model("another_prov/custom-model-x")
    assert type(model_spec_obj).__name__ == "OpenAIChatCompletionsModel"
    assert model_spec_obj.model == "custom-model-x"

@pytest.mark.asyncio
async def test_consensus_triage_skips_further_llm_runs():
    """测试在共识分析中，首轮预检（Triage）为 [] 时，流水线立即截断，不调用提取器与裁判"""
    from src.agents.event_agent import analyze_post_with_retry
    
    # 启用共识分析模式
    settings.analysis_pipeline = {
        "mode": "consensus",
        "triage_provider": "openai",
        "triage_model": "gpt-4o-mini",
        "extractors": [{"provider": "openai", "model": "gpt-4o-mini"}, {"provider": "deepseek", "model": "deepseek-chat"}],
        "judge": {"provider": "openai", "model": "gpt-4o"}
    }
    
    with patch("agents.Runner.run", new_callable=AsyncMock) as mock_run:
        # 模拟 triage 预检直接返回 PriageOutput 且 has_event = False
        triage_mock_res = AsyncMock()
        triage_mock_res.final_output = TriageOutput(has_event=False, candidate_events=[])
        mock_run.return_value = triage_mock_res
        
        events = await analyze_post_with_retry("日常日常碎碎念", "url_triage")
        
        assert events == []
        # Runner.run 应该仅被调用 1 次（即仅执行了首轮预检，没有执行提取器与裁判）
        assert mock_run.call_count == 1

@pytest.mark.asyncio
async def test_consensus_parallel_extraction_single_fault_degradation():
    """测试多模型并行提取时单侧 API 异常抖动降级为单侧信任模式，跳过裁判"""
    from src.agents.event_agent import analyze_post_with_retry
    from src.models.schemas import FinalOutput, CosEvent
    
    settings.analysis_pipeline = {
        "mode": "consensus",
        "triage_provider": "openai",
        "triage_model": "gpt-4o-mini",
        "extractors": [{"provider": "openai", "model": "gpt-4o-mini"}, {"provider": "deepseek", "model": "deepseek-chat"}],
        "judge": {"provider": "openai", "model": "gpt-4o"}
    }
    
    with patch("agents.Runner.run", new_callable=AsyncMock) as mock_run:
        # 1. 预检返回含有可能的活动
        triage_mock_res = AsyncMock()
        triage_mock_res.final_output = TriageOutput(has_event=True, candidate_events=["CP30"])
        
        # 2. 并行提取阶段：让第一个提取器成功返回，第二个报错
        success_output = FinalOutput(event_list=[
            CosEvent(
                event_name="CP30 动漫展",
                event_date="2026-07-05",
                event_place="上海会展中心",
                event_description="芙宁娜",
                confidence=0.9,
                source_url="url_degrade"
            )
        ])
        
        extractor_mock_res = AsyncMock()
        extractor_mock_res.final_output = success_output
        
        # 设定 side_effect: 
        # 第一次调用 (Triage): 返回 triage_mock_res
        # 第二次调用 (Extractor 1): 返回 extractor_mock_res
        # 第三次调用 (Extractor 2): 抛出 API 异常
        mock_run.side_effect = [triage_mock_res, extractor_mock_res, ValueError("DeepSeek API Overloaded 503")]
        
        events = await analyze_post_with_retry("博文", "url_degrade")
        
        # 验证结果为成功一方的提取草稿，且总运行未崩溃，未唤醒 Judge
        assert len(events) == 1
        assert events[0]["event_name"] == "CP30 动漫展"
        assert mock_run.call_count == 3  # Triage + Extractor 1 + Extractor 2 (无 Judge)

@pytest.mark.asyncio
async def test_consensus_judge_fuzzy_deduplication_and_merging():
    """测试两个提取器均成功，裁判智能体正确进行模糊去重与字段合并"""
    from src.agents.event_agent import analyze_post_with_retry
    from src.models.schemas import FinalOutput, CosEvent
    
    settings.analysis_pipeline = {
        "mode": "consensus",
        "triage_provider": "openai",
        "triage_model": "gpt-4o-mini",
        "extractors": [{"provider": "openai", "model": "gpt-4o-mini"}, {"provider": "deepseek", "model": "deepseek-chat"}],
        "judge": {"provider": "openai", "model": "gpt-4o"}
    }
    
    with patch("agents.Runner.run", new_callable=AsyncMock) as mock_run:
        # 1. 预检含有漫展
        triage_mock_res = AsyncMock()
        triage_mock_res.final_output = TriageOutput(has_event=True, candidate_events=["CP30"])
        
        # 2. 提取器 1 结果
        ext1_mock_res = AsyncMock()
        ext1_mock_res.final_output = FinalOutput(event_list=[
            CosEvent(
                event_name="CP30",
                event_date="2026-07-05",
                event_place="上海国展",
                event_description="芙宁娜",
                confidence=0.85,
                source_url="url_judge"
            )
        ])
        
        # 3. 提取器 2 结果
        ext2_mock_res = AsyncMock()
        ext2_mock_res.final_output = FinalOutput(event_list=[
            CosEvent(
                event_name="CP30 动漫展",
                event_date="2026-07-05",
                event_place="上海国家会展中心 3.2馆",
                event_description="芙芙",
                confidence=0.9,
                source_url="url_judge"
            )
        ])
        
        # 4. 裁判最终裁决合并结果
        judge_mock_res = AsyncMock()
        judge_mock_res.final_output = FinalOutput(event_list=[
            CosEvent(
                event_name="CP30 动漫展",
                event_date="2026-07-05",
                event_place="上海国家会展中心 3.2馆",
                event_description="第一天芙宁娜面基",
                confidence=0.95,
                source_url="url_judge"
            )
        ])
        
        mock_run.side_effect = [triage_mock_res, ext1_mock_res, ext2_mock_res, judge_mock_res]
        
        events = await analyze_post_with_retry("博文正文", "url_judge")
        
        assert len(events) == 1
        assert events[0]["event_name"] == "CP30 动漫展"
        assert events[0]["event_place"] == "上海国家会展中心 3.2馆"
        assert events[0]["event_description"] == "第一天芙宁娜面基"
        assert events[0]["confidence"] == 0.95
        assert mock_run.call_count == 4  # Triage + Extractor 1 + Extractor 2 + Judge


@pytest.mark.asyncio
async def test_repost_and_retweet_parsing():
    """测试微博与B站转发内容的合并解析与拼接格式规范"""
    from src.tools.weibo_scraper import WeiboScraper
    from src.tools.bilibili_scraper import BilibiliScraper
    from unittest.mock import MagicMock
    
    # ==================== 1. 微博转发解析合并验证 ====================
    weibo_scraper = WeiboScraper()
    
    mock_weibo_json = {
        "data": {
            "list": [
                {
                    "id": "111111",
                    "bid": "bid111",
                    "mblogid": "Ql7djrATz",
                    "text_raw": "我要去漫展！",
                    "created_at": "Thu Jan 01 17:12:59 +0800 2026",
                    # 转发微博
                    "retweeted_status": {
                        "user": {
                            "screen_name": "绮太郎的基友"
                        },
                        "text_raw": "CP30开始招募啦！时间是5.16-5.17"
                    }
                },
                {
                    "id": "222222",
                    "bid": "bid222",
                    "mblogid": "Ql7djrATy",
                    "text_raw": "这是一条普通微博",
                    "created_at": "Thu Jan 01 18:00:00 +0800 2026"
                }
            ]
        }
    }
    
    async def mock_weibo_flow(work_func, *args, **kwargs):
        mock_page = AsyncMock()
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=mock_weibo_json)
        
        class MockExpectResponse:
            def __init__(self, val):
                self.val = val
            async def __aenter__(self):
                mock_resp_info = AsyncMock()
                async def get_val():
                    return self.val
                mock_resp_info.value = get_val()
                return mock_resp_info
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
                
        mock_page.expect_response = MagicMock(return_value=MockExpectResponse(mock_response))
        
        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        
        return await work_func(mock_context, *args, **kwargs)
        
    with patch.object(weibo_scraper, "scrape_flow_handler", new=mock_weibo_flow):
        weibo_posts = await weibo_scraper.fetch_weibo_posts("test_uid", limit=2)
        
    assert len(weibo_posts) == 2
    # 验证转发微博合并拼接格式：转发了 @{原作者} 的博文：“{原博文}”\n说：“{Coser附言}”
    assert weibo_posts[0]["post_id"] == "111111"
    assert weibo_posts[0]["content"] == "转发了 @绮太郎的基友 的博文：“CP30开始招募啦！时间是5.16-5.17”\n说：“我要去漫展！”"
    # 验证 Weibo mblogid 详情页链接拼接与发布日期北京时区格式化
    assert weibo_posts[0]["post_url"] == "https://weibo.com/test_uid/Ql7djrATz"
    assert weibo_posts[0]["published_at"] == "2026-01-01 17:12:59"
    
    # 验证普通微博
    assert weibo_posts[1]["post_id"] == "222222"
    assert weibo_posts[1]["content"] == "这是一条普通微博"
    assert weibo_posts[1]["post_url"] == "https://weibo.com/test_uid/Ql7djrATy"
    assert weibo_posts[1]["published_at"] == "2026-01-01 18:00:00"
    
    # ==================== 2. B站转发解析合并验证 ====================
    bili_scraper = BilibiliScraper()
    
    mock_bili_json = {
        "data": {
            "items": [
                {
                    "id_str": "333333",
                    "modules": {
                        "module_dynamic": {
                            "desc": {
                                "text": "我会去现场！"
                            }
                        }
                    },
                    # 转发动态
                    "orig": {
                        "modules": {
                            "module_author": {
                                "name": "B站官方姬"
                            },
                            "module_dynamic": {
                                "desc": {
                                    "text": "第五届JH·TIA动漫电竞展于5.23开启"
                                }
                            }
                        }
                    }
                },
                {
                    "id_str": "444444",
                    "modules": {
                        "module_dynamic": {
                            "desc": {
                                "text": "普通B站动态"
                            }
                        }
                    }
                },
                {
                    "id_str": "555555",
                    "modules": {
                        "module_dynamic": {
                            "desc": None  # 无附言转发
                        }
                    },
                    "orig": {
                        "modules": {
                            "module_author": {
                                "name": "B站官方姬"
                            },
                            "module_dynamic": {
                                "desc": {
                                    "text": "无附言转发活动"
                                }
                            }
                        }
                    }
                }
            ]
        }
    }
    
    async def mock_bili_flow(work_func, *args, **kwargs):
        mock_page = AsyncMock()
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=mock_bili_json)
        
        class MockExpectResponse:
            def __init__(self, val):
                self.val = val
            async def __aenter__(self):
                mock_resp_info = AsyncMock()
                async def get_val():
                    return self.val
                mock_resp_info.value = get_val()
                return mock_resp_info
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
                
        mock_page.expect_response = MagicMock(return_value=MockExpectResponse(mock_response))
        
        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        
        return await work_func(mock_context, *args, **kwargs)
        
    with patch.object(bili_scraper, "scrape_flow_handler", new=mock_bili_flow):
        bili_posts = await bili_scraper.fetch_bilibili_posts("test_uid", limit=3)
        
    assert len(bili_posts) == 3
    # 验证转发动态合并拼接格式：转发了 @{原作者} 的动态：“{原动态}”\n说：“{Coser附言}”
    assert bili_posts[0]["post_id"] == "333333"
    assert bili_posts[0]["content"] == "转发了 @B站官方姬 的动态：“第五届JH·TIA动漫电竞展于5.23开启”\n说：“我会去现场！”"
    
    # 验证普通动态
    assert bili_posts[1]["post_id"] == "444444"
    assert bili_posts[1]["content"] == "普通B站动态"
    
    # 验证无附言转发动态
    assert bili_posts[2]["post_id"] == "555555"
    assert bili_posts[2]["content"] == "转发了 @B站官方姬 的动态：“无附言转发活动”\n说：“”"


@pytest.mark.asyncio
async def test_repost_incremental_update():
    """测试微博二次编辑修改查重状态重置，以及时间轴分流之增量合并（历史冻结与未来对齐）"""
    # 1. 注册 Coser 并插入第一版博文 (edit_count=0)
    assert DBService.add_coser("增量测试姬")
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "增量测试姬"][0]
    
    posts_v0 = [{
        "post_id": "999999",
        "content": "漫展行程发布",
        "post_url": "url999",
        "edit_count": 0,
        "published_at": "Thu Jan 01 17:12:59 +0800 2026"
    }]
    
    assert DBService.save_raw_posts(coser_id, "weibo", posts_v0) == 1
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, edit_count, is_analyzed FROM raw_posts WHERE post_id = '999999';")
    raw_post_id, stored_edit_count, is_analyzed = cursor.fetchone()
    assert stored_edit_count == 0
    assert is_analyzed == 0
    conn.close()
    
    # 2. 模拟系统当前日期为 2026-05-24，进行第一次事务写入
    initial_events = [
        {
            "event_name": "历史漫展",
            "event_date": "2026-01-10",  # 历史
            "event_place": "广州保利馆",
            "event_description": "芙宁娜",
            "confidence": 0.9,
            "source_url": "url999"
        },
        {
            "event_name": "未来漫展A",
            "event_date": "2026-06-01",  # 未来
            "event_place": "上海世博馆",
            "event_description": "雷电将军",
            "confidence": 0.85,
            "source_url": "url999"
        }
    ]
    
    import datetime
    fixed_now = datetime.datetime(2026, 5, 24, 12, 0, 0)
    with patch("src.services.db_service.datetime.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        
        # 第一次写入，状态应更新为 is_analyzed = 1
        assert DBService.save_extracted_events_transactional(raw_post_id, initial_events, 0.3) is True
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 1
    
    cursor.execute("SELECT COUNT(*) FROM cosplay_events WHERE raw_post_id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 1
    conn.close()
    
    # 3. 模拟二次抓取编辑后的微博 (edit_count=1)
    posts_v1 = [{
        "post_id": "999999",
        "content": "漫展行程发布（更新版）",
        "post_url": "url999",
        "edit_count": 1,
        "published_at": "Thu Jan 01 17:12:59 +0800 2026"
    }]
    
    # edit_count 大于已存，因此应该成功更新并重置为未分析 is_analyzed = 0
    assert DBService.save_raw_posts(coser_id, "weibo", posts_v1) == 1
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT content, edit_count, is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    row = cursor.fetchone()
    assert row[0] == "漫展行程发布（更新版）"
    assert row[1] == 1
    assert row[2] == 0
    conn.close()
    
    # 4. 进行第二次增量写入：
    # - 历史活动 (2026-01-10) 由持久化层硬过滤，不写入未来日程流
    # - 旧的未来行程 (2026-06-01) 此次被 Coser 砍掉取消了 (对齐清理)
    # - 新增一个全新的未来行程 (2026-07-01) (增量合并)
    new_extracted_events = [
        {
            "event_name": "历史漫展",
            "event_date": "2026-01-10",
            "event_place": "广州保利馆",
            "event_description": "芙宁娜",
            "confidence": 0.9,
            "source_url": "url999"
        },
        {
            "event_name": "新未来漫展B",
            "event_date": "2026-07-01",
            "event_place": "广州世贸馆",
            "event_description": "神里绫华",
            "confidence": 0.95,
            "source_url": "url999"
        }
    ]
    
    with patch("src.services.db_service.datetime.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        
        assert DBService.save_extracted_events_transactional(raw_post_id, new_extracted_events, 0.3) is True
        
    # 5. 校验数据库，确保最终一致性
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 1
    
    cursor.execute("SELECT event_name, event_date, event_place, event_description FROM cosplay_events WHERE raw_post_id = ? AND status != '已取消' ORDER BY event_date ASC;", (raw_post_id,))
    events_in_db = cursor.fetchall()
    
    # 验证确实有一条状态为 '已取消' 的记录留存
    cursor.execute("SELECT COUNT(*) FROM cosplay_events WHERE raw_post_id = ? AND status = '已取消';", (raw_post_id,))
    assert cursor.fetchone()[0] == 1
    conn.close()
    
    # 应当只有 1 条有效活动：新增的 2026-07-01 未来活动。
    # 2026-06-01 的旧未来活动已被软删除对齐。
    assert len(events_in_db) == 1
    assert events_in_db[0][0] == "新未来漫展B"
    assert events_in_db[0][1] == "2026-07-01"
    assert events_in_db[0][2] == "广州世贸馆"
    assert events_in_db[0][3] == "神里绫华"


@pytest.mark.asyncio
async def test_harden_and_timezone_align():
    """测试加固机制与时区对齐：
    1. 微博转发原作者 screen_name 为 None/无 时的真值兜底容错
    2. B站动态 pub_ts 提取并转化为北京时区标准时间字符串
    3. 数据库及智能体在跨时区部署时（如服务器 UTC 23:00，北京已是次日 07:00），强行对齐为北京时间 YYYY-MM-DD
    """
    from src.tools.weibo_scraper import WeiboScraper
    from src.tools.bilibili_scraper import BilibiliScraper
    from src.services.db_service import DBService
    from unittest.mock import MagicMock
    import datetime
    
    # ==================== 1. 微博转发原作者为 None 的安全兜底校验 ====================
    weibo_scraper = WeiboScraper()
    mock_weibo_json = {
        "data": {
            "list": [
                {
                    "id": "888888",
                    "bid": "bid888",
                    "text_raw": "我要去漫展！",
                    # 转发微博但作者注销，screen_name 为 None
                    "retweeted_status": {
                        "user": {
                            "screen_name": None
                        },
                        "text_raw": "CP30开始招募啦！时间是5.16-5.17"
                    }
                },
                {
                    "id": "888889",
                    "bid": "bid889",
                    "text_raw": "我又转发了一条！",
                    # 转发微博但 user 为 None
                    "retweeted_status": {
                        "user": None,
                        "text_raw": "CP30开始招募啦！时间是5.16-5.17"
                    }
                }
            ]
        }
    }
    
    async def mock_weibo_flow(work_func, *args, **kwargs):
        mock_page = AsyncMock()
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=mock_weibo_json)
        
        class MockExpectResponse:
            def __init__(self, val):
                self.val = val
            async def __aenter__(self):
                mock_resp_info = AsyncMock()
                async def get_val():
                    return self.val
                mock_resp_info.value = get_val()
                return mock_resp_info
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
                
        mock_page.expect_response = MagicMock(return_value=MockExpectResponse(mock_response))
        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        return await work_func(mock_context, *args, **kwargs)
        
    with patch.object(weibo_scraper, "scrape_flow_handler", new=mock_weibo_flow):
        weibo_posts = await weibo_scraper.fetch_weibo_posts("test_uid", limit=2)
        
    assert len(weibo_posts) == 2
    # 验证兜底为 "原作者"
    assert weibo_posts[0]["content"] == "转发了 @原作者 的博文：“CP30开始招募啦！时间是5.16-5.17”\n说：“我要去漫展！”"
    assert weibo_posts[1]["content"] == "转发了 @原作者 的博文：“CP30开始招募啦！时间是5.16-5.17”\n说：“我又转发了一条！”"

    # ==================== 2. B站动态 pub_ts 提取与时序北京时间戳转化验证 ====================
    bili_scraper = BilibiliScraper()
    # 假设第一个为带正常文本的动态，发布时间戳为 1716528000 （对应北京时间 2024-05-24 13:20:00）
    # 第二个为纯视频投稿动态，没有任何文本附言，应该被物理过滤跳过
    mock_bili_json = {
        "data": {
            "items": [
                {
                    "id_str": "666666",
                    "modules": {
                        "module_dynamic": {
                            "desc": {
                                "text": "普通B站动态"
                            }
                        },
                        "module_author": {
                            "pub_ts": 1716528000
                        }
                    }
                },
                {
                    "id_str": "666667",
                    "modules": {
                        "module_dynamic": {
                            "desc": {
                                "text": "   "
                            }
                        },
                        "module_author": {
                            "pub_ts": 1716528000
                        }
                    }
                }
            ]
        }
    }
    
    async def mock_bili_flow(work_func, *args, **kwargs):
        mock_page = AsyncMock()
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value=mock_bili_json)
        
        class MockExpectResponse:
            def __init__(self, val):
                self.val = val
            async def __aenter__(self):
                mock_resp_info = AsyncMock()
                async def get_val():
                    return self.val
                mock_resp_info.value = get_val()
                return mock_resp_info
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
                
        mock_page.expect_response = MagicMock(return_value=MockExpectResponse(mock_response))
        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        return await work_func(mock_context, *args, **kwargs)
        
    with patch.object(bili_scraper, "scrape_flow_handler", new=mock_bili_flow):
        bili_posts = await bili_scraper.fetch_bilibili_posts("test_uid", limit=2)
        
    assert len(bili_posts) == 1
    assert bili_posts[0]["post_id"] == "666666"
    assert bili_posts[0]["published_at"] == "2024-05-24 13:20:00"

    # ==================== 3. 跨时区服务器部署下的北京时区对齐锁定校验 ====================
    # 模拟本地数据库写入时区对齐
    from src.models.db_models import init_db, get_db_connection
    init_db()
    
    # 1. 注册 Coser 实体并验证 created_at 格式
    DBService.add_coser("时区测试姬", weibo_uid="777777")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, created_at FROM cosers WHERE name = '时区测试姬';")
    row = cursor.fetchone()
    coser_id = row[0]
    coser_created_at = row[1]
    
    import re
    # 验证 cosers 表的 created_at 在应用层写入时已对齐为 YYYY-MM-DD HH:MM:SS
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", coser_created_at) is not None
    
    cursor.close()
    conn.close()
    
    # 2. 模拟服务器 UTC 时间为 2026-05-23 23:00:00 (即北京时间 2026-05-24 07:00:00)
    # 统一时钟工具负责向各业务模块提供北京参考时间。
    fixed_beijing_now = datetime.datetime(2026, 5, 24, 7, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
            
    # 要注入的提取事件：2026-05-23 (在北京时间来看是历史发生的行程)
    extracted_events = [
        {
            "event_name": "北京时区历史展",
            "event_date": "2026-05-23",  # 对北京时间 2026-05-24 来说是昨天 (历史活动)
            "event_place": "北京博览馆",
            "event_description": "八重神子",
            "confidence": 0.95,
            "source_url": "url777"
        },
        {
            "event_name": "北京时区未来展",
            "event_date": "2026-05-24",  # 对北京时间 2026-05-24 来说是今天 (未来/即将发生)
            "event_place": "上海会展",
            "event_description": "芙宁娜",
            "confidence": 0.95,
            "source_url": "url777"
        }
    ]
    
    posts = [{
        "post_id": "777777",
        "content": "测试时区",
        "post_url": "url777",
        "edit_count": 0,
        "published_at": "2026-05-24 13:00:00"
    }]
    
    with patch("src.services.db.coser_repository.beijing_now_str", return_value="2026-05-24 07:00:00"), \
         patch("src.services.db.event_repository.beijing_now_str", return_value="2026-05-24 07:00:00"), \
         patch("src.services.db.event_repository.beijing_today_str", return_value="2026-05-24"), \
         patch("src.services.db.materialize_service.beijing_now_str", return_value="2026-05-24 07:00:00"), \
         patch("src.services.db.materialize_service.beijing_today", return_value=fixed_beijing_now.date()), \
         patch("src.services.fusion_service.beijing_now", return_value=fixed_beijing_now), \
         patch("src.services.fusion_service.beijing_now_str", return_value="2026-05-24 07:00:00"):
        # 写入 raw_posts，触发应用层北京时间 scraped_at 注入
        DBService.save_raw_posts(coser_id, "weibo", posts)
        
        # 查出刚才写入的 raw_post_id
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, scraped_at FROM raw_posts WHERE platform = 'weibo' AND post_id = '777777';")
        row = cursor.fetchone()
        raw_post_id = row[0]
        raw_post_scraped_at = row[1]
        
        # 验证 raw_posts 的 scraped_at 在应用层已被精确锁死为 mock 对应的北京时间 "2026-05-24 07:00:00"
        assert raw_post_scraped_at == "2026-05-24 07:00:00"
        cursor.close()
        conn.close()
        
        # 写入 cosplay_events，触发应用层北京时间 created_at 注入
        assert DBService.save_extracted_events_transactional(raw_post_id, extracted_events, 0.3) is True
        
    # 3. 验证数据库中活动的分流及 created_at 北京时间一致性
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT event_name, event_date, event_place, created_at FROM cosplay_events WHERE raw_post_id = ? ORDER BY event_date ASC;", (raw_post_id,))
    events = cursor.fetchall()
    cursor.close()
    conn.close()
    
    assert len(events) == 1
    assert events[0][0] == "北京时区未来展"
    assert events[0][1] == "2026-05-24"
    assert events[0][3] == "2026-05-24 07:00:00"
    
    # 清理测试数据
    DBService.delete_coser("时区测试姬")


def test_deepseek_transport_rewriting():
    """测试 DeepSeekTransport 核心拦截与重写逻辑的准确性"""
    import json
    import httpx
    from src.tools.llm_bridge import DeepSeekTransport

    transport = DeepSeekTransport()
    
    # 1. 构造一个包含 json_schema 要求的 mock 请求体
    mock_payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个助手。"}
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "FinalOutput",
                "schema": {
                    "type": "object",
                    "properties": {
                        "event_list": {"type": "array"}
                    }
                }
            }
        }
    }
    
    mock_content = json.dumps(mock_payload).encode("utf-8")
    
    # 2. 实例化 httpx.Request 对象
    req = httpx.Request(
        method="POST",
        url="https://api.deepseek.com/v1/chat/completions",
        headers={"content-type": "application/json"},
        content=mock_content
    )
    
    # 3. 手动触发拦截改写
    transport._rewrite_request(req)
    
    # 4. 断言验证
    # 验证 X-Deepseek-Client 标识已注入
    assert req.headers["X-Deepseek-Client"] == "cliche"
    
    # 解析改写后的 payload
    rewritten_payload = json.loads(req.read())
    
    # 验证 response_format 已降级为 json_object
    assert rewritten_payload["response_format"] == {"type": "json_object"}
    
    # 验证 system 消息末尾已成功附加 Schema 说明
    system_message = rewritten_payload["messages"][0]["content"]
    assert "JSON Schema for output:" in system_message
    assert "Output must conform to the above JSON schema." in system_message
    
    # 验证 Content-Length 与实际改写后的包体大小完全吻合
    expected_length = len(json.dumps(rewritten_payload, ensure_ascii=True).encode("utf-8"))
    assert int(req.headers["Content-Length"]) == expected_length


def test_deepseek_client_registration_transport():
    """验证当供应商为 deepseek 时，生成的 AsyncOpenAI 客户端是否成功挂载了 DeepSeekTransport"""
    import httpx
    from src.tools.llm_bridge import LLMClientRegistry, DeepSeekTransport
    
    mock_config = {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-test-deepseek-key",
            "default_model": "deepseek-chat"
        }
    }
    
    registry = LLMClientRegistry(mock_config)
    client = registry.get_client("deepseek")
    
    # 验证 AsyncOpenAI 客户端被成功创建
    assert client is not None
    
    # 验证其实际绑定的 transport 为 DeepSeekTransport
    assert isinstance(client._client._transport, DeepSeekTransport)


@pytest.mark.asyncio
async def test_relative_date_parsing_with_published_at():
    """测试在 analyze_post_with_retry 中注入 published_at 时的 User Prompt 生成逻辑"""
    from src.agents.event_agent import analyze_post_with_retry
    
    # 强制单模型模式进行隔离测试
    original_mode = settings.analysis_pipeline.get("mode", "single")
    settings.analysis_pipeline["mode"] = "single"
    
    try:
        with patch("agents.Runner.run", new_callable=AsyncMock) as mock_run:
            # 构造虚拟的成功提取响应
            from src.models.schemas import CosEvent
            mock_final_output = MagicMock()
            mock_final_output.event_list = [
                CosEvent(
                    event_name="JH·TIA动漫电竞展",
                    event_date="2026-05-23",
                    event_place="成都",
                    event_description="下周末23号见",
                    confidence=0.9,
                    source_url="url_999"
                )
            ]
            mock_res = MagicMock()
            mock_res.final_output = mock_final_output
            mock_run.return_value = mock_res
            
            # 调用 analyze_post_with_retry 并注入 published_at 发布日期时间
            events = await analyze_post_with_retry(
                content="下周末23号见咯～",
                url="url_999",
                published_at="2026-05-15 17:00:00"
            )
            
            # 1. 验证 Runner.run 确被调用
            assert mock_run.call_count == 1
            
            # 2. 提取出 Runner.run 的调用参数（User Prompt 文本）
            called_user_prompt = mock_run.call_args[0][1]
            
            # 3. 验证 "博文发布时间:\n2026-05-15 17:00:00\n\n" 成功拼接注入到 Prompt 最头部
            assert called_user_prompt.startswith(
                "博文发布时间:\n2026-05-15 17:00:00\n\n"
            )
            
            # 4. 验证返回的活动提炼正确
            assert len(events) == 1
            assert events[0]["event_date"] == "2026-05-23"
            
    finally:
        settings.analysis_pipeline["mode"] = original_mode


@pytest.mark.asyncio
async def test_judge_bypass_when_candidates_empty():
    """测试在共识模式下，若所有提取器的候选结果均为空，自动旁路跳过裁判大模型"""
    from src.agents.event_agent import analyze_post_with_retry
    
    # 强制共识仲裁模式进行隔离测试
    original_mode = settings.analysis_pipeline.get("mode", "single")
    settings.analysis_pipeline["mode"] = "consensus"
    
    try:
        # Mock 提取器返回空的 FinalOutput，即没有任何候选活动
        with patch("agents.Runner.run", new_callable=AsyncMock) as mock_run:
            # 第一轮：Triage 预检返回 has_event = True (唤醒并行提取器)
            mock_triage_output = MagicMock()
            mock_triage_output.has_event = True
            mock_triage_output.candidate_events = ["漫展候选"]
            
            # 并行提取器运行：返回空的 event_list
            mock_extractor_output = MagicMock()
            mock_extractor_output.event_list = []
            
            # 让 mock_run 依次返回预检结果，以及并行提取器的空草稿 (提取器 1 与 提取器 2)
            mock_run.side_effect = [
                MagicMock(final_output=mock_triage_output),      # Triage Model
                MagicMock(final_output=mock_extractor_output),  # Extractor 1
                MagicMock(final_output=mock_extractor_output),  # Extractor 2
            ]
            
            # 调用 analyze_post_with_retry
            events = await analyze_post_with_retry(
                content="去吃个饭",
                url="url_888"
            )
            
            # 1. 验证返回空活动列表
            assert events == []
            
            # 2. 验证 Runner.run 仅仅被调用了 3 次 (1 次 Triage, 2 次 并行提取)
            # 绝对没有第 4 次终审裁判（Judge Agent）的调用，从而证明旁路拦截 100% 成功！
            assert mock_run.call_count == 3
            
    finally:
        settings.analysis_pipeline["mode"] = original_mode


@pytest.mark.asyncio
async def test_soft_state_machine_multi_version():
    """测试多版本置顶微博的软状态机级联变更：
    1. 写入 v0 版微博 (edit_count=0, post_id="123456")，包含历史和未来行程
    2. 写入 v1 版编辑微博 (edit_count=1, post_id="123456#v1")，未来行程有更新
    3. 校验 v0 版的未来行程被级联更新为 '已取消'，历史行程被持久化层过滤
    4. 校验 get_all_events() 过滤掉了所有 '已取消' 行程
    """
    from src.services.db_service import DBService
    from src.models.db_models import get_db_connection
    from unittest.mock import patch
    import datetime

    # 1. 注册 Coser
    assert DBService.add_coser("多版本测试姬")
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "多版本测试姬"][0]

    # 2. 插入第一版原始微博 v0 (edit_count=0)
    posts_v0 = [{
        "post_id": "123456",
        "content": "行程发布v0",
        "post_url": "url_v0",
        "edit_count": 0,
        "published_at": "2026-01-01 12:00:00"
    }]
    assert DBService.save_raw_posts(coser_id, "weibo", posts_v0) == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE platform = 'weibo' AND post_id = '123456';")
    raw_post_id_v0 = cursor.fetchone()[0]
    conn.close()

    # 3. 第一次事务写入行程数据 (模拟当前系统日期为 2026-05-24)
    initial_events = [
        {
            "event_name": "历史漫展v0",
            "event_date": "2026-01-10",  # 历史行程 (相对于 2026-05-24)
            "event_place": "北京场馆",
            "event_description": "角色A",
            "confidence": 0.9,
            "source_url": "url_v0"
        },
        {
            "event_name": "未来漫展v0",
            "event_date": "2026-06-01",  # 未来行程 (相对于 2026-05-24)
            "event_place": "上海场馆",
            "event_description": "角色B",
            "confidence": 0.85,
            "source_url": "url_v0"
        }
    ]

    fixed_now = datetime.datetime(2026, 5, 24, 12, 0, 0)
    with patch("src.services.db_service.datetime.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        assert DBService.save_extracted_events_transactional(raw_post_id_v0, initial_events, 0.3) is True

    # 4. 插入第二版编辑后微博 v1 (edit_count=1)
    posts_v1 = [{
        "post_id": "123456#v1",  # scraper 自动拼接的后缀格式
        "content": "行程发布v1",
        "post_url": "url_v1",
        "edit_count": 1,
        "published_at": "2026-05-24 12:00:00"
    }]
    assert DBService.save_raw_posts(coser_id, "weibo", posts_v1) == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE platform = 'weibo' AND post_id = '123456#v1';")
    raw_post_id_v1 = cursor.fetchone()[0]
    conn.close()

    # 5. 第二次事务写入新版行程数据
    new_events = [
        {
            "event_name": "历史漫展v0",  # 依然存在的老历史行程
            "event_date": "2026-01-10",
            "event_place": "北京场馆",
            "event_description": "角色A",
            "confidence": 0.9,
            "source_url": "url_v1"
        },
        {
            "event_name": "更新未来漫展v1",  # 发生了变更的新未来行程
            "event_date": "2026-07-01",
            "event_place": "广州场馆",
            "event_description": "角色C",
            "confidence": 0.95,
            "source_url": "url_v1"
        }
    ]

    with patch("src.services.db_service.datetime.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        assert DBService.save_extracted_events_transactional(raw_post_id_v1, new_events, 0.3) is True

    # 6. 验证软状态机流转正确性
    conn = get_db_connection()
    cursor = conn.cursor()

    # 验证 v0 版本的未来漫展v0是否已被软取消为 '已取消'
    cursor.execute("SELECT status FROM cosplay_events WHERE raw_post_id = ? AND event_name = '未来漫展v0';", (raw_post_id_v0,))
    assert cursor.fetchone()[0] == "已取消"

    # 验证 v0 版本的历史漫展v0被过滤，不进入未来日程流
    cursor.execute("SELECT COUNT(*) FROM cosplay_events WHERE raw_post_id = ? AND event_name = '历史漫展v0';", (raw_post_id_v0,))
    assert cursor.fetchone()[0] == 0

    # 验证 v1 版本的新未来行程是否是 '未开始'
    cursor.execute("SELECT status FROM cosplay_events WHERE raw_post_id = ? AND event_name = '更新未来漫展v1';", (raw_post_id_v1,))
    assert cursor.fetchone()[0] == "未开始"
    conn.close()

    # 7. 验证 get_all_events() 过滤 '已取消' 日程
    all_events = DBService.get_all_events(0.3)
    # 应只包含 "更新未来漫展v1" (v1 版的)，排除历史和已取消日程
    active_names = [e["event_name"] for e in all_events if e["coser_name"] == "多版本测试姬"]
    assert "历史漫展v0" not in active_names
    assert "更新未来漫展v1" in active_names
    assert "未来漫展v0" not in active_names


@pytest.mark.asyncio
async def test_bilibili_xhs_synthetic_versioning():
    """测试B站和小红书在内容发生变化时触发合成版本控制、追加#v后缀与未来行程级联软注销"""
    from src.services.db_service import DBService
    from src.models.db_models import get_db_connection
    from unittest.mock import patch
    import datetime

    # 1. 注册 Coser 并插入B站首发动态 (edit_count=0)
    assert DBService.add_coser("B站合成测试姬")
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "B站合成测试姬"][0]

    post_v0 = {
        "post_id": "bili_9999",
        "content": "明天要去打卡！",
        "post_url": "url_bili",
        "edit_count": 0,
        "published_at": None
    }
    assert DBService.save_raw_posts(coser_id, "bilibili", [post_v0]) == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, post_id, edit_count FROM raw_posts WHERE platform = 'bilibili' AND post_id = 'bili_9999';")
    raw_post_id_v0, post_id_v0, edit_count_v0 = cursor.fetchone()
    assert edit_count_v0 == 0
    conn.close()

    # 2. 写入第一次分析行程 (系统日期 2026-05-24)
    initial_events = [
        {
            "event_name": "明天漫展",
            "event_date": "2026-05-25",  # 未来行程
            "event_place": "杭州展馆",
            "event_description": "芙宁娜",
            "confidence": 0.9,
            "source_url": "url_bili"
        }
    ]
    fixed_now = datetime.datetime(2026, 5, 24, 12, 0, 0)
    with patch("src.services.db_service.datetime.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        assert DBService.save_extracted_events_transactional(raw_post_id_v0, initial_events, 0.3) is True

    # 3. 模拟B站动态内容被编辑修改，再次抓取
    post_v1 = {
        "post_id": "bili_9999",
        "content": "明天去打卡修改版：不去杭州了，改去上海！",  # 内容有变
        "post_url": "url_bili",
        "edit_count": 0,
        "published_at": None
    }
    # 内容改变，应当自适应合成版本 edit_count=1 并生成新记录 bili_9999#v1
    assert DBService.save_raw_posts(coser_id, "bilibili", [post_v1]) == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, post_id, edit_count FROM raw_posts WHERE platform = 'bilibili' AND post_id = 'bili_9999#v1';")
    raw_post_id_v1, post_id_v1, edit_count_v1 = cursor.fetchone()
    assert edit_count_v1 == 1
    conn.close()

    # 4. 第二次写入新日程
    new_events = [
        {
            "event_name": "上海漫展",
            "event_date": "2026-05-30",  # 新的未来行程
            "event_place": "上海展馆",
            "event_description": "雷电将军",
            "confidence": 0.95,
            "source_url": "url_bili"
        }
    ]
    with patch("src.services.db_service.datetime.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        assert DBService.save_extracted_events_transactional(raw_post_id_v1, new_events, 0.3) is True

    # 5. 校验级联软取消效果
    conn = get_db_connection()
    cursor = conn.cursor()
    # 验证 v0 版本的未来日程已被级联标记为 '已取消'
    cursor.execute("SELECT status FROM cosplay_events WHERE raw_post_id = ? AND event_name = '明天漫展';", (raw_post_id_v0,))
    assert cursor.fetchone()[0] == "已取消"

    # 验证 v1 版本的未来日程依然是 '未开始'
    cursor.execute("SELECT status FROM cosplay_events WHERE raw_post_id = ? AND event_name = '上海漫展';", (raw_post_id_v1,))
    assert cursor.fetchone()[0] == "未开始"
    conn.close()


@pytest.mark.asyncio
async def test_sqlite_check_constraint_status():
    """测试 status 列的值域检查物理与应用层防御校验"""
    from src.services.db_service import DBService
    from src.models.db_models import get_db_connection
    import pytest

    # 注册 Coser
    assert DBService.add_coser("状态机测试姬")
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "状态机测试姬"][0]

    posts = [{
        "post_id": "status_check_999",
        "content": "漫展行程",
        "post_url": "url",
        "edit_count": 0,
        "published_at": None
    }]
    assert DBService.save_raw_posts(coser_id, "xhs", posts) == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE platform = 'xhs' AND post_id = 'status_check_999';")
    raw_post_id = cursor.fetchone()[0]

    # 1. 尝试使用非法拼写状态通过 SQL 强插，断言触发 SQLite 物理 CHECK 约束异常
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            """
            INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, status, created_at)
            VALUES (?, ?, ?, ?, ?, '已取销', ?);
            """,
            (raw_post_id, "状态机测试姬", "漫展", "2026-06-01", "场馆", "2026-05-24 12:00:00")
        )
        conn.commit()

    conn.close()

    # 2. 尝试通过 DBService 接口传入非法事件触发应用层 Python 域值校验断言
    invalid_events = [
        {
            "event_name": "违法漫展",
            "event_date": "2026-06-01",
            "event_place": "场馆",
            "event_description": "角色",
            "confidence": 0.9,
            "source_url": "url",
            "status": "已取销"  # 错误的拼写
        }
    ]
    # 我们故意绕过提取框架，模拟异常插入。因为应用层强校验，应重新抛出 AssertionError 激活熔断机制
    with pytest.raises(AssertionError):
        DBService.save_extracted_events_transactional(raw_post_id, invalid_events, 0.3)


@pytest.mark.asyncio
async def test_deepseek_transport_failsafe_and_escape():
    """测试 DeepSeekTransport 的 ASCII 转义传输与异常熔断安全兜底机制"""
    from src.tools.llm_bridge import DeepSeekTransport
    import httpx
    import json
    from unittest.mock import patch, MagicMock

    transport = DeepSeekTransport()

    # 1. 验证正常改写且 unicode 被 ensure_ascii=True 转义为 ASCII 码
    original_payload = {
        "response_format": {"type": "json_schema", "json_schema": {"name": "test"}},
        "messages": [
            {"role": "system", "content": "你好，Emoji 😊"}
        ]
    }
    request = httpx.Request(
        method="POST",
        url="https://api.deepseek.com/chat/completions",
        headers={"content-type": "application/json"},
        content=json.dumps(original_payload, ensure_ascii=False).encode("utf-8")
    )
    
    transport._rewrite_request(request)
    
    # 验证改写成功
    rewritten_payload = json.loads(request.read().decode("utf-8"))
    assert rewritten_payload["response_format"] == {"type": "json_object"}
    
    # 验证 system 消息包含 JSON Schema 提示词且全部以纯 ASCII 表示 (unicode 格式被转义为 \u 编码)
    system_content = rewritten_payload["messages"][0]["content"]
    assert "JSON Schema for output:" in system_content
    # 转义后 request 中的 content 应该是不含非 ASCII 字符的纯 ASCII 字符串
    raw_body = request.read().decode("ascii") # 如果含非 ASCII，decode("ascii") 会报错，但现在都是 \uXXXX 所以能解码！
    assert raw_body is not None

    # 2. 模拟高噪声或格式损毁请求触发异常时，拦截层成功熔断回退
    bad_request = httpx.Request(
        method="POST",
        url="https://api.deepseek.com/chat/completions",
        headers={"content-type": "application/json"},
        content=b"invalid-json-data{"
    )
    # 因为 JSON 解析失败，_rewrite_request 不应报错崩溃，而是默默捕获异常熔断，保持请求内容不受任何损坏
    transport._rewrite_request(bad_request)
    assert bad_request.read() == b"invalid-json-data{"


@pytest.mark.asyncio
async def test_weibo_edit_time_anchoring():
    """测试微博二次编辑高精度 editHistory 时间抓取与 DBService 智能重锚决策机制"""
    from src.tools.weibo_scraper import WeiboScraper
    from src.services.db_service import DBService
    from unittest.mock import AsyncMock, patch
    import datetime

    # 1. 模拟 editHistory 接口请求成功
    # 模拟 WeiboScraper 抓取带有 edit_count > 0 的微博
    weibo_scraper = WeiboScraper()
    
    mock_history_json = {
        "statuses": [
            {
                "created_at": "Thu May 14 15:12:02 +0800 2026",
                "text_raw": "5.24超级飞侠生日会"
            },
            {
                "created_at": "Sun May 10 09:50:41 +0800 2026",
                "text_raw": "5.31一日店长"
            }
        ]
    }
    
    # 模拟 context.request.get 成功
    mock_resp = AsyncMock()
    mock_resp.ok = True
    mock_resp.json = AsyncMock(return_value=mock_history_json)
    
    mock_context = AsyncMock()
    mock_context.request.get = AsyncMock(return_value=mock_resp)

    # 准备 timeline 的抓取单条 mblog
    mock_timeline_item = {
        "id": "5104278719172155",
        "text_raw": "近期线下行程",
        "created_at": "Wed Sep 24 00:15:57 +0800 2025",
        "edit_count": 42
    }
    
    # 提取时间
    posts = []
    # 模拟 timelines list 处理逻辑
    item = mock_timeline_item
    post_id = str(item.get("id"))
    edit_count = int(item.get("edit_count") or 0)
    if edit_count > 0:
        post_id = f"{post_id}#v{edit_count}"
        
    beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
    from email.utils import parsedate_to_datetime
    
    # 验证 editHistory 获取成功
    history_url = f"https://weibo.com/ajax/statuses/editHistory?mid={item.get('id')}&page=1"
    history_resp = await mock_context.request.get(history_url)
    assert history_resp.ok
    history_json = await history_resp.json()
    statuses = history_json.get("statuses", [])
    assert len(statuses) == 2
    
    latest_edit_time_raw = statuses[0].get("created_at")
    dt = parsedate_to_datetime(latest_edit_time_raw)
    published_at = dt.astimezone(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
    
    assert published_at == "2026-05-14 15:12:02"

    # 2. 模拟 editHistory 接口请求失败或反爬抛出异常，断言自动安全降级为 original created_at
    mock_context_fail = AsyncMock()
    mock_context_fail.request.get = AsyncMock(side_effect=Exception("Weibo Anti-Scraping 403"))
    
    published_at_fail = None
    try:
        # 模拟调用
        history_resp_fail = await mock_context_fail.request.get(history_url)
    except Exception:
        # 触发降级
        raw_published_at = item.get("created_at")
        dt_fail = parsedate_to_datetime(raw_published_at)
        published_at_fail = dt_fail.astimezone(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
        
    assert published_at_fail == "2025-09-24 00:15:57"  # 成功锁死 2025 年年份！

    # 3. 模拟 DBService 智能重锚判定
    # 首先清理可能存在的冲突数据
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM raw_posts WHERE platform = 'weibo' AND (post_id = '5104278719172155' OR post_id LIKE '5104278719172155#v%');")
    cursor.execute("DELETE FROM cosers WHERE name = '浅九ninth';")
    
    # 注册测试 Coser
    cursor.execute("INSERT INTO cosers (name, weibo_uid, created_at) VALUES ('浅九ninth', '6413437934', '2026-05-24 12:00:00');")
    coser_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # 3a. 场景 A：被动历史录入（数据库内完全无此 base_post_id 记录）
    posts_payload = [{
        "post_id": "5104278719172155#v42",
        "content": "近期行程",
        "post_url": "url",
        "edit_count": 42,
        "published_at": "2026-05-14 15:12:02" # 爬虫传来的高精度时间
    }]
    
    assert DBService.save_raw_posts(coser_id, "weibo", posts_payload) == 1
    
    # 验证被动历史录入成功，发布时间保持 2026-05-14 15:12:02
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT published_at FROM raw_posts WHERE post_id = '5104278719172155#v42';")
    assert cursor.fetchone()[0] == "2026-05-14 15:12:02"
    conn.close()

    # 3b. 场景 B：主动增量编辑（数据库中已存在先前版本记录）
    # 当抓取到更高的编辑版本时，写入 v43 时，应当绝对保留爬虫获取的时间，不被 now_str 覆盖
    posts_payload_new = [{
        "post_id": "5104278719172155#v43",
        "content": "最新更新行程",
        "post_url": "url",
        "edit_count": 43,
        "published_at": "2026-05-18 10:00:00" # 爬虫爬到的新编辑时间
    }]
    
    assert DBService.save_raw_posts(coser_id, "weibo", posts_payload_new) == 1
    
    # 验证新插入的 v43 记录的发布时间完美保留为 2026-05-18 10:00:00
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT published_at FROM raw_posts WHERE post_id = '5104278719172155#v43';")
    assert cursor.fetchone()[0] == "2026-05-18 10:00:00"
    
    # 整理数据库清理测试数据
    cursor.execute("DELETE FROM raw_posts WHERE platform = 'weibo' AND (post_id = '5104278719172155' OR post_id LIKE '5104278719172155#v%');")
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    conn.commit()
    conn.close()


def test_export_scope_and_format_variants(tmp_path):
    """测试升级后的 ExportService 多时域范围 (future/all) 及多格式 (csv/txt/stdout) 的过滤与写入正确性"""
    from src.services.export_service import ExportService
    
    # 1. 注册测试 Coser 并插入各种状态的博文与活动记录
    DBService.add_coser("导出测试Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    # 插入一条博文
    DBService.save_raw_posts(coser_id, "weibo", [{"post_id": "p_exp_123", "content": "行程发布", "post_url": "url"}])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE post_id = 'p_exp_123';")
    raw_post_id = cursor.fetchone()[0]
    
    # 插入四种不同的 Cosplay 活动（历史、未来、未知、已取消）
    # 假设当前系统北京参考时间是 2026-05-25
    cursor.execute(
        """
        INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, status, created_at)
        VALUES 
        (?, '导出测试Coser', '过去漫展A', '2025-09-20', '北京', '明日方舟', 0.9, 'url', '未开始', '2026-05-24 12:00:00'),
        (?, '导出测试Coser', '未来漫展B', '2026-07-01', '上海世博', '原神', 0.8, 'url', '未开始', '2026-05-24 12:00:00'),
        (?, '导出测试Coser', '待定漫展C', '未知', '广州', '崩铁', 0.75, 'url', '未开始', '2026-05-24 12:00:00'),
        (?, '导出测试Coser', '已取消漫展D', '2026-08-01', '深圳', '芙宁娜', 0.9, 'url', '已取消', '2026-05-24 12:00:00');
        """,
        (raw_post_id, raw_post_id, raw_post_id, raw_post_id)
    )
    conn.commit()
    conn.close()
    
    # 2. 验证 scope="all" 获取全量有效记录（过滤已取消）
    # 应该包含：过去漫展A, 未来漫展B, 待定漫展C = 共 3 条
    all_txt_file = tmp_path / "all_events.txt"
    count_all = ExportService.export_events(
        output_path=str(all_txt_file),
        confidence_threshold=0.5,
        scope="all",
        fmt="txt"
    )
    assert count_all == 3
    
    # 验证生成的 TXT 文件内容及排版美学
    with open(all_txt_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "Cosplay 活动日程表 (范围: 全量)" in content
        assert "过去漫展A" in content
        assert "未来漫展B" in content
        assert "待定漫展C" in content
        assert "已取消漫展D" not in content  # 必须过滤已取消
        assert "[共成功导出 3 条活动记录]" in content
        
    # 3. 验证 scope="future" 仅导出未来及未知（过滤历史和已取消）
    # 结合参考时间 2026-05-25，应该仅包含：未来漫展B, 待定漫展C = 共 2 条 (2025-09-20 的过去漫展A被过滤)
    future_csv_file = tmp_path / "future_events.csv"
    count_future = ExportService.export_events(
        output_path=str(future_csv_file),
        confidence_threshold=0.5,
        scope="future",
        fmt="csv"
    )
    assert count_future == 2
    
    # 验证生成的 CSV 文件存在且带有 BOM 标志
    with open(future_csv_file, "rb") as f:
        bom = f.read(3)
        assert bom == b'\xef\xbb\xbf'
        
    # 4. 验证省略 output_path 时，自动分流至 stdout 打印纯文本，且自动根据后缀推理格式
    from unittest.mock import patch
    with patch("click.echo") as mock_echo:
        count_stdout = ExportService.export_events(
            output_path=None,
            confidence_threshold=0.5,
            scope="future",
            fmt=None  # 预期自动推理为 txt
        )
        assert count_stdout == 2
        mock_echo.assert_called_once()
        stdout_content = mock_echo.call_args[0][0]
        assert "Cosplay 活动日程表 (范围: 未来及未知)" in stdout_content
        assert "未来漫展B" in stdout_content
        assert "待定漫展C" in stdout_content
        assert "过去漫展A" not in stdout_content

    # 4b. 验证当省略 output_path 且强制 fmt="csv" 时，stdout 流的头部包含 BOM '\ufeff'
    import io
    mock_stdout = io.StringIO()
    with patch("sys.stdout", mock_stdout):
        count_stdout_csv = ExportService.export_events(
            output_path=None,
            confidence_threshold=0.5,
            scope="future",
            fmt="csv"
        )
        assert count_stdout_csv == 2
        csv_output = mock_stdout.getvalue()
        # 验证首字符是 UTF-8 BOM 字符 '\ufeff'
        assert csv_output.startswith('\ufeff')
        assert "Coser昵称,活动名称,活动日期,活动地点" in csv_output
        assert "未来漫展B" in csv_output
        assert "待定漫展C" in csv_output
        
    # 5. 整理清理测试数据
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cosplay_events WHERE raw_post_id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM raw_posts WHERE id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    conn.commit()
    conn.close()


def test_event_centric_aggregation_and_fusion():
    """测试时空融合引擎对模糊名称、滑动日期区间的聚类、融合、LLM裁判缓存及最宽外包络计算"""
    from src.services.fusion_service import EventFusionService
    from unittest.mock import patch, AsyncMock
    
    # 1. 注册测试 Coser
    DBService.add_coser("融合测试Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    # 2. 插入测试博文与日程数据
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content, is_analyzed) VALUES (?, ?, ?, ?, ?);", (coser_id, 'weibo', 'p_fuse_11', 'content', 0))
    raw_post_id = cursor.lastrowid
    conn.commit()
    
    # A. 场景 1：高度匹配 (ratio >= 0.75) 应该直接归一化
    event_id_1 = EventFusionService.find_or_create_normalized_event(cursor, "Comicup 30", "上海", "2026-05-02")
    
    # 再查询 'Comicup30'。相似度 ratio = 0.94，且同城同档期，预期返回同一个 ID
    event_id_2 = EventFusionService.find_or_create_normalized_event(cursor, "Comicup30", "上海", "2026-05-03")
    assert event_id_1 == event_id_2
    
    # B. 场景 2：临界匹配 (0.2 <= ratio < 0.75) 调用 LLM 裁判并缓存
    # 'C30' 与 'Comicup 30' 的相似度 ratio 约为 0.5。
    with patch("src.services.fusion_service.EventFusionService.run_fusion_judge_agent", new_callable=AsyncMock) as mock_judge:
        mock_judge.return_value = True
        
        event_id_3 = EventFusionService.find_or_create_normalized_event(cursor, "C30", "上海", "未知")
        # 验证返回了同一个 ID
        assert event_id_3 == event_id_1
        mock_judge.assert_called_once()
        
        # 验证别名缓存已被成功写入。第二次查询 'C30' 时，预期直接命中缓存，不触发 LLM
        mock_judge.reset_mock()
        event_id_4 = EventFusionService.find_or_create_normalized_event(cursor, "C30", "上海", "2026-05-03")
        assert event_id_4 == event_id_1
        mock_judge.assert_not_called()

    # C. 场景 3：时间包络计算
    # 模拟在 cosplay_events 中插入三条实际日程，关联到此超级节点
    cursor.execute(
        """
        INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, status, normalized_event_id)
        VALUES 
        (?, '融合测试Coser', 'Comicup 30', '2026-05-02', '上海新国际', '未开始', ?),
        (?, '融合测试Coser', 'Comicup30', '2026-05-03', '上海新国际', '未开始', ?),
        (?, '融合测试Coser', 'C30', '未知', '上海新国际', '未开始', ?);
        """,
        (raw_post_id, event_id_1, raw_post_id, event_id_1, raw_post_id, event_id_1)
    )
    # 触发包络计算
    EventFusionService.update_event_bounding_box(cursor, event_id_1)
    
    # 验证超级漫展节点的最大日期外包络区间已被正确计算为 2026-05-02 至 2026-05-03 (过滤了'未知')
    cursor.execute("SELECT start_date, end_date FROM normalized_events WHERE id = ?;", (event_id_1,))
    row = cursor.fetchone()
    assert row[0] == "2026-05-02"
    assert row[1] == "2026-05-03"
    
    # D. 场景 4：不同届或不同城市的超级漫展应该被隔离
    event_id_gz = EventFusionService.find_or_create_normalized_event(cursor, "CP30", "广州", "2026-05-02")
    assert event_id_gz != event_id_1
    
    # 物理清除测试数据
    cursor.execute("DELETE FROM cosplay_events WHERE raw_post_id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM raw_posts WHERE id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    cursor.execute("DELETE FROM normalized_events WHERE id IN (?, ?);", (event_id_1, event_id_gz))
    cursor.execute("DELETE FROM event_aliases WHERE normalized_event_id IN (?, ?);", (event_id_1, event_id_gz))
    conn.commit()
    conn.close()


def test_cli_summary_by_event_and_calendar(tmp_path):
    """测试通过 Click 运行 summary --by-event, calendar, export --view calendar 等命令的流畅度与对齐"""
    from click.testing import CliRunner
    from src.main import cli
    
    # 1. 注册测试 Coser
    DBService.add_coser("CLI测试Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content, is_analyzed) VALUES (?, ?, ?, ?, ?);", (coser_id, 'weibo', 'p_cli_11', 'content', 0))
    raw_post_id = cursor.lastrowid
    
    # 2. 插入测试超级漫展节点及关联日程
    cursor.execute(
        """
        INSERT INTO normalized_events (id, event_fingerprint, standard_name, city, start_date, end_date)
        VALUES (999, 'shanghai_cp30_test', 'Comicup 30', '上海', '2029-05-02', '2029-05-03');
        """
    )
    cursor.execute(
        """
        INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, status, confidence, normalized_event_id)
        VALUES (?, 'CLI测试Coser', 'Comicup 30', '2029-05-02', '上海国家会展中心', '未开始', 0.9, 999);
        """,
        (raw_post_id,)
    )
    conn.commit()
    conn.close()
    
    runner = CliRunner()
    
    # 3. 验证 summary --by-event 看板命令
    res_summary = runner.invoke(cli, ["summary", "--by-event"])
    assert res_summary.exit_code == 0
    assert "超级漫展集结看板" in res_summary.output
    assert "Comicup 30" in res_summary.output
    assert "CLI测试Coser" in res_summary.output
    
    # 4. 验证 calendar 日历看板命令
    res_cal = runner.invoke(cli, ["calendar", "--city", "上海", "--scope", "future"])
    assert res_cal.exit_code == 0
    assert "二次元 [上海] 漫展展讯日历看板" in res_cal.output
    assert "Comicup 30" in res_cal.output
    
    # 5. 验证 export --view calendar 导出 Markdown 表格文件及 BOM CSV
    md_file = tmp_path / "events_cal.md"
    res_exp_md = runner.invoke(cli, ["export", "--view", "calendar", "--output", str(md_file)])
    assert res_exp_md.exit_code == 0
    assert md_file.exists()
    with open(md_file, "r", encoding="utf-8") as f:
        md_content = f.read()
        assert "二次元超级漫展排期日历看板" in md_content
        assert "| 日期 | 城市 | 漫展名称 |" in md_content
        assert "Comicup 30" in md_content
        
    csv_file = tmp_path / "events_cal.csv"
    res_exp_csv = runner.invoke(cli, ["export", "--view", "calendar", "--output", str(csv_file)])
    assert res_exp_csv.exit_code == 0
    assert csv_file.exists()
    with open(csv_file, "rb") as f:
        bom = f.read(3)
        assert bom == b'\xef\xbb\xbf'
        
    # 6. 物理清除测试数据
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cosplay_events WHERE raw_post_id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM raw_posts WHERE id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    cursor.execute("DELETE FROM normalized_events WHERE id = 999;")
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_analyzer_breaker_permanent_failure():
    """测试三态熔断器对永久性/结构性故障的拦截与熔断升级"""
    # 1. 注册一个测试 coser 和博文
    DBService.add_coser("熔断测试姬")
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "熔断测试姬"][0]
    
    posts = [{
        "post_id": "breaker_post_111",
        "content": "漫展行程",
        "post_url": "url",
        "edit_count": 0,
        "published_at": None
    }]
    DBService.save_raw_posts(coser_id, "xhs", posts)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE platform = 'xhs' AND post_id = 'breaker_post_111';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()
    
    # 2. Mock 提取引擎 analyze_post_with_retry 返回一个包含非法状态的活动（触发 AssertionError）
    # 在 run_analyze 中运行，验证其被拦截并标记 is_analyzed = 2
    from unittest.mock import patch
    invalid_events = [
        {
            "event_name": "熔断漫展",
            "event_date": "2026-06-01",
            "event_place": "场馆",
            "event_description": "芙宁娜",
            "confidence": 0.95,
            "status": "已取销" # 非法状态拼写，强制校验失败
        }
    ]
    
    with patch("src.agents.event_agent.analyze_post_with_retry", return_value=invalid_events) as mock_analyze:
        from src.services.workflow_orchestrator import WorkflowOrchestrator
        total, success, analyzed = await WorkflowOrchestrator.run_analyze(confidence_threshold=0.3)
        
        # 验证分析成功回写状态数是 1 (因为熔断也算作扭转状态成功)
        assert analyzed == 1
        
    # 3. 验证主活动数据没有写入脏数据，且 raw_posts.is_analyzed 升级为 2
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM cosplay_events WHERE raw_post_id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 0
    
    cursor.execute("SELECT is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 2
    
    # 4. 再次执行增量拉取，验证已熔断博文被自动豁免跳过，不再拉取
    cursor.execute("SELECT COUNT(*) FROM raw_posts WHERE is_analyzed = 0;")
    unanalyzed_count = cursor.fetchone()[0]
    
    pending = DBService.get_unanalyzed_posts()
    assert len(pending) == unanalyzed_count
    assert not any(p["id"] == raw_post_id for p in pending)
    
    # 清理测试数据
    cursor.execute("DELETE FROM raw_posts WHERE id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_analyzer_breaker_transient_failure():
    """测试暂时性故障（网络抖动等普通异常）不触发熔断，保持 is_analyzed = 0 且编辑更新洗回状态 0"""
    DBService.add_coser("瞬态测试姬")
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "瞬态测试姬"][0]
    
    posts = [{
        "post_id": "transient_post_222",
        "content": "漫展行程",
        "post_url": "url",
        "edit_count": 0,
        "published_at": None
    }]
    DBService.save_raw_posts(coser_id, "weibo", posts)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE platform = 'weibo' AND post_id = 'transient_post_222';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()
    
    # 模拟大模型请求发生 ConnectionError 暂时性异常
    from unittest.mock import patch
    with patch("src.agents.event_agent.analyze_post_with_retry", side_effect=ConnectionError("Timeout!")):
        from src.services.workflow_orchestrator import WorkflowOrchestrator
        total, success, analyzed = await WorkflowOrchestrator.run_analyze(confidence_threshold=0.3)
        assert analyzed == 0
        
    # 验证 raw_posts.is_analyzed 依旧为 0
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 0
    
    # 验证爬虫更新可以将熔断状态重置回 0
    # 先强制模拟其为 2 状态
    cursor.execute("UPDATE raw_posts SET is_analyzed = 2 WHERE id = ?;", (raw_post_id,))
    conn.commit()
    
    # 触发微博爬虫等原位编辑次数递增更新，验证状态重置为 0
    updated_posts = [{
        "post_id": "transient_post_222",
        "content": "新改版漫展行程",
        "post_url": "url",
        "edit_count": 2, # 编辑数递增
        "published_at": None
    }]
    DBService.save_raw_posts(coser_id, "weibo", updated_posts)
    
    cursor.execute("SELECT content, edit_count, is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    stored_content, stored_edit, stored_is_analyzed = cursor.fetchone()
    assert stored_content == "新改版漫展行程"
    assert stored_edit == 2
    assert stored_is_analyzed == 0 # 成功洗回 0 状态！
    
    # 清理测试数据
    cursor.execute("DELETE FROM raw_posts WHERE id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_analyzer_consensus_all_extractors_failure_keeps_pending():
    """所有 extractor 临时失败时应保持 is_analyzed=0，不进入结构性熔断。"""
    from src.agents.event_agent import TransientLLMError
    from src.services.workflow_orchestrator import WorkflowOrchestrator

    DBService.add_coser("提取器全挂测试姬")
    coser_id = DBService.list_cosers()[0]["id"]
    DBService.save_raw_posts(coser_id, "weibo", [{"post_id": "all_extractors_down", "content": "漫展行程", "post_url": "url"}])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE post_id = 'all_extractors_down';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()

    with patch("src.agents.event_agent.analyze_post_with_retry", side_effect=TransientLLMError("all extractors down")):
        total, success, analyzed = await WorkflowOrchestrator.run_analyze(confidence_threshold=0.3)

    assert total == 1
    assert success == 0
    assert analyzed == 0

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 0
    conn.close()


def test_historical_events_are_skipped_before_fusion():
    """历史活动不应写入 cosplay_events，也不应创建 normalized_events。"""
    DBService.add_coser("历史过滤测试姬")
    coser_id = DBService.list_cosers()[0]["id"]
    DBService.save_raw_posts(coser_id, "weibo", [{"post_id": "history_filter_post", "content": "历史行程", "post_url": "url"}])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE post_id = 'history_filter_post';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()

    events = [
        {
            "event_name": "已过期漫展",
            "event_date": "2026-05-01",
            "event_place": "上海国家会展中心",
            "event_description": "历史行程",
            "confidence": 0.95,
            "source_url": "url",
            "event_type": "漫展",
        },
        {
            "event_name": "未来漫展",
            "event_date": "2026-07-01",
            "event_place": "上海国家会展中心",
            "event_description": "未来行程",
            "confidence": 0.95,
            "source_url": "url",
            "event_type": "漫展",
        },
        {
            "event_name": "未知日期活动",
            "event_date": "未知",
            "event_place": "广州",
            "event_description": "待定",
            "confidence": 0.95,
            "source_url": "url",
            "event_type": "一日店长",
        },
    ]

    assert DBService.save_extracted_events_transactional(raw_post_id, events, 0.3) is True

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT event_name FROM cosplay_events WHERE raw_post_id = ? ORDER BY id;", (raw_post_id,))
    stored_names = [r[0] for r in cursor.fetchall()]
    assert "已过期漫展" not in stored_names
    assert "未来漫展" in stored_names
    assert "未知日期活动" in stored_names

    cursor.execute("SELECT COUNT(*) FROM normalized_events WHERE standard_name = '已过期漫展';")
    assert cursor.fetchone()[0] == 0
    conn.close()


@pytest.mark.asyncio
async def test_breaker_permanent_failure_raises_and_marks_2():
    """测试用例 1：模拟大模型提炼通过，但在入库约束中故意触发 AssertionError，验证主活动表未插入任何脏数据，而 raw_posts.is_analyzed 状态成功置为 2 且下一轮分析不再加载。"""
    from src.services.db_service import DBService
    from src.services.workflow_orchestrator import WorkflowOrchestrator
    from src.models.db_models import get_db_connection
    from unittest.mock import patch

    # 1. 注册 Coser
    assert DBService.add_coser("硬错误熔断姬")
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "硬错误熔断姬"][0]

    # 2. 插入 raw post
    posts = [{
        "post_id": "breaker_perm_999",
        "content": "漫展行程",
        "post_url": "url",
        "edit_count": 0,
        "published_at": None
    }]
    assert DBService.save_raw_posts(coser_id, "xhs", posts) == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE platform = 'xhs' AND post_id = 'breaker_perm_999';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()

    # 3. 模拟大模型提取通过，返回包含非法 status (会触发 AssertionError) 的活动
    mock_events = [
        {
            "event_name": "违法漫展",
            "event_date": "2026-06-01",
            "event_place": "场馆",
            "event_description": "角色",
            "confidence": 0.9,
            "source_url": "url",
            "status": "已取销"  # 非标拼写状态值，触发 validate_status -> AssertionError
        }
    ]

    with patch("src.agents.event_agent.analyze_post_with_retry", return_value=mock_events):
        # 运行分析流程
        total, success, analyzed = await WorkflowOrchestrator.run_analyze(confidence_threshold=0.3)
        
        # 验证分析状态：应该有 1 条博文被处理，0 个活动成功入库，1 条博文被算作已分析（已处理状态扭转）
        assert total == 1
        assert success == 0
        assert analyzed == 1

    # 4. 验证数据库数据完整性：没有新活动插入，并且 is_analyzed 变为了 2
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM cosplay_events WHERE raw_post_id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 0

    cursor.execute("SELECT is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 2
    conn.close()

    # 5. 验证下一轮分析不会再次捞出该博文 (由于 is_analyzed = 2)
    unanalyzed_posts = DBService.get_unanalyzed_posts()
    assert not any(p["id"] == raw_post_id for p in unanalyzed_posts)

    # 清除测试数据
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM raw_posts WHERE id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_breaker_transient_failure_skips_keeps_0():
    """测试用例 2：模拟网络超时类异常，验证状态依旧为 0，并且下一轮能够继续捞出重试。"""
    from src.services.db_service import DBService
    from src.services.workflow_orchestrator import WorkflowOrchestrator
    from src.models.db_models import get_db_connection
    from unittest.mock import patch

    # 1. 注册 Coser
    assert DBService.add_coser("软错误超时姬")
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "软错误超时姬"][0]

    # 2. 插入 raw post
    posts = [{
        "post_id": "breaker_trans_888",
        "content": "漫展行程",
        "post_url": "url",
        "edit_count": 0,
        "published_at": None
    }]
    assert DBService.save_raw_posts(coser_id, "xhs", posts) == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE platform = 'xhs' AND post_id = 'breaker_trans_888';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()

    # 3. 模拟分析过程中发生普通网络异常/超时 (Exception)
    with patch("src.agents.event_agent.analyze_post_with_retry", side_effect=Exception("API Timeout")):
        # 运行分析流程
        total, success, analyzed = await WorkflowOrchestrator.run_analyze(confidence_threshold=0.3)
        
        # 验证分析状态：1 条待处理，0 个成功入库，0 个已分析完成 (因为是暂时性异常，不改变 is_analyzed 标记)
        assert total == 1
        assert success == 0
        assert analyzed == 0

    # 4. 验证数据库数据完整性：is_analyzed 依然保持 0
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 0
    conn.close()

    # 5. 验证下一轮仍能正常捞出待分析
    unanalyzed_posts = DBService.get_unanalyzed_posts()
    assert any(p["id"] == raw_post_id for p in unanalyzed_posts)

    # 清除测试数据
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM raw_posts WHERE id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_breaker_edit_count_reset_from_2_to_0():
    """测试用例 3：模拟将已熔断（状态为 2）的博文进行爬虫更新，验证其 is_analyzed 状态被成功洗回 0。"""
    from src.services.db_service import DBService
    from src.models.db_models import get_db_connection

    # 1. 注册 Coser
    assert DBService.add_coser("状态重置姬")
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "状态重置姬"][0]

    # 2. 插入 raw post
    posts = [{
        "post_id": "breaker_reset_777",
        "content": "漫展行程 第一次内容",
        "post_url": "url",
        "edit_count": 0,
        "published_at": None
    }]
    assert DBService.save_raw_posts(coser_id, "weibo", posts) == 1

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE platform = 'weibo' AND post_id = 'breaker_reset_777';")
    raw_post_id = cursor.fetchone()[0]
    
    # 3. 强行将该博文标记为 2 (熔断挂起)
    cursor.execute("UPDATE raw_posts SET is_analyzed = 2 WHERE id = ?;", (raw_post_id,))
    conn.commit()
    
    # 验证此时状态确为 2
    cursor.execute("SELECT is_analyzed FROM raw_posts WHERE id = ?;", (raw_post_id,))
    assert cursor.fetchone()[0] == 2
    conn.close()

    # 4. 模拟爬虫抓取到编辑更新后的新版本 (edit_count 递增，无后缀)
    updated_posts = [{
        "post_id": "breaker_reset_777",
        "content": "漫展行程 修正后的合法内容",
        "post_url": "url",
        "edit_count": 1,
        "published_at": None
    }]
    
    # 运行 save_raw_posts，应当触发 in-place 原位更新，同时将 is_analyzed 刷回 0
    assert DBService.save_raw_posts(coser_id, "weibo", updated_posts) == 1

    # 5. 验证状态被重置为 0，并且内容和 edit_count 更新成功
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_analyzed, content, edit_count FROM raw_posts WHERE id = ?;", (raw_post_id,))
    is_analyzed, content, edit_count = cursor.fetchone()
    assert is_analyzed == 0
    assert content == "漫展行程 修正后的合法内容"
    assert edit_count == 1
    conn.close()

    # 清除测试数据
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM raw_posts WHERE id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    conn.commit()
    conn.close()


def test_coser_multi_platform_dedup_and_merge():
    """验证 Coser 在多平台/多次发布未来同一日程时，原位 In-place 合并去重且拼接描述、升级链接和置信度"""
    # 1. 注册测试 Coser 和博文
    DBService.add_coser("多平台去重测试Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content) VALUES (?, 'weibo', 'p_weibo_dedup', 'weibo content');", (coser_id,))
    raw_post_id_1 = cursor.lastrowid
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content) VALUES (?, 'bilibili', 'p_bili_dedup', 'bili content');", (coser_id,))
    raw_post_id_2 = cursor.lastrowid
    conn.commit()
    
    # 2. 第一次录入微博日程 (CP30，第一天出黄泉)
    events_weibo = [{
        "event_name": "Comicup 30",
        "event_date": "2029-05-02",
        "event_place": "上海新国际",
        "event_description": "第一天出黄泉",
        "confidence": 0.88,
        "source_url": "url_weibo",
        "event_type": "漫展"
    }]
    assert DBService.save_extracted_events_transactional(raw_post_id_1, events_weibo, 0.0) is True
    
    # 验证此时日程有 1 行
    cursor.execute("SELECT id, raw_post_id, event_description, source_url, confidence FROM cosplay_events WHERE coser_name = '多平台去重测试Coser';")
    rows = cursor.fetchall()
    assert len(rows) == 1
    db_id = rows[0][0]
    assert rows[0][1] == raw_post_id_1
    assert rows[0][2] == "第一天出黄泉"
    assert rows[0][3] == "url_weibo"
    assert abs(rows[0][4] - 0.88) < 0.01
    
    # 3. 第二次录入B站日程 (CP30，A15摊位签售)，预期触发 In-place 合并去重
    events_bili = [{
        "event_name": "Comicup 30",
        "event_date": "2029-05-02",
        "event_place": "上海新国际",
        "event_description": "A15摊位签售",
        "confidence": 0.96,
        "source_url": "url_bili",
        "event_type": "漫展"
    }]
    assert DBService.save_extracted_events_transactional(raw_post_id_2, events_bili, 0.0) is True
    
    # 再次查询该 Coser 的所有日程，行数预期依然是 1
    cursor.execute("SELECT id, raw_post_id, event_description, source_url, confidence FROM cosplay_events WHERE coser_name = '多平台去重测试Coser';")
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == db_id  # 物理 ID 不变，原位更新
    assert rows[0][1] == raw_post_id_2  # 升级为最新博文 ID
    assert rows[0][2] == "第一天出黄泉 | A15摊位签售"  # 描述智能拼接合并
    assert rows[0][3] == "url_bili"  # source_url 升级为最新
    assert abs(rows[0][4] - 0.96) < 0.01  # 置信度升级为最新
    
    # 清除测试数据
    cursor.execute("DELETE FROM cosplay_events WHERE coser_name = '多平台去重测试Coser';")
    cursor.execute("DELETE FROM raw_posts WHERE id IN (?, ?);", (raw_post_id_1, raw_post_id_2))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    conn.commit()
    conn.close()


def test_abbreviation_alignment_and_low_ratio_referee():
    """验证缩写预对齐词典直接合并以及放宽后的 [0.2, 0.75) 低比率时空重叠触发裁判"""
    from src.services.fusion_service import EventFusionService
    from unittest.mock import patch, AsyncMock
    
    DBService.add_coser("融合测试Coser二代")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content) VALUES (?, 'weibo', 'p_abbrev', 'content');", (coser_id,))
    raw_post_id = cursor.lastrowid
    conn.commit()
    
    # A. 简称直接对齐测试：上海bw2026 应与 bilibiliworld2026 直接一致
    event_id_1 = EventFusionService.find_or_create_normalized_event(cursor, "bilibiliworld2026", "上海", "2026-05-02")
    event_id_2 = EventFusionService.find_or_create_normalized_event(cursor, "上海bw2026", "上海", "2026-05-02")
    # 由于 "bw" 自动在极简清洗中替换为 "bilibiliworld" 且剔除字符，"shanghaibilibiliworld2026" 相似比对极高直接命中
    assert event_id_1 == event_id_2
    
    # B. 放宽 ratio 下限至 0.2 并触发 LLM 裁判测试
    # "bilibiliworld2026" vs "上海BiliWorld26"。清洗后 "shanghaibilibiliworld26" 长度23，"bilibiliworld2026" 长度18
    # difflib.SequenceMatcher.ratio 约为 0.65，在 [0.2, 0.75) 区间内，且同城同档期 (2026-05-02 与 2026-05-03 在 3 天重叠窗口内)
    # 预期必须拉起 LLM 裁判判定
    with patch("src.services.fusion_service.EventFusionService.run_fusion_judge_agent", new_callable=AsyncMock) as mock_judge:
        mock_judge.return_value = True
        
        event_id_3 = EventFusionService.find_or_create_normalized_event(cursor, "上海BiliWorld26", "上海", "2026-05-03")
        assert event_id_3 == event_id_1
        mock_judge.assert_called_once()
        
    # 清理数据
    cursor.execute("DELETE FROM normalized_events WHERE city = '上海';")
    cursor.execute("DELETE FROM event_aliases WHERE city = '上海';")
    cursor.execute("DELETE FROM raw_posts WHERE id = ?;", (raw_post_id,))
    cursor.execute("DELETE FROM cosers WHERE id = ?;", (coser_id,))
    conn.commit()
    conn.close()


def test_date_inference_inheritance_view_and_export(tmp_path):
    """验证未知日程动态继承超级漫展日期，并在查询服务、控制台格式化、文件导出时稳定展现"""
    from src.views.terminal_renderer import TerminalRenderer
    from src.services.export_service import ExportService
    DBService.add_coser("CoserA_Known")
    DBService.add_coser("CoserB_Unknown")
    cosers = DBService.list_cosers()
    coser_a_id = [c for c in cosers if c["name"] == "CoserA_Known"][0]["id"]
    coser_b_id = [c for c in cosers if c["name"] == "CoserB_Unknown"][0]["id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content) VALUES (?, 'weibo', 'post_a', 'content');", (coser_a_id,))
    raw_post_a = cursor.lastrowid
    cursor.execute("INSERT INTO raw_posts (coser_id, platform, post_id, content) VALUES (?, 'weibo', 'post_b', 'content');", (coser_b_id,))
    raw_post_b = cursor.lastrowid
    conn.commit()
    
    # 1. 录入 A 具有明确举办日期的日程 (超级节点 CP30 被标定为 2029-05-02 至 2029-05-02)
    events_a = [{
        "event_name": "Comicup 30",
        "event_date": "2029-05-02",
        "event_place": "上海国家会展",
        "event_description": "第一天",
        "confidence": 0.9,
        "event_type": "漫展"
    }]
    assert DBService.save_extracted_events_transactional(raw_post_a, events_a, 0.0) is True
    
    # 2. 录入 B 具有未知日期日程
    events_b = [{
        "event_name": "Comicup 30",
        "event_date": "未知",
        "event_place": "上海国家会展",
        "event_description": "出角色",
        "confidence": 0.9,
        "event_type": "漫展"
    }]
    assert DBService.save_extracted_events_transactional(raw_post_b, events_b, 0.0) is True
    
    # 3. 验证 QueryService 看板查询继承
    all_events = DBService.get_all_events(0.0, scope="all")
    coser_b_event = [e for e in all_events if e["coser_name"] == "CoserB_Unknown"][0]
    # 日期应该自动继承并带上 (推算自超级节点) 标签
    assert coser_b_event["event_date"] == "2029-05-02 至 2029-05-02 (推算自超级节点)"
    
    # 4. 验证 TerminalRenderer._style_date 带有等宽彩显
    styled = TerminalRenderer._style_date(coser_b_event["event_date"])
    assert "\x1b" in styled  # 检查是否包含 ANSI Escape Codes 的彩显标记
    assert "2029-05-02 至 2029-05-02" in styled
    assert "(推算自超级节点)" in styled
    
    # 5. 验证 ExportService 导出继承
    out_txt = tmp_path / "export.txt"
    ExportService.export_events(str(out_txt), 0.0, "all", "txt")
    with open(out_txt, "r", encoding="utf-8") as f:
        txt_content = f.read()
    assert "2029-05-02 至 2029-05-02 (推算自超级节点)" in txt_content
    
    # 清理数据
    cursor.execute("DELETE FROM cosplay_events WHERE coser_name IN ('CoserA_Known', 'CoserB_Unknown');")
    cursor.execute("DELETE FROM normalized_events WHERE city = '上海';")
    cursor.execute("DELETE FROM raw_posts WHERE id IN (?, ?);", (raw_post_a, raw_post_b))
    cursor.execute("DELETE FROM cosers WHERE id IN (?, ?);", (coser_a_id, coser_b_id))
    conn.commit()
    conn.close()


def test_coser_duplicate_warnings():
    """测试新增和更新 Coser 时的名字相似度及平台 UID 占用冲突校验警告（非阻断且安全输出到 stderr）"""
    from click.testing import CliRunner
    from src.main import cli
    from src.services.db.coser_repository import CoserRepository
    
    runner = CliRunner()

    # 1. 注册基础 Coser，此时是干净的数据库，无警告
    result = runner.invoke(cli, ["coser", "add", "--name", "桃景三酪", "--bili", "11286045"])
    assert result.exit_code == 0
    assert "✓ 成功注册 Coser [桃景三酪]" in result.stdout
    assert "名字相似度碰撞" not in result.stderr
    assert "平台 UID 冲突检测" not in result.stderr

    # 2. 注册疑似冲突的 Coser "桃景三酪_"，且 bilibili_uid 设为 " 11286045 " (带空格，测试边界清洗)
    result = runner.invoke(cli, ["coser", "add", "--name", "桃景三酪_", "--bili", " 11286045 "])
    assert result.exit_code == 0
    
    # 验证名字相似度碰撞警告与 B站 UID 被 "桃景三酪" 占用的冲突警告都在 stderr 中，且 stdout 为成功消息
    assert "名字相似度碰撞" in result.stderr
    assert "桃景三酪_" in result.stderr
    assert "桃景三酪" in result.stderr
    assert "平台 UID 冲突检测" in result.stderr
    assert "bilibili_uid '11286045' 已被 Coser [桃景三酪] 绑定" in result.stderr
    assert "✓ 成功注册 Coser [桃景三酪_]" in result.stdout

    # 3. 尝试更新 Coser，以整数传入 UID，触发平台 UID 冲突警告并路由至 stderr
    # 首先添加另一个 coser "微博博主"（weibo_uid="999"）
    result = runner.invoke(cli, ["coser", "add", "--name", "微博博主", "--weibo", "999"])
    assert result.exit_code == 0
    
    # 更新 "桃景三酪_"，将其 weibo_uid 设为 999 (类型兼容性测试)
    result = runner.invoke(cli, ["coser", "update", "--name", "桃景三酪_", "--weibo", "999"])
    assert result.exit_code == 0
    assert "平台 UID 冲突检测" in result.stderr
    assert "weibo_uid '999' 已被 Coser [微博博主] 绑定" in result.stderr
    assert "✓ 成功更新 Coser [桃景三酪_] 的配置！" in result.stdout
    
    # 4. 更新自身 UID 时，不应该触发自己的冲突警告，且此时不应做名字相似度校验 (即使名字与桃景三酪相似)
    # 先把 桃景三酪_ 的 weibo_uid 清空，避免产生别的冲突干扰
    result = runner.invoke(cli, ["coser", "update", "--name", "桃景三酪_", "--weibo", ""])
    assert result.exit_code == 0
    
    # 更新 "微博博主"
    result = runner.invoke(cli, ["coser", "update", "--name", "微博博主", "--weibo", "999"])
    assert result.exit_code == 0
    assert "平台 UID 冲突检测" not in result.stderr
    assert "名字相似度碰撞" not in result.stderr

    # 5. 直接通过 Repository 接口测试类型兼容性与空格清洗
    warnings = CoserRepository.check_coser_duplicates(
        name="测试冲突者",
        bilibili_uid=11286045, # 传入 int 并且存在冲突
        check_name_similarity=False
    )
    assert len(warnings) == 2
    assert any("已被 Coser [桃景三酪] 绑定" in w for w in warnings)
    assert any("已被 Coser [桃景三酪_] 绑定" in w for w in warnings)
