import os
import sys
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

# 确保项目根目录在 python 搜索路径中
sys.path.insert(0, os.getcwd())

from src.models.db_models import init_db, get_db_connection
from src.services.db_service import DBService
from src.config import settings
from src.services.workflow_orchestrator import WorkflowOrchestrator

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

def test_sliding_window_scheduling_and_rotation():
    """测试从未爬取到已爬取的排序与轮转变化"""
    # 1. 注册 3 个活跃 Coser
    assert DBService.add_coser("CoserA", bilibili_uid="bili_a", weibo_uid="weibo_a") is True
    assert DBService.add_coser("CoserB", bilibili_uid="bili_b", weibo_uid="weibo_b") is True
    assert DBService.add_coser("CoserC", bilibili_uid="bili_c", weibo_uid="weibo_c") is True

    # 2. 以 batch 限制为 2 获取队列
    batch = DBService.list_active_cosers_by_schedule("bilibili", 2)
    assert len(batch) == 2
    # 此时没有任何爬取时间戳，排序将优先选择 NULL，且默认按 rowid/创建时间 升序
    names = [c["name"] for c in batch]
    assert "CoserA" in names
    assert "CoserB" in names
    assert "CoserC" not in names

    # 3. 更新 CoserA 的爬取时间戳
    coser_a = [c for c in batch if c["name"] == "CoserA"][0]
    assert DBService.update_scrape_timestamp(coser_a["id"], "bilibili") is True

    # 4. 再次获取 batch 限制为 2 的队列
    # 由于 CoserA 已经有时间戳，它应该被旋转到队尾，新队列应该是 CoserB 和 CoserC
    batch_after = DBService.list_active_cosers_by_schedule("bilibili", 2)
    assert len(batch_after) == 2
    names_after = [c["name"] for c in batch_after]
    assert "CoserB" in names_after
    assert "CoserC" in names_after
    assert "CoserA" not in names_after

    # 5. 获取全部 3 个，CoserA 应排在最后
    batch_all = DBService.list_active_cosers_by_schedule("bilibili", 3)
    assert len(batch_all) == 3
    assert batch_all[2]["name"] == "CoserA"


def test_coser_last_scraped_at_update_and_cleanup():
    """测试 cosers 表中 last_scraped_at 字段的更新与清理"""
    # 1. 注册一个 Coser
    assert DBService.add_coser("CoserToDelete", bilibili_uid="bili_del") is True
    cosers = DBService.list_cosers()
    coser = [c for c in cosers if c["name"] == "CoserToDelete"][0]
    coser_id = coser["id"]
    
    # 验证初始 last_scraped_at 为 None
    assert coser.get("last_scraped_at") is None

    # 2. 写入平台时间戳状态记录
    assert DBService.update_scrape_timestamp(coser_id, "bilibili") is True

    # 验证此时状态记录存在且已更新
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT last_scraped_at FROM cosers WHERE id = ?;", (coser_id,))
    val = cursor.fetchone()[0]
    assert val is not None
    conn.close()

    # 3. 物理删除该 Coser
    assert DBService.delete_coser("CoserToDelete") is True

    # 验证该 Coser 在 cosers 表中已不复存在
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM cosers WHERE id = ?;", (coser_id,))
    assert cursor.fetchone()[0] == 0
    conn.close()


def test_xhs_cooldown_filters_scheduled_accounts():
    """小红书 next_retry_after 未到期时不应进入调度队列，到期后恢复。"""
    assert DBService.add_coser("XhsCooldown", xhs_uid="xhs_cooldown") is True
    coser = [c for c in DBService.list_cosers() if c["name"] == "XhsCooldown"][0]

    assert DBService.update_scrape_timestamp(coser["id"], "xhs", status="rate_limited", error="访问频繁") is True
    assert DBService.list_active_cosers_by_schedule("xhs", 10) == []

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE coser_scrape_state SET next_retry_after = ? WHERE coser_id = ? AND platform = 'xhs';",
        ("2000-01-01 00:00:00", coser["id"])
    )
    conn.commit()
    conn.close()

    batch = DBService.list_active_cosers_by_schedule("xhs", 10)
    assert [c["name"] for c in batch] == ["XhsCooldown"]


