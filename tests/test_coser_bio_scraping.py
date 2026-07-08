import os
import json
import sys
import datetime
import pytest
import grpc
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure the root directory is in python search path
sys.path.insert(0, os.getcwd())

from src.models.db_models import init_db, get_db_connection
from src.services.db_service import DBService
from src.config import settings
from src.tools.weibo_scraper import WeiboScraper
from src.tools.bilibili_scraper import BilibiliScraper
from src.tools.xhs_scraper import XhsScraper

# ==============================================================================
# Playwright expect_response 异步上下文管理器模拟器
# ==============================================================================
class MockExpectResponseContext:
    def __init__(self, value):
        import inspect
        if not (inspect.iscoroutine(value) or inspect.isawaitable(value)):
            async def _wrap():
                return value
            self.value = _wrap()
        else:
            self.value = value
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


# ==============================================================================
# 数据库隔离 Fixture
# ==============================================================================
@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """隔离测试数据库，防止测试污染生产数据"""
    db_file = tmp_path / "test_bio_scraping.db"
    original_db_path = settings.db_path
    settings.db_path = str(db_file)
    init_db()
    yield
    if db_file.exists():
        db_file.unlink()
    settings.db_path = original_db_path


# ==============================================================================
# 单元测试：Weibo 个人简介提取与虚拟动态合成
# ==============================================================================
@pytest.mark.asyncio
async def test_weibo_bio_scraping():
    scraper = WeiboScraper()
    
    # 模拟微博 API 成功返回用户数据，且 mymblog 返回空列表（说明无推文但有简介）
    mock_profile_json = {
        "data": {
            "user": {
                "description": "这是微博Coser的漫展行程介绍：6月1日广州萤火虫。"
            }
        }
    }
    
    mock_mymblog_json = {
        "data": {
            "list": []
        }
    }

    mock_resp_profile = MagicMock()
    mock_resp_profile.url = "https://weibo.com/ajax/profile/info?uid=123"
    mock_resp_profile.status = 200
    mock_resp_profile.json = AsyncMock(return_value=mock_profile_json)

    mock_resp_mymblog = MagicMock()
    mock_resp_mymblog.url = "https://weibo.com/ajax/statuses/mymblog?uid=123"
    mock_resp_mymblog.status = 200
    mock_resp_mymblog.json = AsyncMock(return_value=mock_mymblog_json)

    # 采用 MagicMock (同步事件与属性) + AsyncMock (异步操作) 组合模拟 Playwright page
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.get_attribute = AsyncMock(return_value=None)  # 禁用 DOM 兜底
    
    mock_page.expect_response = MagicMock(return_value=MockExpectResponseContext(mock_resp_mymblog))

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    callbacks = {}
    def mock_on(event_name, callback):
        callbacks[event_name] = callback
    mock_page.on = mock_on

    async def mock_goto(url):
        if "response" in callbacks:
            await callbacks["response"](mock_resp_profile)
            await callbacks["response"](mock_resp_mymblog)
    mock_page.goto.side_effect = mock_goto

    with patch.object(scraper, "scrape_flow_handler") as mock_flow:
        async def side_effect(fn, uid, limit):
            return await fn(mock_context, uid, limit)
        mock_flow.side_effect = side_effect

        posts = await scraper.fetch_weibo_posts("123", limit=5)

        # 验证虚拟推文成功合成
        assert len(posts) == 1
        assert posts[0]["post_id"] == "bio_123"
        assert "6月1日广州萤火虫" in posts[0]["content"]
        assert posts[0]["post_url"] == "https://weibo.com/u/123"
        assert posts[0]["edit_count"] == 0
        assert "published_at" in posts[0]


@pytest.mark.asyncio
async def test_weibo_empty_bio_filter():
    """验证空白简介前置过滤门槛，不应生成虚拟推文"""
    scraper = WeiboScraper()
    mock_profile_json = {
        "data": {
            "user": {
                "description": "  "  # 纯空白简介
            }
        }
    }
    
    mock_resp_profile = MagicMock()
    mock_resp_profile.url = "https://weibo.com/ajax/profile/info?uid=123"
    mock_resp_profile.status = 200
    mock_resp_profile.json = AsyncMock(return_value=mock_profile_json)

    mock_resp_mymblog = MagicMock()
    mock_resp_mymblog.url = "https://weibo.com/ajax/statuses/mymblog?uid=123"
    mock_resp_mymblog.status = 200
    mock_resp_mymblog.json = AsyncMock(return_value={"data": {"list": []}})

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.get_attribute = AsyncMock(return_value=None)
    mock_page.expect_response = MagicMock(return_value=MockExpectResponseContext(mock_resp_mymblog))

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    callbacks = {}
    mock_page.on = lambda name, cb: callbacks.update({name: cb})
    
    async def mock_goto(url):
        if "response" in callbacks:
            await callbacks["response"](mock_resp_profile)
            await callbacks["response"](mock_resp_mymblog)
    mock_page.goto.side_effect = mock_goto

    with patch.object(scraper, "scrape_flow_handler") as mock_flow:
        async def side_effect(fn, uid, limit):
            return await fn(mock_context, uid, limit)
        mock_flow.side_effect = side_effect

        posts = await scraper.fetch_weibo_posts("123", limit=5)
        # 验证空白简介被过滤，未生成任何动态
        assert len(posts) == 0


