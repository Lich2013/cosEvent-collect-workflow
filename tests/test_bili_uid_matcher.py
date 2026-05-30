import pytest
import os
import sys
sys.path.insert(0, os.getcwd())

from src.services.bili_uid_matcher import BiliUidMatcher

def test_exact_name_match():
    """测试精确昵称匹配，无任何干扰"""
    weibo_name = "横川是川崽"
    search_results = [
        {
            "uname": "横川是川崽",
            "mid": "7346295847",
            "fans": 100000,
            "official_verify": {"type": 0, "desc": "动漫博主"}
        }
    ]
    res = BiliUidMatcher.match_coser(weibo_name, search_results)
    assert res["best_match"] is not None
    assert res["best_match"]["mid"] == "7346295847"
    assert res["best_match"]["uname"] == "横川是川崽"
    # 得分：名称(50) + 粉丝log10(5)*5(25) + 认证(20) = 95
    assert res["score"] == 95.0

def test_substring_and_fuzzy_name_match():
    """测试包含前缀、后缀或部分符号差异的模糊匹配分值"""
    weibo_name = "杜杜Dolly_"
    search_results = [
        {
            "uname": "杜杜Dolly", # 缺少下划线
            "mid": "1963850420",
            "fans": 50000,
            "official_verify": {"type": -1, "desc": ""}
        }
    ]
    res = BiliUidMatcher.match_coser(weibo_name, search_results)
    assert res["best_match"] is not None
    assert res["best_match"]["mid"] == "1963850420"
    # 标准化后名称完全一致："杜杜dolly" vs "杜杜dolly"，得分应依然为 50.0 (精确匹配分)
    assert res["best_match"]["scores"]["name"] == 50.0

def test_impersonator_and_low_followers_cutoff():
    """测试粉丝数量硬阈值防护与高仿低分号过滤"""
    weibo_name = "横川是川崽"
    search_results = [
        {
            "uname": "横川是川崽",
            "mid": "fake_uid_1",
            "fans": 12,  # 低粉小号
            "official_verify": {"type": -1, "desc": ""}
        },
        {
            "uname": "横川是川崽",
            "mid": "7346295847",  # 真实大号
            "fans": 145000,
            "official_verify": {"type": 0, "desc": "B站认证Coser"}
        }
    ]
    res = BiliUidMatcher.match_coser(weibo_name, search_results)
    assert res["best_match"] is not None
    assert res["best_match"]["mid"] == "7346295847"
    
    # 验证低粉小号虽名字匹配，但在 candidates 里的总分由于粉丝和认证极低且不满足 fans >= 100 无法当选 best_match
    candidates_map = {c["mid"]: c for c in res["candidates"]}
    assert candidates_map["fake_uid_1"]["scores"]["total"] < 60.0

def test_completely_mismatched_names():
    """测试名称完全不匹配的过滤"""
    weibo_name = "沐哲MuZZZ"
    search_results = [
        {
            "uname": "路人甲乙丙",
            "mid": "999999",
            "fans": 10000,
            "official_verify": {"type": -1, "desc": ""}
        }
    ]
    res = BiliUidMatcher.match_coser(weibo_name, search_results)
    assert res["best_match"] is None
    assert len(res["candidates"]) == 0

def test_threshold_confidence_filtering():
    """测试置信度得分低于阈值的拦截"""
    weibo_name = "无风霖鹿"
    search_results = [
        {
            "uname": "无风霖鹿",
            "mid": "2110727454",
            "fans": 5, # 极少粉丝且无认证，虽然名字一致，但总分较低
            "official_verify": {"type": -1, "desc": ""}
        }
    ]
    # 默认置信度为 50
    res = BiliUidMatcher.match_coser(weibo_name, search_results, confidence_threshold=60.0)
    # 得分：名字(50) + 粉丝log10(5)*5(~3.5) = ~53.5，低于自定义的 60.0 阈值，应返回 None
    assert res["best_match"] is None
    assert len(res["candidates"]) == 1

def test_social_bio_cross_verify():
    """测试签名档(Bio)含有微博昵称的社交网络互链交叉打分与精确锁定"""
    weibo_name = "横川是川崽"
    search_results = [
        {
            "uname": "川崽川崽", # 名字不一致 (name_score = 0)
            "mid": "7346295847",
            "fans": 50000,
            "usign": "合作私信，微博：@横川是川崽",  # 含有微博账号标识 (+40.0)
            "official_verify": {"type": 0, "desc": "知名UP主"}
        }
    ]
    res = BiliUidMatcher.match_coser(weibo_name, search_results)
    assert res["best_match"] is not None
    assert res["best_match"]["mid"] == "7346295847"
    # 总分：名字(0) + 粉丝log10(50000)*5(23.49) + 认证(20) + 社交互链(40) = 83.49
    assert res["score"] == 83.49