@pytest.mark.asyncio
async def test_scrape_failure_still_updates_timestamp():
    """测试当抓取抛出异常时，时间戳是否仍能够正常更新落盘"""
    # 1. 注册一个 Coser 并验证状态记录初始不存在
    assert DBService.add_coser("CoserFailTest", bilibili_uid="bili_fail") is True
    cosers = DBService.list_cosers()
    coser_id = [c["id"] for c in cosers if c["name"] == "CoserFailTest"][0]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT last_scraped_at FROM cosers WHERE id = ?;", (coser_id,))
    assert cursor.fetchone()[0] is None
    conn.close()

    # 2. Mock 异常情况下的 BilibiliScraper
    with patch("src.services.workflow_orchestrator.BilibiliScraper") as mock_bili_class:
        mock_bili = MagicMock()
        # 强制抛出异常以模拟网络或者风控崩溃
        mock_bili.fetch_bilibili_posts = AsyncMock(side_effect=Exception("Bilibili connection refused (mocked)"))
        mock_bili_class.return_value = mock_bili

        # 执行 run_scrape 抓取，平台指定为 bilibili
        total_cosers, success_platforms, total_inserted = await WorkflowOrchestrator.run_scrape(
            limit=5, platform="bilibili", batch_size=1
        )

        assert total_cosers == 1
        assert success_platforms["bilibili"]["total"] == 1
        assert success_platforms["bilibili"]["success"] == 0  # 爬取标记为失败
        assert total_inserted == 0

    # 3. 检查数据库，验证 last_scraped_at 即使在异常情况下也被成功插入/更新
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT last_scraped_at FROM cosers WHERE id = ?;", (coser_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] is not None
    conn.close()


@pytest.mark.asyncio
async def test_ticket_lock_concurrency():
    """测试多协程并发获取或刷新 ticket 时的锁隔离性，防止网络请求刷爆"""
    from src.tools.bilibili_scraper import BilibiliScraper
    scraper = BilibiliScraper()
    
    # 阻断 .env 物理写入
    scraper._update_dotenv_ticket = MagicMock()
    
    call_count = 0
    async def mock_post_ticket(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)  # 模拟网络调用延迟
        return {
            "code": 0,
            "data": {
                "ticket": f"mocked_ticket_{call_count}",
                "ttl": 259200
            }
        }
    
    with patch("src.tools.bilibili_scraper.asyncio.to_thread", side_effect=mock_post_ticket):
        # 清理配置缓存
        settings.bilibili_grpc_ticket = ""
        settings.bilibili_grpc_ticket_expires_at = 0
        
        # 同时发起 3 个强制刷新的申请请求
        tasks = [
            scraper._get_valid_bili_ticket(force_refresh=True),
            scraper._get_valid_bili_ticket(force_refresh=True),
            scraper._get_valid_bili_ticket(force_refresh=True)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # 验证仅有一个真正的 GenWebTicket 网络请求被派发，其余被 Lock 隔离并直接复用了最新结果
        assert call_count == 1
        assert len(set(results)) == 1
        assert results[0] == "mocked_ticket_1"


@pytest.mark.asyncio
async def test_round_robin_batch_limit():
    """测试多平台模式下的去重后的 batch_size 总量限制与负载分发"""
    # 1. 注册 3 个具有不同平台 UID 的 Coser
    assert DBService.add_coser("CoserA", weibo_uid="weibo_a", bilibili_uid="bili_a") is True
    assert DBService.add_coser("CoserB", bilibili_uid="bili_b") is True
    assert DBService.add_coser("CoserC", weibo_uid="weibo_c") is True

    weibo_scraped = []
    bili_scraped = []

    async def mock_weibo_fetch(uid, limit):
        weibo_scraped.append(uid)
        return []

    async def mock_bili_fetch(uid, limit):
        bili_scraped.append(uid)
        return []

    with patch("src.services.workflow_orchestrator.WeiboScraper") as mock_weibo_class, \
         patch("src.services.workflow_orchestrator.BilibiliScraper") as mock_bili_class:
        
        mock_weibo = MagicMock()
        mock_weibo.fetch_weibo_posts = AsyncMock(side_effect=mock_weibo_fetch)
        mock_weibo_class.return_value = mock_weibo

        mock_bili = MagicMock()
        mock_bili.fetch_bilibili_posts = AsyncMock(side_effect=mock_bili_fetch)
        mock_bili_class.return_value = mock_bili

        # 执行 run_scrape，限制去重后最大 Coser 数量为 2
        total_cosers, success_platforms, total_inserted = await WorkflowOrchestrator.run_scrape(
            limit=5, platform="all", batch_size=2
        )

        # 验证处理的唯一 Coser ID 数总和不超过 2
        assert total_cosers == 2
        # 按全局排序，CoserA 和 CoserB 被选中
        assert "weibo_a" in weibo_scraped
        assert "weibo_c" not in weibo_scraped  # CoserC 没在全局 Top 2 中，不爬取
        # B站队列中，选中的 CoserA 和 CoserB 应该被爬取
        assert "bili_a" in bili_scraped
        assert "bili_b" in bili_scraped