# ==============================================================================
# 单元测试：B站 gRPC 签名提取与 Card API 补爬及自愈
# ==============================================================================
@pytest.mark.asyncio
async def test_bilibili_grpc_bio_scraping():
    scraper = BilibiliScraper()
    
    # 1. 模拟 gRPC 响应：签名 sign 为空 (模拟真实 B站 gRPC 接口返回情况)
    mock_author = MagicMock()
    mock_author.name = "B站Coser"
    mock_author.sign = ""  # 为空！
    
    mock_module_author = MagicMock()
    mock_module_author.WhichOneof.return_value = "module_author"
    mock_module_author.module_author.HasField.return_value = True
    mock_module_author.module_author.author = mock_author
    mock_module_author.module_author.ptime_label_text = "5-28"

    mock_module_desc = MagicMock()
    mock_module_desc.WhichOneof.return_value = "module_desc"
    mock_module_desc.module_desc.text = "这是一条普通的B站动态正文"

    mock_item = MagicMock()
    mock_item.extend.dyn_id_str = "11223344"
    mock_item.modules = [mock_module_author, mock_module_desc]
    
    mock_space_resp = MagicMock()
    mock_space_resp.list = [mock_item]

    # 2. 模拟 Web Card API 的 HTTP 成功响应
    import json
    mock_card_json = {
        "code": 0,
        "message": "OK",
        "data": {
            "card": {
                "sign": "漫展档期：端午上海CP30"
            }
        }
    }
    mock_http_response = MagicMock()
    mock_http_response.__enter__.return_value = mock_http_response
    mock_http_response.read.return_value = json.dumps(mock_card_json).encode("utf-8")

    with patch("bilibili.app.dynamic.v2_pb2.DynSpaceReq"), \
         patch("bilibili.metadata_pb2.Metadata"), \
         patch("bilibili.metadata.device_pb2.Device"), \
         patch("bilibili.metadata.network_pb2.Network"), \
         patch("bilibili.metadata.restriction_pb2.Restriction"), \
         patch("bilibili.metadata.locale_pb2.Locale"), \
         patch("bilibili.metadata.fawkes_pb2.FawkesReq"), \
         patch("grpc.secure_channel"), \
         patch("bilibili.app.dynamic.v2_pb2_grpc.DynamicStub") as mock_stub_cls, \
         patch("urllib.request.urlopen", return_value=mock_http_response) as mock_urlopen, \
         patch.object(settings, "bilibili_grpc_access_token", "fake_token"), \
         patch.object(settings, "bilibili_grpc_mid", 456):
         
        # Mock gRPC Stub Call
        mock_stub = MagicMock()
        mock_stub.DynSpace.return_value = mock_space_resp
        mock_stub_cls.return_value = mock_stub
        
        posts = await scraper.fetch_bilibili_posts_grpc("456", limit=5)
        
        # 验证提取并合成了 1条常规动态 + 1条Bio虚拟动态
        assert len(posts) == 2
        # 常规动态
        assert posts[0]["post_id"] == "11223344"
        # 虚拟简介动态
        assert posts[1]["post_id"] == "bio_456"
        assert posts[1]["content"] == "[个人简介] 漫展档期：端午上海CP30"
        assert posts[1]["post_url"] == "https://space.bilibili.com/456"
        
        # 验证 urlopen 被成功调用
        mock_urlopen.assert_called_once()


@pytest.mark.asyncio
async def test_bilibili_grpc_bio_scraping_error_resilience():
    """测试 gRPC 模式下，Card API 补爬签名接口由于网络异常报错时，常规动态正常交付，系统优雅自愈不崩溃"""
    scraper = BilibiliScraper()
    
    # 模拟 gRPC 响应：签名 sign 为空
    mock_author = MagicMock()
    mock_author.name = "B站Coser"
    mock_author.sign = ""
    
    mock_module_author = MagicMock()
    mock_module_author.WhichOneof.return_value = "module_author"
    mock_module_author.module_author.HasField.return_value = True
    mock_module_author.module_author.author = mock_author
    mock_module_author.module_author.ptime_label_text = "5-28"

    mock_module_desc = MagicMock()
    mock_module_desc.WhichOneof.return_value = "module_desc"
    mock_module_desc.module_desc.text = "这是一条普通的B站动态正文"

    mock_item = MagicMock()
    mock_item.extend.dyn_id_str = "11223344"
    mock_item.modules = [mock_module_author, mock_module_desc]
    
    mock_space_resp = MagicMock()
    mock_space_resp.list = [mock_item]

    # 模拟 Web Card 接口请求抛出异常 (如 HTTP Error)
    import urllib.error
    def mock_urlopen_error(*args, **kwargs):
        raise urllib.error.URLError("Connection timeout")

    with patch("bilibili.app.dynamic.v2_pb2.DynSpaceReq"), \
         patch("bilibili.metadata_pb2.Metadata"), \
         patch("bilibili.metadata.device_pb2.Device"), \
         patch("bilibili.metadata.network_pb2.Network"), \
         patch("bilibili.metadata.restriction_pb2.Restriction"), \
         patch("bilibili.metadata.locale_pb2.Locale"), \
         patch("bilibili.metadata.fawkes_pb2.FawkesReq"), \
         patch("grpc.secure_channel"), \
         patch("bilibili.app.dynamic.v2_pb2_grpc.DynamicStub") as mock_stub_cls, \
         patch("urllib.request.urlopen", side_effect=mock_urlopen_error), \
         patch.object(settings, "bilibili_grpc_access_token", "fake_token"), \
         patch.object(settings, "bilibili_grpc_mid", 456):
         
        # Mock gRPC Stub Call
        mock_stub = MagicMock()
        mock_stub.DynSpace.return_value = mock_space_resp
        mock_stub_cls.return_value = mock_stub
        
        posts = await scraper.fetch_bilibili_posts_grpc("456", limit=5)
        
        # 即使补爬接口报错，主程序也绝对不能崩溃，应该只返回 1 条常规动态，虚拟 Bio 推文被静默跳过
        assert len(posts) == 1
        assert posts[0]["post_id"] == "11223344"



