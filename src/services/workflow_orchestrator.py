import asyncio
import logging
from src.config import settings
from src.services.db_service import DBService
from src.tools.weibo_scraper import WeiboScraper
from src.tools.bilibili_scraper import BilibiliScraper
from src.tools.xhs_scraper import XhsScraper
from src.utils.logger import log_event
from src.models.db_models import get_db_connection

class WorkflowOrchestrator:
    """
    工作流编排器 (Controller)：
    专门处理多源数据抓取、大模型增量提炼分析以及两阶段处理流程的总控与调度逻辑。
    """

    @staticmethod
    async def run_scrape(limit: int = None, coser_name: str = None, platform: str = "all", batch_size: int = None) -> tuple[int, dict, int]:
        """[Scrape Phase] 异步去重抓取活跃 Coser 博文动态并持久化

        Args:
            limit: 单一平台单次爬取动态条数。
            coser_name: 可选，仅抓取该 Coser；None 表示按时间窗口调度。
            platform: 可选，抓取平台（weibo/bilibili/xhs/all）。
            batch_size: 每次调度最大 Coser 数量限制。
        """
        # 默认 batch_size 为 30
        batch_limit = batch_size if batch_size is not None else 30

        # 仅实例化被指定平台的 Scraper，避免其余平台的冷启动
        weibo_sc = WeiboScraper() if platform in ("weibo", "all") else None
        bili_sc = BilibiliScraper() if platform in ("bilibili", "all") else None
        xhs_sc = XhsScraper() if platform in ("xhs", "all") else None

        success_platforms = {
            "weibo": {"success": 0, "total": 0},
            "bilibili": {"success": 0, "total": 0},
            "xhs": {"success": 0, "total": 0}
        }
        total_inserted = 0
        processed_coser_ids = set()

        db_conn = get_db_connection()
        try:
            single_coser_list = []
            if coser_name:
                all_cosers = DBService.list_cosers(only_active=True, conn=db_conn)
                single_coser_list = [c for c in all_cosers if c["name"] == coser_name]
                if not single_coser_list:
                    print(f"\x1b[1;33m[WARNING] 未找到处于激活状态且名为 [{coser_name}] 的 Coser，请确认姓名拼写或启用状态。\x1b[0m")
                    return 0, {}, 0

            target_weibo_cosers = []
            target_bili_cosers = []
            target_xhs_cosers = []

            if coser_name:
                if platform in ("weibo", "all"):
                    target_weibo_cosers = [c for c in single_coser_list if c["weibo_uid"]]
                if platform in ("bilibili", "all"):
                    target_bili_cosers = [c for c in single_coser_list if c["bilibili_uid"]]
                if platform in ("xhs", "all"):
                    target_xhs_cosers = [c for c in single_coser_list if c["xhs_uid"]]
                processed_coser_ids = set(c["id"] for c in single_coser_list)
            else:
                # 统一获取全局最久未爬取的活跃 Coser 队列
                target_cosers = DBService.list_active_cosers_by_schedule(platform, batch_limit, conn=db_conn)
                for c in target_cosers:
                    if platform in ("weibo", "all") and c["weibo_uid"] and c["weibo_uid"] not in ("", "-"):
                        target_weibo_cosers.append(c)
                    if platform in ("bilibili", "all") and c["bilibili_uid"] and c["bilibili_uid"] not in ("", "-"):
                        target_bili_cosers.append(c)
                    if platform in ("xhs", "all") and c["xhs_uid"] and c["xhs_uid"] not in ("", "-"):
                        target_xhs_cosers.append(c)
                    processed_coser_ids.add(c["id"])

            # 1. 微博抓取
            if platform in ("weibo", "all"):
                for c in target_weibo_cosers:
                    processed_coser_ids.add(c["id"])
                    success_platforms["weibo"]["total"] += 1
                    try:
                        posts = await weibo_sc.fetch_weibo_posts(c["weibo_uid"], limit)
                        if posts:
                            ins = DBService.save_raw_posts(c["id"], "weibo", posts, conn=db_conn)
                            total_inserted += ins
                        success_platforms["weibo"]["success"] += 1
                    except Exception as e:
                        log_event("ERROR", "scraper_weibo", f"Coser [{c['name']}] 微博抓取失败: {e}", str(e))
                    finally:
                        DBService.update_scrape_timestamp(c["id"], "weibo", conn=db_conn)

            # 2. B站抓取
            if platform in ("bilibili", "all"):
                for c in target_bili_cosers:
                    processed_coser_ids.add(c["id"])
                    success_platforms["bilibili"]["total"] += 1
                    try:
                        posts = await bili_sc.fetch_bilibili_posts(c["bilibili_uid"], limit)
                        if posts:
                            ins = DBService.save_raw_posts(c["id"], "bilibili", posts, conn=db_conn)
                            total_inserted += ins
                        success_platforms["bilibili"]["success"] += 1
                    except Exception as e:
                        log_event("ERROR", "scraper_bilibili", f"Coser [{c['name']}] B站抓取失败: {e}", str(e))
                    finally:
                        DBService.update_scrape_timestamp(c["id"], "bilibili", conn=db_conn)

            # 3. 小红书抓取
            if platform in ("xhs", "all"):
                for idx, c in enumerate(target_xhs_cosers):
                    if idx > 0:
                        import random
                        delay = random.uniform(7.0, 10.0)
                        print(f"\x1b[1;36m[Orchestrator] 针对小红书数据源进行频控休眠: {delay:.1f}s...\x1b[0m")
                        await asyncio.sleep(delay)
                    processed_coser_ids.add(c["id"])
                    success_platforms["xhs"]["total"] += 1
                    try:
                        posts = await xhs_sc.fetch_xhs_posts(c["xhs_uid"], limit)
                        if posts:
                            ins = DBService.save_raw_posts(c["id"], "xhs", posts, conn=db_conn)
                            total_inserted += ins
                        success_platforms["xhs"]["success"] += 1
                    except Exception as e:
                        log_event("ERROR", "scraper_xhs", f"Coser [{c['name']}] 小红书抓取失败: {e}", str(e))
                    finally:
                        DBService.update_scrape_timestamp(c["id"], "xhs", conn=db_conn)

        finally:
            db_conn.close()

        return len(processed_coser_ids), success_platforms, total_inserted



    @staticmethod
    async def run_analyze(confidence_threshold: float) -> tuple[int, int, int]:
        """[Analyze Phase] 增量式分析未处理博文并原子性提炼活动入库"""
        from src.agents.event_agent import analyze_post_with_retry
        import sqlite3
        
        pending_posts = DBService.get_unanalyzed_posts()
        if not pending_posts:
            return 0, 0, 0
            
        total_posts = len(pending_posts)
        success_events_count = 0
        analyzed_count = 0
        failed_count = 0
        
        for p in pending_posts:
            try:
                # 1. 大模型增量提炼
                events = await analyze_post_with_retry(p["content"], p["post_url"] or "", p["published_at"])
                
                # 2. 事务原子性写入
                if DBService.save_extracted_events_transactional(p["id"], events, confidence_threshold):
                    # 过滤出置信度合规的并累计
                    filtered_events = [e for e in events if float(e.get("confidence", 1.0)) >= confidence_threshold]
                    success_events_count += len(filtered_events)
                    analyzed_count += 1
                else:
                    err_msg = f"博文 ID {p['id']} 事务原子性入库失败（软异常已自动回滚）。"
                    log_event("ERROR", "analyzer_transaction", err_msg)
            except (AssertionError, sqlite3.IntegrityError, ValueError, TypeError, AttributeError) as permanent_err:
                # 结构性/格式性永久故障：主事务安全回滚，开启独立短事务将状态置为 2 以防死循环
                err_msg = f"处理博文 ID {p['id']} 时遭遇永久性结构故障: {permanent_err}。系统已安全回滚主数据，并强制将状态标记为熔断挂起 (is_analyzed = 2)。"
                log_event("ERROR", "analyzer_breaker", err_msg, str(permanent_err))
                if DBService.mark_post_analysis_failed(p["id"]):
                    failed_count += 1
                    analyzed_count += 1  # 状态已成功扭转，计入完成分析总数以保持契约兼容
            except Exception as e:
                # 暂时性异常（如大模型连接超时等）
                err_msg = f"提炼博文 ID {p['id']} 时发生暂时性异常: {e}。将保持未分析状态以备下轮自动重试。"
                log_event("ERROR", "analyzer_analyze", err_msg, str(e))
                
        if failed_count > 0:
            print(f"\x1b[1;33m[Analyzer Breaker WARNING] 本轮分析共有 {failed_count} 条博文因数据格式/结构冲突触发熔断挂起 (is_analyzed = 2)，已跳过下轮重试。\x1b[0m")
            
        # [Auto-Discovery] 触发 Coser 自动发现机制
        try:
            from src.services.discovery_service import DiscoveryService
            print("\x1b[1;36m[Discovery] 正在分析增量博文的社交图谱以发现新 Coser...\x1b[0m")
            discovered_count = await DiscoveryService.discover_candidates_from_posts(pending_posts)
            if discovered_count > 0:
                print(f"\x1b[1;32m[Discovery] 本轮分析成功自动发现并录入了 {discovered_count} 位新 Coser 候选人，请使用 'coser list-candidates' 查看并审核！\x1b[0m")
        except Exception as discovery_err:
            log_event("WARNING", "orchestrator_discovery", f"自动发现过程出现异常: {discovery_err}", str(discovery_err))

        return total_posts, success_events_count, analyzed_count
