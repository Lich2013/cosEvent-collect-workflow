import sys
import os
sys.path.insert(0, os.getcwd())

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.services.discovery_service import DiscoveryService
from src.tools.bilibili_scraper import BilibiliScraper
from src.services.db_service import DBService
from src.models.db_models import init_db
from src.config import settings

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """测试用例级数据库自动隔离"""
    db_file = tmp_path / "test_bili_space_res.db"
    original_db = settings.db_path
    settings.db_path = str(db_file)
    init_db()
    yield
    if db_file.exists():
        db_file.unlink()
    settings.db_path = original_db

def test_register_candidates_with_mentions():
    """测试 register_candidates_from_posts 优先提取 mentions 中的 pre-bound UID"""
    posts = [
        {
            "content": "和 @池咲misa 贴贴！",
            "post_url": "http://bili.com/dynamic/123",
            "platform": "bilibili",
            "mentions": [
                {"name": "池咲misa", "uid": "987654321"}
            ]
        }
    ]
    
    registered = DiscoveryService.register_candidates_from_posts(posts)
    assert registered == 1
    
    candidates = DBService.list_candidates("pending")
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["name"] == "池咲misa"
    assert cand["matched_bili_uid"] == "987654321"
    assert cand["is_verified"] == 0

@pytest.mark.asyncio
async def test_verify_pending_candidates_bypass_search():
    """测试 verify_pending_candidates 对于已绑定 UID 的候选人，绕过 B站 搜索"""
    # 1. 注册一个已经有 B站 UID 的 pending 候选人
    DBService.add_candidate(
        name="池咲misa",
        platform="bilibili",
        source_ref="http://bili.com/dynamic/123",
        matched_bili_uid="987654321"
    )
    
    # 2. 模拟 B站 空间解析返回 (包含 coser 签名以通过属性校验)
    mock_profiles = {
        "987654321": {
            "uname": "池咲misa",
            "bio": "专业coser，合作私信",
            "verify_desc": ""
        }
    }
    
    with patch("src.tools.bilibili_scraper.BilibiliScraper.search_bilibili_users_batch", new_callable=AsyncMock) as mock_search, \
         patch("src.tools.bilibili_scraper.BilibiliScraper.resolve_uids_batch", new_callable=AsyncMock) as mock_resolve:
         
        mock_resolve.return_value = mock_profiles
        
        # 运行验证
        verified_count = await DiscoveryService.verify_pending_candidates(limit=5)
        
        # 验证成功的数量
        assert verified_count == 1
        
        # 搜索接口不应被调用 (因为有 pre-bound UID)
        mock_search.assert_not_called()
        
        # 空间解析接口应该被调用
        mock_resolve.assert_called_once_with(["987654321"])
        
        # 检查候选人是否被成功标记为 verified=1 且 UID 保持不变
        candidates = DBService.list_candidates("approved")
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["matched_bili_uid"] == "987654321"
        assert cand["is_verified"] == 1

@pytest.mark.asyncio
async def test_verify_pending_candidates_combined_validation():
    """测试 verify_pending_candidates 的双重/合并属性验证 (Weibo Bio 与 B站 Bio)"""
    # 1. 注册一个没有 UID 且来自微博的候选人
    DBService.add_candidate(
        name="极简日程Coser_cos",
        platform="weibo",
        source_ref="http://weibo.com/123"
    )
    
    # 2. 模拟微博解析返回结果 (无 coser 关键字，微博 Bio 不通过)
    mock_weibo_user = {
        "idstr": "222333",
        "screen_name": "极简日程Coser_cos",
        "description": "摄影爱好者"
    }
    
    # 3. 模拟 B站 搜索匹配出一个 UID 999111
    mock_bili_results = {
        "极简日程Coser": [
            {
                "uname": "极简日程Coser",
                "mid": 999111,
                "fans": 12000,
                "official_verify": {"type": -1, "desc": ""},
                "usign": "主要发cosplay日常"  # 包含二次元关键词
            }
        ]
    }
    
    # 4. 模拟 B站 空间解析返回完整 Bio
    mock_bili_profile = {
        "999111": {
            "uname": "极简日程Coser",
            "bio": "是一个普通的二次元coser",
            "verify_desc": ""
        }
    }
    
    with patch("src.tools.weibo_scraper.WeiboScraper.resolve_screen_names_batch", new_callable=AsyncMock) as mock_weibo_resolve, \
         patch("src.tools.bilibili_scraper.BilibiliScraper.search_bilibili_users_batch", new_callable=AsyncMock) as mock_bili_search, \
         patch("src.tools.bilibili_scraper.BilibiliScraper.resolve_uids_batch", new_callable=AsyncMock) as mock_bili_resolve:
         
        mock_weibo_resolve.return_value = {"极简日程Coser_cos": mock_weibo_user}
        mock_bili_search.return_value = mock_bili_results
        mock_bili_resolve.return_value = mock_bili_profile
        
        # 运行验证
        verified_count = await DiscoveryService.verify_pending_candidates(limit=5)
        
        # 虽然微博 Bio 不含二次元关键字，但 B站 空间 Bio 通过了属性校验，所以成功验证
        assert verified_count == 1
        
        # 校验数据库更新
        candidates = DBService.list_candidates("approved")
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["matched_weibo_uid"] == "222333"
        assert cand["matched_bili_uid"] == "999111"
        assert cand["is_verified"] == 1