# ==============================================================================
# 单元测试：B站 Playwright 签名提取与 DOM 兜底
# ==============================================================================
@pytest.mark.asyncio
async def test_bilibili_playwright_bio_scraping():
    scraper = BilibiliScraper()
    
    # 模拟 api.bilibili.com/x/space/wbi/acc/info 响应体
    mock_acc_json = {
        "code": 0,
        "data": {
            "sign": "这是B站签名：暑假在广州萤火虫出没。"
        }
    }
    
    mock_resp_acc = MagicMock()
    mock_resp_acc.url = "https://api.bilibili.com/x/space/wbi/acc/info?mid=456"
    mock_resp_acc.status = 200
    mock_resp_acc.json = AsyncMock(return_value=mock_acc_json)

    mock_feed_json = {"data": {"items": []}}
    mock_resp_feed = MagicMock()
    mock_resp_feed.url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed"
    mock_resp_feed.status = 200
    mock_resp_feed.json = AsyncMock(return_value=mock_feed_json)

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.locator = MagicMock()
    mock_page.locator.return_value.is_visible = AsyncMock(return_value=False) # 禁用 DOM

    mock_page.expect_response = MagicMock(return_value=MockExpectResponseContext(mock_resp_feed))

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    callbacks = {}
    mock_page.on = lambda name, cb: callbacks.update({name: cb})
    
    async def mock_goto(url):
        if "response" in callbacks:
            await callbacks["response"](mock_resp_acc)
            await callbacks["response"](mock_resp_feed)
    mock_page.goto.side_effect = mock_goto

    with patch.object(scraper, "scrape_flow_handler") as mock_flow:
        async def side_effect(fn, uid, limit):
            return await fn(mock_context, uid, limit)
        mock_flow.side_effect = side_effect
        
        posts = await scraper._fetch_bilibili_posts_playwright("456", limit=5)
        
        # 验证虚拟简介动态合成成功
        assert len(posts) == 1
        assert posts[0]["post_id"] == "bio_456"
        assert "暑假在广州萤火虫出没" in posts[0]["content"]


# ==============================================================================
# 单元测试：小红书个人介绍提取与 DOM 兜底
# ==============================================================================
@pytest.mark.asyncio
async def test_xhs_bio_scraping_dom_fallback():
    """测试小红书在 Ajax 接口未拦截到时，通过 DOM 兜底成功解析 Bio 并且主程序不崩溃"""
    scraper = XhsScraper()
    
    # 模拟 expect_response 抛出 TimeoutError，模拟拦截失败
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    class MockExpectResponseErrorContext:
        async def __aenter__(self):
            raise Exception("Timeout intercepting otherinfo")
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_page.expect_response = MagicMock(return_value=MockExpectResponseErrorContext())
    
    # 模拟 DOM 选择器成功定位
    mock_locator = AsyncMock()
    mock_locator.is_visible.return_value = True
    mock_locator.inner_text.return_value = "这是小红书个人介绍：7月10日一日店长排班。"
    mock_page.locator.return_value = mock_locator

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    with patch.object(scraper, "scrape_flow_handler") as mock_flow:
        async def side_effect(fn, uid, limit):
            return await fn(mock_context, uid, limit)
        mock_flow.side_effect = side_effect
        
        posts = await scraper.fetch_xhs_posts("789", limit=5)
        
        # 验证通过 DOM 兜底完美抓取
        assert len(posts) == 1
        assert posts[0]["post_id"] == "bio_789"
        assert "7月10日一日店长排班" in posts[0]["content"]


@pytest.mark.asyncio
async def test_xhs_bio_scraping_api_success():
    """测试小红书在 Ajax 接口拦截成功时，解析 JSON 中的 desc 字段成功获得 Bio"""
    scraper = XhsScraper()
    
    mock_resp_otherinfo = MagicMock()
    mock_resp_otherinfo.url = "https://www.xiaohongshu.com/api/sns/web/v1/user/otherinfo?target_user_id=789"
    mock_resp_otherinfo.status = 200
    mock_resp_otherinfo.json = AsyncMock(return_value={"data": {"desc": "这是小红书接口返回的签名：6月1日广州萤火虫出没。"}})

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.expect_response = MagicMock(return_value=MockExpectResponseContext(mock_resp_otherinfo))
    
    # 模拟 DOM 选择器定位失败，确保完全由 API 接口提供数据
    mock_locator = AsyncMock()
    mock_locator.is_visible.return_value = False
    mock_page.locator.return_value = mock_locator

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    with patch.object(scraper, "scrape_flow_handler") as mock_flow:
        async def side_effect(fn, uid, limit):
            return await fn(mock_context, uid, limit)
        mock_flow.side_effect = side_effect
        
        posts = await scraper.fetch_xhs_posts("789", limit=5)
        
        # 验证虚拟简介动态合成成功，且只有 1 条
        assert len(posts) == 1
        assert posts[0]["post_id"] == "bio_789"
        assert "6月1日广州萤火虫出没" in posts[0]["content"]


