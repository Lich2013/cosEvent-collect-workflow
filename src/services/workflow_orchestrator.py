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
    async def run_scrape(limit: int = None) -> tuple[int, dict, int]:
        """[Scrape Phase] 异步去重抓取活跃 Coser 博文动态并持久化"""
        cosers = DBService.list_cosers(only_active=True)
        if not cosers:
            return 0, {
                "weibo": {"success": 0, "total": 0},
                "bilibili": {"success": 0, "total": 0},
                "xhs": {"success": 0, "total": 0}
            }, 0
            
        weibo_sc = WeiboScraper()
        bili_sc = BilibiliScraper()
        xhs_sc = XhsScraper()
        
        total_cosers = len(cosers)
        success_platforms = {
            "weibo": {"success": 0, "total": 0},
            "bilibili": {"success": 0, "total": 0},
            "xhs": {"success": 0, "total": 0}
        }
        total_inserted = 0
        
        for c in cosers:
            # 微博抓取
            if c["weibo_uid"]:
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
            if c["bilibili_uid"]:
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
            if c["xhs_uid"]:
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
        
        pending_posts = DBService.get_unanalyzed_posts()
        if not pending_posts:
            return 0, 0, 0
            
        total_posts = len(pending_posts)
        success_events_count = 0
        analyzed_count = 0
        
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
                    err_msg = f"博文 ID {p['id']} 事务原子性入库失败！已自动回滚。"
                    log_event("ERROR", "analyzer_transaction", err_msg)
            except Exception as e:
                err_msg = f"提炼博文 ID {p['id']} 时发生异常: {e}"
                log_event("ERROR", "analyzer_analyze", err_msg, str(e))
                
        return total_posts, success_events_count, analyzed_count
