import asyncio
import logging
from src.config import settings
from src.services.db_service import DBService
from src.tools.weibo_scraper import WeiboScraper
from src.tools.bilibili_scraper import BilibiliScraper
from src.tools.xhs_scraper import XhsScraper
from src.utils.logger import log_event

class WorkflowOrchestrator:
    """
    工作流编排器 (Controller)：
    专门处理多源数据抓取、大模型增量提炼分析以及两阶段处理流程的总控与调度逻辑。
    """

    @staticmethod
    async def run_scrape(limit: int = None, coser_name: str = None, platform: str = "all") -> tuple[int, dict, int]:
        """[Scrape Phase] 异步去重抓取活跃 Coser 博文动态并持久化

        Args:
            limit: 单一平台最大爬取条数。
            coser_name: 可选，仅抓取匹配该姓名/昵称的 Coser；None 表示全量。
            platform: 可选，仅抓取该平台（weibo/bilibili/xhs/all）；默认 all 全量。
        """
        cosers = DBService.list_cosers(only_active=True)

        # 姓名过滤：内存推导裁剪，空结果优雅熔断
        if coser_name:
            cosers = [c for c in cosers if c["name"] == coser_name]
            if not cosers:
                print(f"\x1b[1;33m[WARNING] 未找到处于激活状态且名为 [{coser_name}] 的 Coser，请确认姓名拼写或启用状态。\x1b[0m")
                return 0, {}, 0

        if not cosers:
            return 0, {
                "weibo": {"success": 0, "total": 0},
                "bilibili": {"success": 0, "total": 0},
                "xhs": {"success": 0, "total": 0}
            }, 0

        # 仅实例化被指定平台的 Scraper，避免其余平台的冷启动
        weibo_sc = WeiboScraper() if platform in ("weibo", "all") else None
        bili_sc = BilibiliScraper() if platform in ("bilibili", "all") else None
        xhs_sc = XhsScraper() if platform in ("xhs", "all") else None

        total_cosers = len(cosers)
        success_platforms = {
            "weibo": {"success": 0, "total": 0},
            "bilibili": {"success": 0, "total": 0},
            "xhs": {"success": 0, "total": 0}
        }
        total_inserted = 0

        for c in cosers:
            # 微博抓取
            if c["weibo_uid"] and platform in ("weibo", "all"):
                success_platforms["weibo"]["total"] += 1
                try:
                    posts = await weibo_sc.fetch_weibo_posts(c["weibo_uid"], limit)
                    if posts:
                        ins = DBService.save_raw_posts(c["id"], "weibo", posts)
                        total_inserted += ins
                    success_platforms["weibo"]["success"] += 1
                except Exception as e:
                    log_event("ERROR", "scraper_weibo", f"Coser [{c['name']}] 微博抓取失败: {e}", str(e))

            # B站抓取
            if c["bilibili_uid"] and platform in ("bilibili", "all"):
                success_platforms["bilibili"]["total"] += 1
                try:
                    posts = await bili_sc.fetch_bilibili_posts(c["bilibili_uid"], limit)
                    if posts:
                        ins = DBService.save_raw_posts(c["id"], "bilibili", posts)
                        total_inserted += ins
                    success_platforms["bilibili"]["success"] += 1
                except Exception as e:
                    log_event("ERROR", "scraper_bilibili", f"Coser [{c['name']}] B站抓取失败: {e}", str(e))

            # 小红书抓取
            if c["xhs_uid"] and platform in ("xhs", "all"):
                success_platforms["xhs"]["total"] += 1
                try:
                    posts = await xhs_sc.fetch_xhs_posts(c["xhs_uid"], limit)
                    if posts:
                        ins = DBService.save_raw_posts(c["id"], "xhs", posts)
                        total_inserted += ins
                    success_platforms["xhs"]["success"] += 1
                except Exception as e:
                    log_event("ERROR", "scraper_xhs", f"Coser [{c['name']}] 小红书抓取失败: {e}", str(e))

        return total_cosers, success_platforms, total_inserted


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
            
        return total_posts, success_events_count, analyzed_count