@pytest.mark.asyncio
async def test_xhs_bio_scraping_rate_limit_bypasses_storage_state():
    """测试当小红书爬取遭遇风控抛出 XhsRateLimitError 时，scrape_flow_handler 捕获该异常且不执行 storage_state 回写"""
    from src.tools.playwright_base import XhsRateLimitError
    scraper = XhsScraper()
    
    # 模拟 async_playwright context
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    
    # 模拟 context
    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()
    mock_context.storage_state = AsyncMock()  # 我们要验证这个没被调用！
    
    # 模拟 browser
    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()
    
    # 模拟 playwright chromium launch
    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)
    
    mock_p = MagicMock()
    mock_p.chromium = mock_chromium
    
    # 用 patch.object 拦截 async_playwright 上下文管理器以避免真实启动浏览器
    class MockAsyncPlaywrightContext:
        async def __aenter__(self):
            return mock_p
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    # 模拟实际调用的工作函数，抛出 XhsRateLimitError
    async def mock_work_func(context, uid, limit):
        raise XhsRateLimitError("Rate limit triggered in test")

    with patch("src.tools.playwright_base.async_playwright", return_value=MockAsyncPlaywrightContext()), \
         patch.object(scraper, "_check_state_cookies_expired", return_value=False):
        
        # 运行流程处理器
        result = await scraper.scrape_flow_handler(mock_work_func, "789", 5)
        
        # 验证返回空列表
        assert result == []
        # 验证 context.storage_state 没有被调用 (这就是关键的隔离风控缓存验证！)
        mock_context.storage_state.assert_not_called()


def test_xhs_otherinfo_health_classification():
    """小红书 otherinfo 业务响应应能稳定分类所有健康状态。"""
    scraper = XhsScraper()

    cases = [
        ({"data": {"desc": "上海CP30"}}, "healthy", "上海CP30"),
        ({"data": {"desc": "  "}}, "empty_bio", ""),
        ({"code": -1, "msg": "请先登录"}, "auth_invalid", ""),
        ({"code": -1, "msg": "访问频繁，请完成验证码"}, "rate_limited", ""),
        ({"code": -1, "msg": "用户不存在或私密"}, "not_found_or_private", ""),
        ({"foo": "bar"}, "unknown_schema", ""),
    ]

    for payload, expected_status, expected_bio in cases:
        status, bio, summary = scraper.classify_otherinfo_response(payload)
        assert status == expected_status
        assert bio == expected_bio
        assert "keys=" in summary


@pytest.mark.asyncio
async def test_xhs_page_state_classification():
    """页面状态检测覆盖登录、验证、访问频繁、用户不可见和正常页面。"""
    scraper = XhsScraper()

    async def classify(url, body):
        page = MagicMock()
        page.url = url
        locator = MagicMock()
        locator.inner_text = AsyncMock(return_value=body)
        page.locator.return_value = locator
        return await scraper.classify_page_state(page)

    assert (await classify("https://www.xiaohongshu.com/login", ""))[0] == "auth_invalid"
    assert (await classify("https://www.xiaohongshu.com/website-login/captcha?redirectPath=/user/profile/u", ""))[0] == "rate_limited"
    assert (await classify("https://www.xiaohongshu.com/user/profile/u", "请完成滑块安全验证"))[0] == "rate_limited"
    assert (await classify("https://www.xiaohongshu.com/user/profile/u", "访问频繁，请稍后再试"))[0] == "rate_limited"
    assert (await classify("https://www.xiaohongshu.com/user/profile/u", "用户不存在或内容无法查看"))[0] == "not_found_or_private"
    assert (await classify("https://www.xiaohongshu.com/user/profile/u", "普通用户主页内容"))[0] == "unknown_schema"


@pytest.mark.asyncio
async def test_xhs_session_health_error_blocks_writeback(tmp_path):
    """小红书业务级非健康状态应禁止 state.json 和种子 Cookie 回写。"""
    from src.tools.playwright_base import SessionHealthError

    scraper = XhsScraper()
    scraper.state_file = tmp_path / "state.json"
    scraper.seed_file = tmp_path / "xhs_cookies.json"
    scraper.seed_file.write_text("web_session=s; a1=a; websectiga=w; xsecappid=x", encoding="utf-8")

    mock_context = MagicMock()
    mock_context.set_default_timeout = MagicMock()
    mock_context.add_cookies = AsyncMock()
    mock_context.close = AsyncMock()
    mock_context.storage_state = AsyncMock()
    mock_context.cookies = AsyncMock(return_value=[])

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()
    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)
    mock_p = MagicMock()
    mock_p.chromium = mock_chromium

    class MockAsyncPlaywrightContext:
        async def __aenter__(self):
            return mock_p
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def mock_work_func(context):
        scraper._set_status("auth_invalid", "请先登录")
        raise SessionHealthError("小红书 otherinfo 非健康响应: auth_invalid")

    with patch("src.tools.playwright_base.async_playwright", return_value=MockAsyncPlaywrightContext()), \
         patch.object(scraper, "_check_state_cookies_expired", return_value=True):
        result = await scraper.scrape_flow_handler(mock_work_func)

    assert result == []
    assert scraper.skip_state_write is True
    assert scraper.skip_seed_write is True
    mock_context.storage_state.assert_not_called()


