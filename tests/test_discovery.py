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
def setup_test_db(tmp_path):
    """测试用例级数据库自动隔离与重构"""
    db_file = tmp_path / "test_discovery.db"
    settings.db_path = str(db_file)
    init_db()
    yield
    if db_file.exists():
        db_file.unlink()

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
        pending = DBService.list_candidates("pending")
        assert len(pending) == 1
        assert pending[0]["name"] == "小红帽_cos"
        assert pending[0]["matched_bili_uid"] == "999888"
        assert pending[0]["match_score"] > 0.0
