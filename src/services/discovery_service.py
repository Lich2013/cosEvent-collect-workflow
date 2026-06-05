import re
import asyncio
import datetime
from src.services.db_service import DBService
from src.tools.bilibili_scraper import BilibiliScraper
from src.services.bili_uid_matcher import BiliUidMatcher
from src.utils.logger import log_event
from src.models.db_models import get_db_connection

class DiscoveryService:
    COSER_KEYWORDS = [
        "cos", "coser", "cosplay", "二次元", "排班", "工作", "合作", 
        "店长", "签售", "嘉宾", "模特", "发片", "写真", "博主", "次元", 
        "主页", "摄影", "后期", "妆造", "画师"
    ]

    @staticmethod
    def extract_mentions(content: str) -> list[str]:
        """从博文中正则提取 @提及 的用户昵称，包含前置否定边界，防止匹配邮箱地址"""
        if not content:
            return []
        # 使用否定后顾，确保 @ 前没有字母、数字、下划线、减号或点号 (防止匹配 email)
        raw_mentions = re.findall(r"(?<![a-zA-Z0-9_\-\.])@([\u4e00-\u9fa5a-zA-Z0-9_\-]+)", content)
        # 去重且过滤空名字
        seen = set()
        cleaned_mentions = []
        for m in raw_mentions:
            m_clean = m.strip()
            if m_clean and m_clean not in seen:
                seen.add(m_clean)
                cleaned_mentions.append(m_clean)
        return cleaned_mentions

    @staticmethod
    def register_candidates_from_posts(posts: list[dict]) -> int:
        """从博文中提取所有提及的 @用户名，无损并物理安全地注册为未验证的候选人（不设截断）"""
        if not posts:
            return 0

        # 1. 提取所有提及姓名
        all_mentions = []
        for p in posts:
            mentions = DiscoveryService.extract_mentions(p.get("content", ""))
            for m in mentions:
                all_mentions.append({
                    "name": m,
                    "source_ref": p.get("post_url") or ""
                })

        if not all_mentions:
            return 0

        # 2. 从数据库捞取所有已存在的 cosers 与 coser_candidates
        cosers = DBService.list_cosers(only_active=False)
        candidates = (
            DBService.list_candidates(status="pending") + 
            DBService.list_candidates(status="approved") + 
            DBService.list_candidates(status="ignored")
        )

        existing_names = {c["name"].lower() for c in cosers}
        existing_candidate_names = {c["name"].lower() for c in candidates}

        registered_count = 0
        seen_names = set()
        for item in all_mentions:
            name = item["name"]
            name_lower = name.lower()
            if name_lower not in existing_names and name_lower not in existing_candidate_names and name_lower not in seen_names:
                seen_names.add(name_lower)
                # 注册时 UID 记为 None，待后续异步检索对齐
                success = DBService.add_candidate(
                    name=name,
                    platform="bilibili",
                    source_ref=item["source_ref"],
                    matched_bili_uid=None,
                    match_score=0.0
                )
                if success:
                    registered_count += 1
        return registered_count

    @staticmethod
    async def verify_pending_candidates(limit: int = 15) -> int:
        """从缓冲队列捞取未验证的 pending 候选人，执行 B站 检索与打分验证"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, name, source_ref 
                FROM coser_candidates 
                WHERE status = 'pending' AND (matched_bili_uid IS NULL OR matched_bili_uid = '');
                """
            )
            rows = cursor.fetchall()
            candidates_to_verify = [{"id": r[0], "name": r[1], "source_ref": r[2]} for r in rows]
        finally:
            cursor.close()
            conn.close()

        if not candidates_to_verify:
            return 0

        process_limit = min(limit, len(candidates_to_verify))
        candidates_to_run = candidates_to_verify[:process_limit]
        print(f"\x1b[1;36m[Discovery] 缓冲队列中共有 {len(candidates_to_verify)} 个待验证候选人，本轮处理前 {len(candidates_to_run)} 个\x1b[0m")

        scraper = BilibiliScraper()
        newly_verified = 0

        # 批量检索 (Playwright 复用 Session)
        keywords = [c["name"] for c in candidates_to_run]
        try:
            results_map = await scraper.search_bilibili_users_batch(keywords)
            if isinstance(results_map, list):
                results_map = {}
        except Exception as e:
            log_event("ERROR", "DiscoveryService", f"批量验证检索失败: {e}", str(e))
            return 0

        for cand in candidates_to_run:
            cand_id = cand["id"]
            name = cand["name"]
            source_ref = cand["source_ref"]
            search_results = results_map.get(name, [])

            if not isinstance(search_results, list):
                search_results = []

            # 检索未找到任何 UP 主
            if not search_results:
                print(f"\x1b[1;33m[Discovery] ⚠ 候选人 [{name}] B站未检索到任何 UP 主，自动置为忽略。\x1b[0m")
                DBService.reject_candidate(cand_id)
                continue

            # 使用启发式打分 (置信度阈值 30.0)
            res = BiliUidMatcher.match_coser(name, search_results, confidence_threshold=30.0)
            best_match = res["best_match"]

            if best_match:
                best_mid = best_match["mid"]
                score = res["score"]

                # 获取 usign 字段
                original_result = next((item for item in search_results if str(item.get("mid")) == str(best_mid)), None)
                usign = (original_result.get("usign") or "") if original_result else ""

                bio_lower = usign.lower()
                verify_lower = (best_match.get("verify_desc") or "").lower()
                name_lower = name.lower()

                # 二次元属性校验
                is_coser_by_name = "cos" in name_lower or "coser" in name_lower or "cosplay" in name_lower
                is_coser_by_bio = any(kw in bio_lower for kw in DiscoveryService.COSER_KEYWORDS) or any(kw in verify_lower for kw in DiscoveryService.COSER_KEYWORDS)
                is_verified = best_match.get("scores", {}).get("verify", 0.0) > 0.0

                if is_coser_by_name or is_coser_by_bio or is_verified:
                    # 验证成功，更新 UID 和置信度分数
                    success = DBService.add_candidate(
                        name=name,
                        platform="bilibili",
                        source_ref=source_ref,
                        matched_bili_uid=str(best_mid),
                        match_score=score
                    )
                    if success:
                        newly_verified += 1
                        print(f"\x1b[1;32m[Discovery] ✓ 成功验证候选人 [{name}] -> B站(UID: {best_mid}) | 置信度: {score:.1f}\x1b[0m")
                else:
                    print(f"\x1b[1;33m[Discovery] ⚠ 候选人 [{name}] 未通过二次元属性关键词筛选。Bio: '{usign}'，自动置为忽略。\x1b[0m")
                    DBService.reject_candidate(cand_id)
            else:
                print(f"\x1b[1;33m[Discovery] ⚠ 候选人 [{name}] 检索结果未达到置信度门槛(30.0)，自动置为忽略。\x1b[0m")
                DBService.reject_candidate(cand_id)

        return newly_verified

    @staticmethod
    async def discover_candidates_from_posts(posts: list[dict], limit: int = 15) -> int:
        """
        二合一门面接口：
        1. 首先提取并注册 posts 中所有的潜在候选人（写入缓冲表，不设上限）
        2. 然后执行验证机制，最多处理 limit 个待验证的候选人（防止反爬风控）
        """
        registered = DiscoveryService.register_candidates_from_posts(posts)
        if registered > 0:
            print(f"\x1b[1;32m[Discovery] 从博文中成功提取并注册了 {registered} 位候选人到待验证队列。\x1b[0m")
            
        verified = await DiscoveryService.verify_pending_candidates(limit)
        return verified