@pytest.mark.asyncio
async def test_xhs_missing_key_cookie_blocks_seed_write(tmp_path):
    """健康抓取后若缺少小红书关键 Cookie，不应覆盖种子文件。"""
    scraper = XhsScraper()
    scraper.state_file = tmp_path / "state.json"
    scraper.seed_file = tmp_path / "xhs_cookies.json"
    scraper.seed_file.write_text("original", encoding="utf-8")
    scraper.mark_session_healthy()

    mock_context = MagicMock()
    mock_context.storage_state = AsyncMock()
    mock_context.cookies = AsyncMock(return_value=[
        {"name": "web_session", "value": "s"},
        {"name": "a1", "value": "a"},
        {"name": "websectiga", "value": "w"},
    ])

    with patch.object(scraper, "update_seed_cookies") as mock_update_seed:
        await scraper._write_session_state(mock_context)

    mock_context.storage_state.assert_awaited_once_with(path=str(scraper.state_file))
    mock_update_seed.assert_not_called()
    assert scraper.seed_file.read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_playwright_launch_uses_headless_setting():
    """Playwright headless 开关应从 settings.yaml 映射出的 settings 读取。"""
    scraper = XhsScraper()
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=MagicMock())
    original = settings.playwright_headless
    settings.playwright_headless = False
    try:
        await scraper._launch_browser(mock_playwright)
    finally:
        settings.playwright_headless = original

    mock_playwright.chromium.launch.assert_awaited_once_with(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"]
    )


@pytest.mark.asyncio
async def test_xhs_batch_reuses_context_and_waits_between_accounts():
    """批次抓取应在同一个上下文中顺序访问账号并插入账号间等待。"""
    scraper = XhsScraper()
    mock_context = MagicMock()
    items = [
        {"id": 1, "name": "A", "xhs_uid": "u1"},
        {"id": 2, "name": "B", "xhs_uid": "u2"},
    ]

    async def fake_batch_flow(work_func, batch_items, limit):
        return await work_func(mock_context, batch_items, limit)

    async def fake_fetch(context, uid, limit, prewarm=True):
        assert context is mock_context
        return [{"post_id": f"bio_{uid}", "content": "[个人简介] test", "post_url": "u", "edit_count": 0, "published_at": "2026-01-01 00:00:00"}]

    with patch.object(scraper, "scrape_batch_flow_handler", side_effect=fake_batch_flow), \
         patch.object(scraper, "fetch_xhs_posts_with_context", side_effect=fake_fetch) as mock_fetch, \
         patch.object(scraper, "natural_wait", new=AsyncMock()) as mock_wait:
        results = await scraper.fetch_xhs_posts_batch(items, limit=5)

    assert [r["coser"]["id"] for r in results] == [1, 2]
    assert mock_fetch.await_count == 2
    mock_wait.assert_awaited_once_with(7.0, 10.0)


@pytest.mark.asyncio
async def test_xhs_batch_long_pause_after_success_threshold():
    """小红书批次达到成功阈值后，应在下一个账号前执行长暂停。"""
    scraper = XhsScraper()
    mock_context = MagicMock()
    items = [
        {"id": 1, "name": "A", "xhs_uid": "u1"},
        {"id": 2, "name": "B", "xhs_uid": "u2"},
        {"id": 3, "name": "C", "xhs_uid": "u3"},
    ]

    async def fake_batch_flow(work_func, batch_items, limit):
        return await work_func(mock_context, batch_items, limit)

    async def fake_fetch(context, uid, limit, prewarm=True):
        scraper._set_status("success")
        return [{"post_id": f"bio_{uid}", "content": "[个人简介] test", "post_url": "u", "edit_count": 0, "published_at": "2026-01-01 00:00:00"}]

    original_every = settings.xhs_long_pause_every_successes
    original_min = settings.xhs_long_pause_min_seconds
    original_max = settings.xhs_long_pause_max_seconds
    settings.xhs_long_pause_every_successes = 2
    settings.xhs_long_pause_min_seconds = 30.0
    settings.xhs_long_pause_max_seconds = 60.0
    try:
        with patch.object(scraper, "scrape_batch_flow_handler", side_effect=fake_batch_flow), \
             patch.object(scraper, "fetch_xhs_posts_with_context", side_effect=fake_fetch), \
             patch.object(scraper, "natural_wait", new=AsyncMock()) as mock_wait:
            results = await scraper.fetch_xhs_posts_batch(items, limit=5)
    finally:
        settings.xhs_long_pause_every_successes = original_every
        settings.xhs_long_pause_min_seconds = original_min
        settings.xhs_long_pause_max_seconds = original_max

    assert len(results) == 3
    assert mock_wait.await_args_list[0].args == (7.0, 10.0)
    assert mock_wait.await_args_list[1].args == (7.0, 10.0)
    assert mock_wait.await_args_list[2].args == (30.0, 60.0)


@pytest.mark.asyncio
async def test_xhs_default_path_waits_for_page_triggered_otherinfo():
    """默认路径应等待页面自然触发 otherinfo，不使用 Python HTTP 客户端兜底。"""
    scraper = XhsScraper()
    mock_resp_otherinfo = MagicMock()
    mock_resp_otherinfo.url = "https://www.xiaohongshu.com/api/sns/web/v1/user/otherinfo?target_user_id=789"
    mock_resp_otherinfo.status = 200
    mock_resp_otherinfo.json = AsyncMock(return_value={"data": {"desc": "自然触发的简介"}})

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.expect_response = MagicMock(return_value=MockExpectResponseContext(mock_resp_otherinfo))
    mock_page.on = MagicMock()
    mock_locator = AsyncMock()
    mock_locator.is_visible.return_value = False
    mock_page.locator.return_value = mock_locator
    mock_page.mouse.wheel = AsyncMock()

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.request.get = AsyncMock()

    with patch.object(scraper, "prewarm_page", new=AsyncMock()), \
         patch.object(scraper, "natural_wait", new=AsyncMock()), \
         patch("urllib.request.urlopen") as mock_urlopen:
        posts = await scraper.fetch_xhs_posts_with_context(mock_context, "789", limit=5)

    assert posts[0]["post_id"] == "bio_789"
    mock_page.expect_response.assert_called_once()
    mock_page.goto.assert_awaited_once_with("https://www.xiaohongshu.com/user/profile/789")
    mock_context.request.get.assert_not_called()
    mock_urlopen.assert_not_called()