def test_green_channel_for_young_coser():
    """测试名门萌新绿色通道：精准重名并且有官方认证的新人，无视 fans >= 100 限制"""
    weibo_name = "盐桃佑鸟"
    search_results = [
        {
            "uname": "盐桃佑鸟",
            "mid": "3539494804",
            "fans": 30,  # 新人号，粉丝极低 (< 100)
            "official_verify": {"type": 0, "desc": "B站认证Coser"} # 有官方认证
        }
    ]
    res = BiliUidMatcher.match_coser(weibo_name, search_results)
    # 虽然粉丝数 < 100，但由于满足 精准重名(50) + 认证(20) 的绿色免检通道，应该成功绑定！
    assert res["best_match"] is not None
    assert res["best_match"]["mid"] == "3539494804"


@pytest.mark.asyncio
async def test_bilibili_scraper_adaptive_dom_parser():
    """测试 BilibiliScraper 在接口超时降级为 DOM 时，能够使用新型 HTML 自适应提取 UID 昵称粉丝及简介"""
    from src.tools.bilibili_scraper import BilibiliScraper
    from unittest.mock import AsyncMock, MagicMock, patch

    scraper = BilibiliScraper()
    
    # 模拟 HTML 节点：
    # 1. 链接：<a class="text1 p_relative" href="//space.bilibili.com/1526435" title="横川是川崽耶">横川是川崽耶</a>
    # 2. 粉丝段落：<p class="b_text fs_5 text2 text_ellipsis" title="5.8万粉丝 · 39个视频  吉尼斯纪录最小心眼保持者">...
    mock_item = AsyncMock()
    
    # Mock a[href*='space.bilibili.com']
    mock_link = AsyncMock()
    mock_link.inner_text = AsyncMock(return_value="横川是川崽耶")
    mock_link.get_attribute = AsyncMock(return_value="//space.bilibili.com/1526435")
    
    # Mock p:has-text('粉丝')
    mock_p = AsyncMock()
    mock_p.get_attribute = AsyncMock(return_value="5.8万粉丝 · 39个视频  吉尼斯纪录最小心眼保持者")
    mock_p.inner_text = AsyncMock(return_value="5.8万粉丝 · 39个视频  吉尼斯纪录最小心眼保持者")
    
    # Mock span inside p
    mock_span = AsyncMock()
    mock_span.inner_text = AsyncMock(return_value="吉尼斯纪录最小心眼保持者")
    mock_p.query_selector = AsyncMock(return_value=mock_span)
    
    # Card queries dispatching
    async def mock_query_selector(selector):
        if "space.bilibili.com" in selector:
            return mock_link
        if "粉丝" in selector:
            return mock_p
        return None
        
    mock_item.query_selector = AsyncMock(side_effect=mock_query_selector)

    # Scrape flow simulation
    async def mock_scrape_flow(work_func, *args, **kwargs):
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.new_page.return_value = mock_page
        
        # 强制 expect_response 抛出 TimeoutError 以激活 DOM fallback 分支
        mock_page.expect_response = MagicMock(side_effect=Exception("API Timeout"))
        
        # DOM selector for cards returns our mocked card
        mock_page.query_selector_all = AsyncMock(return_value=[mock_item])
        
        return await work_func(mock_context, *args, **kwargs)

    with patch.object(scraper, "scrape_flow_handler", new=mock_scrape_flow):
        # 1. 测试单条查询
        candidates = await scraper.search_bilibili_user("横川是川崽")
        
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["uname"] == "横川是川崽耶"
    assert cand["mid"] == "1526435"
    assert cand["fans"] == 58000
    assert cand["usign"] == "吉尼斯纪录最小心眼保持者"
    assert cand["official_verify"]["desc"] == ""
    
    # 2. 测试批量查询
    with patch.object(scraper, "scrape_flow_handler", new=mock_scrape_flow):
        batch_results = await scraper.search_bilibili_users_batch(["横川是川崽"])
        
    assert "横川是川崽" in batch_results
    batch_candidates = batch_results["横川是川崽"]
    assert len(batch_candidates) == 1
    batch_cand = batch_candidates[0]
    assert batch_cand["uname"] == "横川是川崽耶"
    assert batch_cand["mid"] == "1526435"
    assert batch_cand["fans"] == 58000
    assert batch_cand["usign"] == "吉尼斯纪录最小心眼保持者"
    assert batch_cand["official_verify"]["desc"] == ""


