import os
import sys
import datetime
import pytest
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
    
    mock_resp_posted = MagicMock()
    mock_resp_posted.url = "https://www.xiaohongshu.com/api/sns/web/v1/user_posted?uid=789"
    mock_resp_posted.status = 200
    mock_resp_posted.json = AsyncMock(return_value={"data": {"notes": []}})

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.expect_response = MagicMock(return_value=MockExpectResponseContext(mock_resp_posted))
    
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