@pytest.mark.asyncio
async def test_seed_cookie_newer_bypasses_state(tmp_path):
    """种子 Cookie 文件比 state 新时，应旁路旧 storage_state 并注入种子 Cookie。"""
    scraper = WeiboScraper()
    scraper.state_file = tmp_path / "state.json"
    scraper.seed_file = tmp_path / "weibo_cookies.json"
    scraper.state_file.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    scraper.seed_file.write_text("SUB=new; SUBP=new; WBPSESS=new; XSRF-TOKEN=new", encoding="utf-8")

    old_time = datetime.datetime.now().timestamp() - 60
    new_time = datetime.datetime.now().timestamp()
    os.utime(scraper.state_file, (old_time, old_time))
    os.utime(scraper.seed_file, (new_time, new_time))

    mock_context = MagicMock()
    mock_context.set_default_timeout = MagicMock()
    mock_context.add_cookies = AsyncMock()
    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    with patch.object(scraper, "_check_state_cookies_expired", return_value=False):
        context = await scraper.get_browser_context(mock_browser)

    assert context is mock_context
    assert scraper.context_source == "seed"
    mock_browser.new_context.assert_called_once()
    kwargs = mock_browser.new_context.call_args.kwargs
    assert "storage_state" not in kwargs
    mock_context.add_cookies.assert_awaited_once()


@pytest.mark.asyncio
async def test_weibo_unhealthy_mymblog_blocks_writeback(tmp_path):
    """微博 mymblog 非健康响应应触发会话健康异常并禁止回写。"""
    from src.tools.playwright_base import SessionHealthError

    scraper = WeiboScraper()
    scraper.state_file = tmp_path / "state.json"
    scraper.seed_file = tmp_path / "weibo_cookies.json"

    with pytest.raises(SessionHealthError):
        scraper._assert_mymblog_healthy({"ok": 0, "msg": "未登录", "data": None})

    assert scraper.skip_state_write is True
    assert scraper.skip_seed_write is True
    assert scraper.session_health_verified is False


@pytest.mark.asyncio
async def test_weibo_state_unhealthy_retries_with_seed_and_writes_when_healthy(tmp_path):
    """state 业务级失效后，应使用种子 Cookie 重试一次，重试健康后允许回写。"""
    from src.tools.playwright_base import SessionHealthError

    scraper = WeiboScraper()
    scraper.state_file = tmp_path / "state.json"
    scraper.seed_file = tmp_path / "weibo_cookies.json"
    scraper.state_file.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    scraper.seed_file.write_text("SUB=s; SUBP=s; WBPSESS=s; XSRF-TOKEN=s", encoding="utf-8")
    new_time = datetime.datetime.now().timestamp()
    old_time = new_time - 60
    os.utime(scraper.seed_file, (old_time, old_time))
    os.utime(scraper.state_file, (new_time, new_time))

    state_context = MagicMock()
    state_context.set_default_timeout = MagicMock()
    state_context.close = AsyncMock()
    state_context.storage_state = AsyncMock()

    seed_context = MagicMock()
    seed_context.set_default_timeout = MagicMock()
    seed_context.add_cookies = AsyncMock()
    seed_context.close = AsyncMock()
    seed_context.storage_state = AsyncMock()
    seed_context.cookies = AsyncMock(return_value=[
        {"name": "SUB", "value": "s"},
        {"name": "SUBP", "value": "s"},
        {"name": "WBPSESS", "value": "s"},
        {"name": "XSRF-TOKEN", "value": "s"},
    ])

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(side_effect=[state_context, seed_context])
    mock_browser.close = AsyncMock()
    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)
    mock_p = MagicMock()
    mock_p.chromium = mock_chromium

    class MockAsyncPlaywrightContext:
        async def __aenter__(self):
            return mock_p
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    calls = 0
    async def mock_work_func(context):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SessionHealthError("mymblog 非健康响应: auth_invalid")
        scraper.mark_session_healthy()
        return [{"post_id": "ok"}]

    with patch("src.tools.playwright_base.async_playwright", return_value=MockAsyncPlaywrightContext()), \
         patch.object(scraper, "_check_state_cookies_expired", return_value=False), \
         patch.object(scraper, "update_seed_cookies") as mock_update_seed:
        result = await scraper.scrape_flow_handler(mock_work_func)

    assert result == [{"post_id": "ok"}]
    assert calls == 2
    state_context.storage_state.assert_not_called()
    seed_context.storage_state.assert_awaited_once_with(path=str(scraper.state_file))
    mock_update_seed.assert_called_once()


