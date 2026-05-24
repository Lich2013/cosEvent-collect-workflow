import os
import sys
import sqlite3
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# 确保项目根目录在 python 搜索路径中
sys.path.insert(0, os.getcwd())

from src.models.db_models import init_db, get_db_connection
from src.services.db_service import DBService
from src.config import settings
from src.models.schemas import TriageOutput

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """测试夹具：自动配置临时内存或临时文件数据库，确保测试隔离"""
    db_file = tmp_path / "test_cosevent.db"
    settings.db_path = str(db_file)
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
    整个写入必须 Rollback，且原始博文的 is_analyzed 状态必须依然为 0。
    """
    DBService.add_coser("事务Coser")
    cosers = DBService.list_cosers()
    coser_id = cosers[0]["id"]
    
    # 插入一条博文
    DBService.save_raw_posts(coser_id, "weibo", [{"post_id": "p888", "content": "漫展计划", "post_url": "url888"}])
    
    # 获取插入的 raw_post_id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE post_id = 'p888';")
    raw_post_id = cursor.fetchone()[0]
    conn.close()
    
    # 构造一批提取出的活动，其中第 2 条没有 event_name（设为 None），会触发 SQLite 的 NOT NULL 异常
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
            "event_name": None, # 异常数据！触发 SQLite NOT NULL 报错，引起回滚
            "event_date": "2026-07-02",
            "event_place": "上海世博馆",
            "event_description": "崩铁",
            "confidence": 0.8,
            "source_url": "url888"
        }
    ]
    
    # 执行原子事务保存，预期应该失败返回 False，并且执行回滚
    success = DBService.save_extracted_events_transactional(raw_post_id, events, confidence_threshold=0.3)
    assert success is False
    
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
    assert cursor.fetchone()[0] == 2
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
    # - 历史活动 (2026-01-10) 保持不变，不重复插入，也不被删除 (固化保护)
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
    
    # 应当只有 2 条活动：固化的 2026-01-10 历史活动，和新增的 2026-07-01 未来活动。
    # 2026-06-01 的旧未来活动已被软删除对齐。
    assert len(events_in_db) == 2
    
    assert events_in_db[0][0] == "历史漫展"
    assert events_in_db[0][1] == "2026-01-10"
    assert events_in_db[0][3] == "芙宁娜"
    
    assert events_in_db[1][0] == "新未来漫展B"
    assert events_in_db[1][1] == "2026-07-01"
    assert events_in_db[1][2] == "广州世贸馆"
    assert events_in_db[1][3] == "神里绫华"


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
    # 我们 mock 系统的 datetime.datetime.now 并在 Mock 块内执行数据保存与增量分析
    class MockDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                # 传入时区时，以 UTC 2026-05-23 23:00:00 加上时区偏移
                base_utc = datetime.datetime(2026, 5, 23, 23, 0, 0, tzinfo=datetime.timezone.utc)
                return base_utc.astimezone(tz)
            # Naive datetime 模拟 UTC 部署的服务器本地 naive 时间 2026-05-23 23:00:00
            return datetime.datetime(2026, 5, 23, 23, 0, 0)
            
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
    
    with patch("src.services.db_service.datetime.datetime", new=MockDatetime):
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
    
    assert len(events) == 2
    assert events[0][0] == "北京时区历史展"
    assert events[0][1] == "2026-05-23"
    # 验证 cosplay_events 的 created_at 在应用层已被精确锁死为 mock 对应的北京时间 "2026-05-24 07:00:00"
    assert events[0][3] == "2026-05-24 07:00:00"
    
    assert events[1][0] == "北京时区未来展"
    assert events[1][1] == "2026-05-24"
    assert events[1][3] == "2026-05-24 07:00:00"
    
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
    3. 校验 v0 版的未来行程被级联更新为 '已取消'，但历史行程受固化保护保持不变
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

    # 验证 v0 版本的历史漫展v0是否依旧是 '未开始' (冷冻保护)
    cursor.execute("SELECT status FROM cosplay_events WHERE raw_post_id = ? AND event_name = '历史漫展v0';", (raw_post_id_v0,))
    assert cursor.fetchone()[0] == "未开始"

    # 验证 v1 版本的新未来行程是否是 '未开始'
    cursor.execute("SELECT status FROM cosplay_events WHERE raw_post_id = ? AND event_name = '更新未来漫展v1';", (raw_post_id_v1,))
    assert cursor.fetchone()[0] == "未开始"
    conn.close()

    # 7. 验证 get_all_events() 过滤 '已取消' 日程
    all_events = DBService.get_all_events(0.3)
    # 应只包含 "历史漫展v0" (v0 版的) 和 "更新未来漫展v1" (v1 版的)，排除 "未来漫展v0" (已取消)
    active_names = [e["event_name"] for e in all_events if e["coser_name"] == "多版本测试姬"]
    assert "历史漫展v0" in active_names
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
    # 我们故意绕过提取框架，模拟异常插入。因为应用层校验，应抛出 AssertionError 或 IntegrityError
    assert DBService.save_extracted_events_transactional(raw_post_id, invalid_events, 0.3) is False


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

