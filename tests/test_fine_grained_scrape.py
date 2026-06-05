"""
细粒度抓取过滤测试套件
测试 WorkflowOrchestrator.run_scrape 的 coser_name / platform 过滤行为。
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ACTIVE_COSERS = [
    {
        "id": 1,
        "name": "池咲misa",
        "weibo_uid": "1111",
        "bilibili_uid": "2222",
        "xhs_uid": "3333",
        "is_active": 1,
    },
    {
        "id": 2,
        "name": "北の雪狐",
        "weibo_uid": "4444",
        "bilibili_uid": None,
        "xhs_uid": None,
        "is_active": 1,
    },
]

DUMMY_POSTS = [
    {"post_id": "abc", "content": "测试动态", "post_url": "https://example.com", "edit_count": 0, "published_at": "2026-05-01 10:00:00"}
]


def _make_scraper_mocks():
    """返回三个可 await 的 Scraper 替身"""
    weibo_sc = MagicMock()
    weibo_sc.fetch_weibo_posts = AsyncMock(return_value=DUMMY_POSTS)

    bili_sc = MagicMock()
    bili_sc.fetch_bilibili_posts = AsyncMock(return_value=DUMMY_POSTS)

    xhs_sc = MagicMock()
    xhs_sc.fetch_xhs_posts = AsyncMock(return_value=DUMMY_POSTS)

    return weibo_sc, bili_sc, xhs_sc


# ---------------------------------------------------------------------------
# Helper: run with patched dependencies
# ---------------------------------------------------------------------------

def _run_scrape_patched(cosers_fixture, coser_name=None, platform="all"):
    """统一入口：注入伪 DBService、Scraper 并执行 run_scrape"""
    import asyncio
    from src.services.workflow_orchestrator import WorkflowOrchestrator

    weibo_sc, bili_sc, xhs_sc = _make_scraper_mocks()

    def mock_list_active_cosers_by_schedule(plat, limit, conn=None):
        uid_col = f"{plat}_uid"
        return [
            c for c in cosers_fixture
            if c.get(uid_col) is not None and c.get(uid_col) != '' and c.get(uid_col) != '-'
        ][:limit]

    with patch("src.services.workflow_orchestrator.DBService.list_cosers", return_value=cosers_fixture), \
         patch("src.services.workflow_orchestrator.DBService.list_active_cosers_by_schedule", side_effect=mock_list_active_cosers_by_schedule), \
         patch("src.services.workflow_orchestrator.DBService.update_scrape_timestamp", return_value=True), \
         patch("src.services.workflow_orchestrator.DBService.save_raw_posts", return_value=1), \
         patch("src.services.workflow_orchestrator.WeiboScraper", return_value=weibo_sc), \
         patch("src.services.workflow_orchestrator.BilibiliScraper", return_value=bili_sc), \
         patch("src.services.workflow_orchestrator.XhsScraper", return_value=xhs_sc):
        result = asyncio.run(
            WorkflowOrchestrator.run_scrape(10, coser_name=coser_name, platform=platform)
        )

    return result, weibo_sc, bili_sc, xhs_sc


# ---------------------------------------------------------------------------
# 场景一：无过滤参数 → 全量抓取（向下兼容）
# ---------------------------------------------------------------------------

class TestFullScrapeNoFilter:
    def test_returns_all_cosers_count(self):
        result, *_ = _run_scrape_patched(ACTIVE_COSERS)
        total_cosers, _, total_inserted = result
        assert total_cosers == 2

    def test_all_platforms_attempted(self):
        result, weibo_sc, bili_sc, xhs_sc = _run_scrape_patched(ACTIVE_COSERS)
        # 池咲misa 三平台都有 UID → 三个 scraper 都应被调用
        assert weibo_sc.fetch_weibo_posts.called
        assert bili_sc.fetch_bilibili_posts.called
        assert xhs_sc.fetch_xhs_posts.called

    def test_inserted_count_accumulated(self):
        # 两个 Coser：池咲misa 3平台 + 北の雪狐 只有微博 → 4次成功 save_raw_posts → 4
        result, *_ = _run_scrape_patched(ACTIVE_COSERS)
        _, _, total_inserted = result
        assert total_inserted == 4  # 3 + 1


# ---------------------------------------------------------------------------
# 场景二：coser_name 过滤 → 单点匹配
# ---------------------------------------------------------------------------

class TestCoserNameFilter:
    def test_match_single_coser(self):
        result, weibo_sc, bili_sc, xhs_sc = _run_scrape_patched(ACTIVE_COSERS, coser_name="池咲misa")
        total_cosers, _, _ = result
        assert total_cosers == 1

    def test_only_matched_coser_scraped(self):
        # 仅 "池咲misa" 被爬取，"北の雪狐" 的微博不应被调用第二次
        result, weibo_sc, bili_sc, xhs_sc = _run_scrape_patched(ACTIVE_COSERS, coser_name="池咲misa")
        # fetch_weibo_posts 只应被调用 1 次（北の雪狐被过滤掉）
        assert weibo_sc.fetch_weibo_posts.call_count == 1

    def test_nonexistent_coser_graceful_return(self):
        """传入不存在的姓名 → 返回 (0, {}, 0) 且不崩溃"""
        result, *_ = _run_scrape_patched(ACTIVE_COSERS, coser_name="不存在的Coser")
        assert result == (0, {}, 0)

    def test_nonexistent_coser_no_scraper_called(self):
        """空匹配熔断 → 任何 Scraper 都不应被调用"""
        result, weibo_sc, bili_sc, xhs_sc = _run_scrape_patched(ACTIVE_COSERS, coser_name="不存在的Coser")
        assert not weibo_sc.fetch_weibo_posts.called
        assert not bili_sc.fetch_bilibili_posts.called
        assert not xhs_sc.fetch_xhs_posts.called


# ---------------------------------------------------------------------------
# 场景三：platform 过滤 → 平台旁路
# ---------------------------------------------------------------------------

class TestPlatformFilter:
    def test_bilibili_only_no_weibo_call(self):
        """--platform bilibili → 微博 Scraper 不应被调用"""
        result, weibo_sc, bili_sc, xhs_sc = _run_scrape_patched(ACTIVE_COSERS, platform="bilibili")
        assert not weibo_sc.fetch_weibo_posts.called
        assert not xhs_sc.fetch_xhs_posts.called
        assert bili_sc.fetch_bilibili_posts.called

    def test_weibo_only_no_bili_call(self):
        result, weibo_sc, bili_sc, xhs_sc = _run_scrape_patched(ACTIVE_COSERS, platform="weibo")
        assert weibo_sc.fetch_weibo_posts.called
        assert not bili_sc.fetch_bilibili_posts.called
        assert not xhs_sc.fetch_xhs_posts.called

    def test_xhs_only(self):
        result, weibo_sc, bili_sc, xhs_sc = _run_scrape_patched(ACTIVE_COSERS, platform="xhs")
        assert not weibo_sc.fetch_weibo_posts.called
        assert not bili_sc.fetch_bilibili_posts.called
        assert xhs_sc.fetch_xhs_posts.called

    def test_contract_tuple_shape_with_platform_filter(self):
        """平台过滤时，返回值仍应为三元组且 success_platforms 包含所有三个平台键"""
        result, *_ = _run_scrape_patched(ACTIVE_COSERS, platform="bilibili")
        total_cosers, success_platforms, total_inserted = result
        assert isinstance(total_cosers, int)
        assert isinstance(success_platforms, dict)
        assert "weibo" in success_platforms
        assert "bilibili" in success_platforms
        assert "xhs" in success_platforms
        assert isinstance(total_inserted, int)


# ---------------------------------------------------------------------------
# 场景四：coser_name + platform 联合过滤
# ---------------------------------------------------------------------------

class TestCombinedFilter:
    def test_single_coser_single_platform(self):
        """--name 池咲misa --platform bilibili → 只爬 B站，只爬一人"""
        result, weibo_sc, bili_sc, xhs_sc = _run_scrape_patched(
            ACTIVE_COSERS, coser_name="池咲misa", platform="bilibili"
        )
        total_cosers, _, total_inserted = result
        assert total_cosers == 1
        assert total_inserted == 1
        assert bili_sc.fetch_bilibili_posts.call_count == 1
        assert not weibo_sc.fetch_weibo_posts.called
        assert not xhs_sc.fetch_xhs_posts.called

    def test_single_coser_no_uid_for_platform(self):
        """北の雪狐 没有 B站 UID，--platform bilibili → 0 条入库"""
        result, weibo_sc, bili_sc, xhs_sc = _run_scrape_patched(
            ACTIVE_COSERS, coser_name="北の雪狐", platform="bilibili"
        )
        total_cosers, _, total_inserted = result
        assert total_cosers == 1
        assert total_inserted == 0
        assert not bili_sc.fetch_bilibili_posts.called


# ---------------------------------------------------------------------------
# 场景五：活跃名单为空
# ---------------------------------------------------------------------------

class TestEmptyCoserList:
    def test_empty_db_returns_zero_tuple(self):
        result, *_ = _run_scrape_patched([])
        total_cosers, success_platforms, total_inserted = result
        assert total_cosers == 0
        assert total_inserted == 0