@pytest.mark.asyncio
async def test_weibo_state_and_seed_unhealthy_do_not_writeback(tmp_path):
    """state 与种子 Cookie 都无法通过微博健康检查时，应返回空列表且不回写。"""
    from src.tools.playwright_base import SessionHealthError

    scraper = WeiboScraper()
    scraper.state_file = tmp_path / "state.json"
    scraper.seed_file = tmp_path / "weibo_cookies.json"
    scraper.state_file.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    scraper.seed_file.write_text("SUB=s; SUBP=s; WBPSESS=s; XSRF-TOKEN=s", encoding="utf-8")
    new_time = datetime.datetime.now().timestamp()
    old_time = new_time - 60
    os.utime(scraper.seed_file, (old_time, old_time))
    os.utime(scraper.state_file, (new_time, new_time))

    state_context = MagicMock()
    state_context.set_default_timeout = MagicMock()
    state_context.close = AsyncMock()
    state_context.storage_state = AsyncMock()

    seed_context = MagicMock()
    seed_context.set_default_timeout = MagicMock()
    seed_context.add_cookies = AsyncMock()
    seed_context.close = AsyncMock()
    seed_context.storage_state = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(side_effect=[state_context, seed_context])
    mock_browser.close = AsyncMock()
    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)
    mock_p = MagicMock()
    mock_p.chromium = mock_chromium

    class MockAsyncPlaywrightContext:
        async def __aenter__(self):
            return mock_p
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    async def mock_work_func(context):
        raise SessionHealthError("mymblog 非健康响应: auth_invalid")

    with patch("src.tools.playwright_base.async_playwright", return_value=MockAsyncPlaywrightContext()), \
         patch.object(scraper, "_check_state_cookies_expired", return_value=False), \
         patch.object(scraper, "update_seed_cookies") as mock_update_seed:
        result = await scraper.scrape_flow_handler(mock_work_func)

    assert result == []
    state_context.storage_state.assert_not_called()
    seed_context.storage_state.assert_not_called()
    mock_update_seed.assert_not_called()


