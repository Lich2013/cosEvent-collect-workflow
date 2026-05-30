import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import datetime
from unittest.mock import patch, MagicMock
import grpc
from src.tools.bilibili_scraper import BilibiliScraper
from src.config import settings

def test_parse_bili_ptime_absolute_with_year():
    # 测试有完整年份的绝对时间解析
    is_edited, parsed_time = BilibiliScraper._parse_bili_ptime("编辑于 2026年5月25日 04:05")
    assert is_edited is True
    assert parsed_time == "2026-05-25 04:05:00"

    is_edited, parsed_time = BilibiliScraper._parse_bili_ptime("2024年4月23日")
    assert is_edited is False
    assert parsed_time == "2024-04-23 00:00:00"

    is_edited, parsed_time = BilibiliScraper._parse_bili_ptime("2025-04-12 12:30:15")
    assert is_edited is False
    assert parsed_time == "2025-04-12 12:30:15"



def test_parse_bili_ptime_absolute_no_year():
    # 测试没有年份的绝对时间解析，验证年份智能补齐与向前推算
    beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(beijing_tz)
    
    # 模拟未来日期：如果当前是 5 月，解析 12月25日，应该算作去年的 12月25日
    future_month = 12 if now.month <= 6 else (now.month - 2)
    # 构造一个肯定在未来的相对月份日期
    label = f"{future_month}月25日 10:00"
    is_edited, parsed_time = BilibiliScraper._parse_bili_ptime(label)
    assert is_edited is False
    
    # 解析年份应该是去年或者是今年
    parsed_dt = datetime.datetime.strptime(parsed_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=beijing_tz)
    assert parsed_dt <= now + datetime.timedelta(hours=1)


def test_parse_bili_ptime_relative():
    # 测试相对时间解析
    beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(beijing_tz)

    is_edited, parsed_time = BilibiliScraper._parse_bili_ptime("昨天 04:05")
    assert is_edited is False
    parsed_dt = datetime.datetime.strptime(parsed_time, "%Y-%m-%d %H:%M:%S")
    expected_dt = now - datetime.timedelta(days=1)
    assert parsed_dt.day == expected_dt.day
    assert parsed_dt.hour == 4
    assert parsed_dt.minute == 5

    is_edited, parsed_time = BilibiliScraper._parse_bili_ptime("编辑于 刚刚")
    assert is_edited is True
    parsed_dt = datetime.datetime.strptime(parsed_time, "%Y-%m-%d %H:%M:%S")
    assert (now.replace(tzinfo=None) - parsed_dt).total_seconds() < 5


@pytest.mark.asyncio
async def test_fetch_bilibili_posts_fallback_on_grpc_error():
    # 测试在 gRPC 鉴权/通信出错时，BilibiliScraper 能够零崩溃静默降级为 Playwright 网页抓取
    scraper = BilibiliScraper()
    
    # Mock settings 使得凭证存在，从而触发 gRPC 分支
    with patch.object(settings, "bilibili_grpc_access_token", "fake_token"), \
         patch.object(settings, "bilibili_grpc_mid", 123456):
         
        # Mock fetch_bilibili_posts_grpc 抛出 RpcError 异常
        def mock_grpc_error(*args, **kwargs):
            raise grpc.RpcError("Auth expired")
            
        with patch.object(scraper, "fetch_bilibili_posts_grpc", side_effect=mock_grpc_error) as mock_grpc, \
             patch.object(scraper, "_fetch_bilibili_posts_playwright", return_value=[{"post_id": "playwright_1", "content": "fallback text"}]) as mock_playwright:
             
            posts = await scraper.fetch_bilibili_posts("1574624", limit=3)
            
            # 确认 gRPC 被调用了，且失败了
            mock_grpc.assert_called_once()
            # 确认 Playwright 降级流程被成功触发并返回结果
            mock_playwright.assert_called_once()
            assert len(posts) == 1
            assert posts[0]["post_id"] == "playwright_1"
