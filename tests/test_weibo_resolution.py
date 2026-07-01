import sys
import os
sys.path.insert(0, os.getcwd())

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.services.discovery_service import DiscoveryService
from src.tools.weibo_scraper import WeiboScraper
from src.services.db_service import DBService
from src.models.db_models import init_db, get_db_connection
from src.config import settings

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """测试用例级数据库自动隔离"""
    db_file = tmp_path / "test_weibo_res.db"
    original_db = settings.db_path
    settings.db_path = str(db_file)
    init_db()
    original_auto_approve = settings.auto_approve_candidates
    settings.auto_approve_candidates = True
    yield
    if db_file.exists():
        db_file.unlink()
    settings.db_path = original_db
    settings.auto_approve_candidates = original_auto_approve

def test_prune_weibo_suffix():
    """验证微博名字后缀清洗逻辑"""
    assert DiscoveryService.prune_weibo_suffix("北川白鸟_ShiratoriK") == "北川白鸟"
    assert DiscoveryService.prune_weibo_suffix("小汐_cos") == "小汐"
    assert DiscoveryService.prune_weibo_suffix("艾西_Coser") == "艾西"
    assert DiscoveryService.prune_weibo_suffix("是橘梓不是橘子") == "是橘梓不是橘子"
    assert DiscoveryService.prune_weibo_suffix("测试下划线_") == "测试下划线"
    assert DiscoveryService.prune_weibo_suffix("") == ""
    assert DiscoveryService.prune_weibo_suffix(None) == ""

@pytest.mark.asyncio
async def test_weibo_scraper_resolve_screen_name():
    """验证 WeiboScraper.resolve_screen_name 解析 AJAX 返回值"""
    scraper = WeiboScraper()
    
    mock_profile_json = {
        "ok": 1,
        "data": {
            "user": {
                "idstr": "7188636063",
                "screen_name": "小沂Alter",
                "description": "是一个不太优秀的普通人_coser"
            }
        }
    }
    
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=mock_profile_json)
    
    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    
    with patch.object(scraper, "scrape_flow_handler") as mock_flow:
        async def side_effect(fn, names):
            return await fn(mock_context, names)
        mock_flow.side_effect = side_effect
        
        user_data = await scraper.resolve_screen_name("小沂Alter")
        
        assert user_data.get("idstr") == "7188636063"
        assert user_data.get("screen_name") == "小沂Alter"
        assert "普通人" in user_data.get("description")

@pytest.mark.asyncio
async def test_verify_pending_candidates_weibo_resolution():
    """验证待对齐候选人通过微博昵称解析对齐并成功的全链路逻辑"""
    # 1. 注册待对齐的微博来源候选人
    DBService.add_candidate(
        name="小沂Alter",
        platform="weibo",
        source_ref="https://weibo.com/3539494804/R2Jwyht2F"
    )
    
    # 2. 模拟微博解析返回结果 (包含二次元关键字 'coser'，以通过 Bio 属性过滤)
    mock_weibo_user = {
        "idstr": "7188636063",
        "screen_name": "小沂Alter",
        "description": "二次元coser"
    }
    
    # B站搜索结果模拟为空 (模拟B站未检索到，但依靠微博Bio直接确权通过的情况)
    mock_bili_results = {}
    
    with patch("src.tools.weibo_scraper.WeiboScraper.resolve_screen_names_batch", new_callable=AsyncMock) as mock_resolve, \
         patch("src.tools.weibo_scraper.WeiboScraper.fetch_weibo_posts", new_callable=AsyncMock) as mock_weibo_posts, \
         patch("src.tools.bilibili_scraper.BilibiliScraper.search_bilibili_users_batch", new_callable=AsyncMock) as mock_bili_search:
         
        mock_resolve.return_value = {"小沂Alter": mock_weibo_user}
        mock_weibo_posts.return_value = []
        mock_bili_search.return_value = mock_bili_results
        
        # 运行验证
        verified_count = await DiscoveryService.verify_pending_candidates(limit=5)
        
        # 即使B站未检索到，因微博 Bio 属性过滤通过，也应成功验证
        assert verified_count == 1
        
        # 校验数据库状态是否更新为通过，且匹配到 weibo_uid，bili_uid 为 None
        candidates = DBService.list_candidates("approved")
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["matched_weibo_uid"] == "7188636063"
        assert cand["matched_bili_uid"] in (None, "")

@pytest.mark.asyncio
async def test_verified_candidates_are_not_re_evaluated():
    """验证已拥有 weibo_uid 或 bili_uid 的候选人不会被重复拉取分析"""
    # 1. 注册并设置一个已经有 weibo_uid 的 pending 候选人
    DBService.add_candidate(
        name="已对齐Coser",
        platform="weibo",
        source_ref="https://weibo.com/3539494804/R2Jwyht2F",
        matched_weibo_uid="7188636063",
        is_verified=1
    )
    
    # 2. 运行验证，此时应该没有待验证的候选人被拉取（即返回 0）
    with patch("src.tools.weibo_scraper.WeiboScraper.resolve_screen_names_batch", new_callable=AsyncMock) as mock_resolve:
        verified_count = await DiscoveryService.verify_pending_candidates(limit=5)
        
        # 确认未处理任何候选人
        assert verified_count == 0
        mock_resolve.assert_not_called()