def test_update_seed_cookies_formats(tmp_path):
    """测试 update_seed_cookies 方法在面对不同的原始种子格式时，能以对应的格式回写"""
    scraper = XhsScraper()
    test_cookies = [
        {"name": "foo", "value": "bar", "domain": ".xiaohongshu.com", "path": "/"},
        {"name": "hello", "value": "world", "domain": ".xiaohongshu.com", "path": "/"}
    ]
    
    # 格式 A: 标准 JSON List
    seed_a = tmp_path / "seed_a.json"
    seed_a.write_text("[]", encoding="utf-8")
    scraper.seed_file = seed_a
    scraper.update_seed_cookies(test_cookies)
    
    # 验证是否写入了标准的 JSON list
    with open(seed_a, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["name"] == "foo"
    
    # 格式 B: 外部双引号包裹的 JSON 字符串
    seed_b = tmp_path / "seed_b.json"
    seed_b.write_text('"foo=old; hello=old"', encoding="utf-8")
    scraper.seed_file = seed_b
    scraper.update_seed_cookies(test_cookies)
    
    # 验证是否写入了带转义双引号包裹的字符串
    with open(seed_b, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, str)
    assert "foo=bar" in data
    assert "hello=world" in data

    # 格式 C: 纯文本 raw 格式
    seed_c = tmp_path / "seed_c.txt"
    seed_c.write_text("foo=old; hello=old", encoding="utf-8")
    scraper.seed_file = seed_c
    scraper.update_seed_cookies(test_cookies)
    
    # 验证是否写入了纯文本
    content = seed_c.read_text(encoding="utf-8").strip()
    assert content == "foo=bar; hello=world"


# ==============================================================================
# 集成测试：Coser Bio 自适应版本控制递增与分析状态置零闭环
# ==============================================================================
def test_bio_db_version_control():
    # 1. 注册测试 Coser
    assert DBService.add_coser("测试Coser_Bio", weibo_uid="1923024604") is True
    cosers = DBService.list_cosers()
    coser_id = next(c["id"] for c in cosers if c["name"] == "测试Coser_Bio")
    
    # 2. 模拟首次抓取到的 Bio
    posts_v1 = [{
        "post_id": "bio_1923024604",
        "content": "[个人简介] 行程安排：6月1日广州萤火虫展台。",
        "post_url": "https://weibo.com/u/1923024604",
        "edit_count": 0,
        "published_at": "2026-06-02 20:00:00"
    }]
    
    # 执行保存，应该是首次插入
    inserted_v1 = DBService.save_raw_posts(coser_id, "weibo", posts_v1)
    assert inserted_v1 == 1
    
    # 验证数据库中已插入成功，且 post_id 为原始 "bio_1923024604"，edit_count = 0，is_analyzed = 0
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT post_id, edit_count, content, is_analyzed FROM raw_posts WHERE coser_id = ?;", (coser_id,))
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "bio_1923024604"
    assert rows[0][1] == 0
    assert rows[0][3] == 0
    conn.close()
    
    # 3. 模拟 AI 增量分析，将该行更新为已分析 (is_analyzed = 1)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE raw_posts SET is_analyzed = 1 WHERE coser_id = ?;", (coser_id,))
    conn.commit()
    conn.close()
    
    # 4. 再次抓取，Bio 未发生变动
    inserted_dup = DBService.save_raw_posts(coser_id, "weibo", posts_v1)
    # 应被去重过滤，不进行任何修改或插入
    assert inserted_dup == 0
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM raw_posts WHERE coser_id = ?;", (coser_id,))
    assert len(cursor.fetchall()) == 1
    conn.close()

    # 5. 再次抓取，Coser 更新了个人简介（行程已更改）
    posts_v2 = [{
        "post_id": "bio_1923024604",
        "content": "[个人简介] 行程安排：已取消广州萤火虫，改为6月10日上海CP30。",
        "post_url": "https://weibo.com/u/1923024604",
        "edit_count": 0,
        "published_at": "2026-06-03 10:00:00"
    }]
    
    inserted_v2 = DBService.save_raw_posts(coser_id, "weibo", posts_v2)
    assert inserted_v2 == 1
    
    # 验证生成了全新的物理新版本，post_id 为 "bio_1923024604#v1"，edit_count = 1，is_analyzed = 0 完美重置
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT post_id, edit_count, content, is_analyzed FROM raw_posts WHERE coser_id = ? ORDER BY edit_count ASC;", (coser_id,))
    rows = cursor.fetchall()
    assert len(rows) == 2
    
    # 原始 v1 版本保持不变
    assert rows[0][0] == "bio_1923024604"
    assert rows[0][1] == 0
    assert rows[0][3] == 1 # 依然是已分析状态
    
    # 新生成的 v2 物理版本
    assert rows[1][0] == "bio_1923024604#v1"
    assert rows[1][1] == 1
    assert "上海CP30" in rows[1][2]
    assert rows[1][3] == 0 # 自动重置为 0，以便增量引擎能够将其捕获！
    conn.close()


# ==============================================================================
# 单元测试：B站 gRPC Token 自动检测、自愈刷新与持久化配置自更新
# ==============================================================================
@pytest.mark.asyncio
async def test_bilibili_grpc_token_auto_refresh(tmp_path):
    scraper = BilibiliScraper()
    
    # 1. 模拟一个临时的 .env 配置文件，初始为过期 Token 和注释的 refresh_token
    temp_dotenv = tmp_path / ".env"
    temp_dotenv.write_text(
        "BILIBILI_ACCESS_TOKEN=old_expired_access_token_123\n"
        "# BILIBILI_REFRESH_TOKEN=old_refresh_token_456\n"
        "BILIBILI_MID=3546926995737116\n",
        encoding="utf-8"
    )
    
    # 2. 覆盖 settings 中的凭据为旧凭证
    original_access = settings.bilibili_grpc_access_token
    original_refresh = settings.bilibili_grpc_refresh_token
    settings.bilibili_grpc_access_token = "old_expired_access_token_123"
    settings.bilibili_grpc_refresh_token = "old_refresh_token_456"
    
    # 重写 _update_dotenv 指向我们临时的 .env 文件，以完整测试正则替换和解除注释逻辑
    def test_update_dotenv(access_token, refresh_token):
        import re
        content = temp_dotenv.read_text(encoding="utf-8")
        if "BILIBILI_ACCESS_TOKEN" in content:
            content = re.sub(
                r"^BILIBILI_ACCESS_TOKEN\s*=.*$",
                f"BILIBILI_ACCESS_TOKEN={access_token}",
                content,
                flags=re.MULTILINE
            )
        if "BILIBILI_REFRESH_TOKEN" in content:
            content = re.sub(
                r"^#?\s*BILIBILI_REFRESH_TOKEN\s*=.*$",
                f"BILIBILI_REFRESH_TOKEN={refresh_token}",
                content,
                flags=re.MULTILINE
            )
        temp_dotenv.write_text(content, encoding="utf-8")
        
    scraper._update_dotenv = test_update_dotenv

    # 3. 模拟 B站 Token 刷新接口成功的 JSON 响应
    mock_refresh_response = {
        "code": 0,
        "message": "0",
        "ttl": 1,
        "data": {
            "access_token": "brand_new_access_token_789",
            "refresh_token": "brand_new_refresh_token_abc",
            "expires_in": 15552000,
            "mid": 3546926995737116
        }
    }
    
    # 4. 模拟 gRPC 首次调用由于 Token 过期报错，第二次重试调用成功的机制
    call_count = 0
    mock_posts = [{"post_id": "12345", "content": "测试动态", "published_at": "2026-06-03 10:00:00"}]
    
    async def mock_grpc_internal(uid, limit):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 模拟 gRPC 报错 RpcError -101 (账号未登录/Token过期)
            class MockRpcError(grpc.RpcError):
                def code(self):
                    return grpc.StatusCode.UNAUTHENTICATED
                def __str__(self):
                    return "RpcError: code = -101, message = identify_v1 signature invalid"
            raise MockRpcError()
        # 第二次重试成功返回
        return mock_posts

    # 5. Patch 底层接口和 HTTP 刷新接口
    with patch.object(scraper, "_fetch_bilibili_posts_grpc_internal", side_effect=mock_grpc_internal), \
         patch("requests.post") as mock_post:
         
        mock_http_resp = MagicMock()
        mock_http_resp.status_code = 200
        mock_http_resp.json.return_value = mock_refresh_response
        mock_post.return_value = mock_http_resp
        
        # 6. 执行 gRPC 抓取（支持自愈刷新）
        res = await scraper.fetch_bilibili_posts_grpc("3546926995737116", 5)
        
        # 7. 各种核心自愈断言验证
        assert res == mock_posts
        assert call_count == 2  # 成功触发了 1 次过期报错 + 1 次成功重试
        
        # 验证 settings 内存值已被热更新
        assert settings.bilibili_grpc_access_token == "brand_new_access_token_789"
        assert settings.bilibili_grpc_refresh_token == "brand_new_refresh_token_abc"
        
        # 验证物理 .env 文件已被热重写，且 refresh_token 已成功解除注释！
        env_content = temp_dotenv.read_text(encoding="utf-8")
        assert "BILIBILI_ACCESS_TOKEN=brand_new_access_token_789" in env_content
        assert "BILIBILI_REFRESH_TOKEN=brand_new_refresh_token_abc" in env_content
        assert "# BILIBILI_REFRESH_TOKEN" not in env_content  # 被成功解除注释并激活！
        
    # 8. 恢复原来的 settings 变量
    settings.bilibili_grpc_access_token = original_access
    settings.bilibili_grpc_refresh_token = original_refresh
