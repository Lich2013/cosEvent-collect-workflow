import re
import asyncio
import datetime
from src.config import settings
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
    def prune_weibo_suffix(name: str) -> str:
        """清洗裁剪微博候选人昵称的常见专属/二次元后缀"""
        if not name:
            return ""
        # 1. 匹配常见的下划线后接纯英文后缀，如 _ShiratoriK, _Coser, _cos, _cosplay 等
        name = re.sub(r"_[a-zA-Z]+$", "", name)
        # 2. 匹配中文专属后缀，如 _cos, _Coser, _官博, _官方, _摄影 等
        name = re.sub(r"_(coser|cosplay|cos|摄影|后期|妆造|官博|官方|画师|bot)$", "", name, flags=re.IGNORECASE)
        # 3. 剥离尾部的下划线
        name = name.rstrip("_")
        return name

    @staticmethod
    def register_candidates_from_posts(posts: list[dict]) -> int:
        """从博文中提取所有提及的 @用户名，无损并物理安全地注册为未验证的候选人（不设限制）"""
        if not posts:
            return 0

        # 1. 提取所有提及姓名及可能预绑定的 UID
        all_mentions = []
        for p in posts:
            pre_bound_mentions = p.get("mentions", [])
            for m in pre_bound_mentions:
                all_mentions.append({
                    "name": m["name"],
                    "uid": m["uid"],
                    "source_ref": p.get("post_url") or "",
                    "platform": p.get("platform") or "bilibili"
                })
            
            if not pre_bound_mentions:
                mentions = DiscoveryService.extract_mentions(p.get("content", ""))
                for m in mentions:
                    all_mentions.append({
                        "name": m,
                        "uid": None,
                        "source_ref": p.get("post_url") or "",
                        "platform": p.get("platform") or "bilibili"
                    })

        if not all_mentions:
            return 0

        # 2. 从数据库捞取所有已存在的 cosers 与 coser_candidates
        cosers = DBService.list_cosers(only_active=False)
        candidates = (
            DBService.list_candidates(status="pending") + 
            DBService.list_candidates(status="approved") + 
            DBService.list_candidates(status="ignored") +
            DBService.list_candidates(status="undetermined")
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
                
                bili_uid = item["uid"] if item["platform"] == "bilibili" else None
                weibo_uid = item["uid"] if item["platform"] == "weibo" else None
                
                success = DBService.add_candidate(
                    name=name,
                    platform=item["platform"],
                    source_ref=item["source_ref"],
                    matched_bili_uid=bili_uid,
                    matched_weibo_uid=weibo_uid,
                    match_score=0.0,
                    is_verified=0
                )
                if success:
                    registered_count += 1
        return registered_count

    @staticmethod
    def has_strong_match(text: str) -> bool:
        if not text:
            return False
        text_lower = text.lower()
        strong_kws = settings.coser_keywords.get("strong") or ["cosplay", "coser", "排班", "嘉宾", "发片"]
        return any(kw in text_lower for kw in strong_kws)

    @staticmethod
    def has_weak_match(text: str) -> bool:
        if not text:
            return False
        text_lower = text.lower()
        weak_kws = settings.coser_keywords.get("weak") or [
            "cos", "二次元", "工作", "合作", "店长", "签售", "模特", 
            "写真", "博主", "次元", "主页", "摄影", "后期", "妆造", "画师"
        ]
        return any(kw in text_lower for kw in weak_kws)

    @staticmethod
    async def verify_pending_candidates(limit: int = 15) -> int:
        """从缓冲队列捞取未验证的 pending/undetermined 候选人，执行 B站 检索与打分验证"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, name, source_ref, platform, matched_bili_uid, matched_weibo_uid, status, status_updated_at
                FROM coser_candidates 
                WHERE (status = 'pending' AND is_verified = 0) OR (status = 'undetermined' AND is_verified = 0 AND datetime(status_updated_at) <= datetime('now', '-7 days', '+8 hours'))
                ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, status_updated_at DESC;
                """
            )
            rows = cursor.fetchall()
            
            candidates_to_verify = []
            for r in rows:
                cand_id = r[0]
                name = r[1]
                source_ref = r[2]
                platform = r[3]
                matched_bili_uid = r[4]
                matched_weibo_uid = r[5]
                status = r[6]
                status_updated_at_str = r[7]
                
                candidates_to_verify.append({
                    "id": cand_id,
                    "name": name,
                    "source_ref": source_ref,
                    "platform": platform,
                    "matched_bili_uid": matched_bili_uid,
                    "matched_weibo_uid": matched_weibo_uid,
                    "status": status,
                    "status_updated_at": status_updated_at_str
                })
        finally:
            cursor.close()
            conn.close()

        # 获取正式追踪名单中已有的 UID，用作去重检测 (Prevent duplicate tracking)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT bilibili_uid, weibo_uid FROM cosers;")
            db_uids = cursor.fetchall()
            existing_bili_uids = {str(r[0]) for r in db_uids if r[0] and str(r[0]).strip()}
            existing_weibo_uids = {str(r[1]) for r in db_uids if r[1] and str(r[1]).strip()}
        except Exception as e:
            existing_bili_uids = set()
            existing_weibo_uids = set()
        finally:
            cursor.close()
            conn.close()

        if not candidates_to_verify:
            return 0

        process_limit = min(limit, len(candidates_to_verify))
        candidates_to_run = candidates_to_verify[:process_limit]
        print(f"\x1b[1;36m[Discovery] 缓冲队列中共有 {len(candidates_to_verify)} 个待验证候选人，本轮处理前 {len(candidates_to_run)} 个\x1b[0m")

        # 预先进行微博来源及交叉候选人的批量解析与缓存
        from src.tools.weibo_scraper import WeiboScraper
        weibo_scraper = WeiboScraper()
        
        weibo_names = [cand["name"] for cand in candidates_to_run]
        resolved_weibo_users = {}
        if weibo_names:
            resolved_weibo_users = await weibo_scraper.resolve_screen_names_batch(weibo_names)
            
        # 收集本轮中已有已绑定 weibo_uid 的候选人，批量解析其 Profile
        weibo_uids_to_resolve = [
            str(cand["matched_weibo_uid"]) 
            for cand in candidates_to_run 
            if cand.get("matched_weibo_uid") and str(cand["matched_weibo_uid"]).strip()
        ]
        resolved_weibo_users_by_uid = {}
        if weibo_uids_to_resolve:
            try:
                resolved_weibo_users_by_uid = await weibo_scraper.resolve_uids_batch(weibo_uids_to_resolve)
            except Exception as e:
                log_event("ERROR", "DiscoveryService", f"通过 UID 批量解析微博 Profile 失败: {e}", str(e))
        
        weibo_info_map = {}
        
        # Collect keywords for B站 searches (only for candidates without pre-bound B站 UID)
        cand_to_search_kw = {}
        search_keywords = []
        for cand in candidates_to_run:
            cand_id = cand["id"]
            name = cand["name"]
            platform = cand["platform"]
            
            # 1. Weibo attributes caching (Double-sided cross-verification)
            weibo_uid = cand.get("matched_weibo_uid")
            weibo_bio = ""
            weibo_verify = ""
            
            # 优先从已绑定 UID 解析的微博用户信息中匹配属性
            weibo_user = None
            if weibo_uid and str(weibo_uid).strip():
                weibo_user = resolved_weibo_users_by_uid.get(str(weibo_uid))
            
            # 如果没有，降级使用同名匹配到的用户信息
            if not weibo_user:
                weibo_user = resolved_weibo_users.get(name)
            
            if weibo_user:
                weibo_uid = str(weibo_user.get("idstr") or weibo_uid or "")
                weibo_bio = weibo_user.get("description") or ""
                weibo_verify = weibo_user.get("verified_reason") or ""
            
            weibo_info_map[cand_id] = {
                "weibo_uid": weibo_uid,
                "weibo_bio": weibo_bio,
                "weibo_verify": weibo_verify
            }
            
            # 2. B站 search setup
            pre_bound_bili_uid = cand.get("matched_bili_uid")
            if not pre_bound_bili_uid or not str(pre_bound_bili_uid).strip():
                if platform == "weibo":
                    search_kw = DiscoveryService.prune_weibo_suffix(name)
                else:
                    search_kw = name
                cand_to_search_kw[cand_id] = search_kw
                search_keywords.append(search_kw)

        scraper = BilibiliScraper()
        results_map = {}
        if search_keywords:
            try:
                results_map = await scraper.search_bilibili_users_batch(search_keywords)
                if isinstance(results_map, list):
                    results_map = {}
            except Exception as e:
                log_event("ERROR", "DiscoveryService", f"批量验证检索失败: {e}", str(e))
                results_map = {}

        candidate_uids = {}
        candidate_bili_scores = {}
        candidate_search_results = {}
        candidate_best_match = {}
        
        for cand in candidates_to_run:
            cand_id = cand["id"]
            pre_bound_bili_uid = cand.get("matched_bili_uid")
            
            if pre_bound_bili_uid and str(pre_bound_bili_uid).strip():
                candidate_uids[cand_id] = str(pre_bound_bili_uid)
                candidate_bili_scores[cand_id] = 100.0
            else:
                search_kw = cand_to_search_kw.get(cand_id)
                search_results = results_map.get(search_kw, []) if search_kw else []
                if not isinstance(search_results, list):
                    search_results = []
                candidate_search_results[cand_id] = search_results
                
                best_match = None
                score = 0.0
                best_mid = None
                if search_results:
                    res = BiliUidMatcher.match_coser(search_kw, search_results, confidence_threshold=30.0)
                    best_match = res["best_match"]
                    if best_match:
                        best_mid = str(best_match["mid"])
                        score = res["score"]
                        candidate_best_match[cand_id] = best_match
                
                if best_mid:
                    candidate_uids[cand_id] = best_mid
                    candidate_bili_scores[cand_id] = score

        uids_to_resolve = list(set(uid for uid in candidate_uids.values() if uid))
        resolved_profiles = {}
        if uids_to_resolve:
            try:
                resolved_profiles = await scraper.resolve_uids_batch(uids_to_resolve)
            except Exception as e:
                log_event("ERROR", "DiscoveryService", f"批量解析 B站 空间失败: {e}", str(e))
                resolved_profiles = {}

        # 预先分析强弱匹配，用于自适应爬取及直接确权
        strong_match_map = {}
        weak_match_map = {}
        for cand in candidates_to_run:
            cand_id = cand["id"]
            name = cand["name"]
            platform = cand["platform"]
            bili_uid = candidate_uids.get(cand_id)
            
            w_info = weibo_info_map.get(cand_id)
            w_bio = w_info["weibo_bio"] if w_info else ""
            w_verify = w_info["weibo_verify"] if w_info else ""
            
            profile = resolved_profiles.get(bili_uid) if bili_uid else None
            b_bio = ""
            b_verify = ""
            if profile and (profile.get("bio") or profile.get("verify_desc")):
                b_bio = profile.get("bio") or ""
                b_verify = profile.get("verify_desc") or ""
            else:
                best_match = candidate_best_match.get(cand_id)
                if best_match:
                    search_results = candidate_search_results.get(cand_id, [])
                    original_result = next((item for item in search_results if str(item.get("mid")) == str(bili_uid)), None)
                    b_bio = (original_result.get("usign") or "") if original_result else ""
                    b_verify = best_match.get("verify_desc") or ""
            
            strong_matched = (
                DiscoveryService.has_strong_match(name) or
                DiscoveryService.has_strong_match(w_bio) or 
                DiscoveryService.has_strong_match(w_verify) or 
                DiscoveryService.has_strong_match(b_bio) or 
                DiscoveryService.has_strong_match(b_verify)
            )
            
            name_lower = name.lower()
            name_has_cos = False
            if "cos" in name_lower:
                exclude_words = ["costco", "cosme", "cosmos", "constantine", "cosco", "cosmect", "cosmetic"]
                if not any(ew in name_lower for ew in exclude_words):
                    is_valid_cos = (
                        "coser" in name_lower or
                        "cosplay" in name_lower or
                        re.search(r'(?:^|[^a-zA-Z])cos(?:$|[^a-zA-Z])', name_lower) is not None
                    )
                    if is_valid_cos:
                        name_has_cos = True
                        
            bio_has_weak = (
                DiscoveryService.has_weak_match(w_bio) or 
                DiscoveryService.has_weak_match(w_verify) or 
                DiscoveryService.has_weak_match(b_bio) or 
                DiscoveryService.has_weak_match(b_verify)
            )
            
            strong_match_map[cand_id] = strong_matched
            weak_match_map[cand_id] = name_has_cos or bio_has_weak

        # 物理隔离并发爬取候选人博文逻辑并保存至 candidate_raw_posts
        failed_crawl_cand_ids = set()

        async def fetch_and_save_single_candidate(cand):
            cand_id = cand["id"]
            if strong_match_map.get(cand_id, False):
                return
                
            cand_platform = cand["platform"]
            bili_uid = candidate_uids.get(cand_id)
            w_info = weibo_info_map.get(cand_id)
            weibo_uid = w_info["weibo_uid"] if w_info else None
            
            is_weak = weak_match_map.get(cand_id, False)
            limit = 10 if is_weak else 3
            
            posts_fetched = []
            try:
                if cand_platform == "bilibili" and bili_uid:
                    posts_fetched = await scraper.fetch_bilibili_posts(bili_uid, limit=limit)
                elif cand_platform == "weibo" and weibo_uid:
                    posts_fetched = await weibo_scraper.fetch_weibo_posts(weibo_uid, limit=limit)
                
                real_posts = [p for p in posts_fetched if not p["post_id"].startswith("bio_")]
                if real_posts:
                    DBService.save_candidate_raw_posts(cand_id, cand_platform, real_posts)
                    print(f"\x1b[1;36m[Discovery] 成功抓取并隔离保存候选人 [{cand['name']}] 的 {len(real_posts)} 条博文文本。\x1b[0m")
            except Exception as err:
                log_event("WARNING", "DiscoveryService", f"抓取候选人 [{cand['name']}] 博文失败: {err}", str(err))
                failed_crawl_cand_ids.add(cand_id)

        scrape_tasks = [fetch_and_save_single_candidate(cand) for cand in candidates_to_run]
        if scrape_tasks:
            await asyncio.gather(*scrape_tasks)

        # 并发评估候选人核验状态
        async def evaluate_single_candidate(cand):
            cand_id = cand["id"]
            name = cand["name"]
            
            w_info = weibo_info_map.get(cand_id)
            weibo_uid = w_info["weibo_uid"] if w_info else None
            bili_uid = candidate_uids.get(cand_id)

            # 0. 检测是否已在正式追踪列表中 (Prevent duplicate tracking)
            is_already_tracked = (
                (bili_uid and str(bili_uid) in existing_bili_uids) or
                (weibo_uid and str(weibo_uid) in existing_weibo_uids)
            )
            if is_already_tracked:
                return {
                    "cand": cand,
                    "action": "reject",
                    "reject_reason": "ALREADY_TRACKED",
                    "weibo_uid": weibo_uid
                }

            # 1. 强匹配直接确权通过，不调用 LLM 及博文抓取
            if strong_match_map.get(cand_id, False):
                return {
                    "cand": cand,
                    "action": "approve",
                    "verify_reason": "Bio 关键词匹配成功",
                    "bili_uid": bili_uid,
                    "weibo_uid": weibo_uid
                }

            # 2. 如果 Bio 不满足强匹配，则查询已抓取的隔离博文
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT platform, content, published_at FROM candidate_raw_posts WHERE candidate_id = ? ORDER BY id DESC LIMIT 10;",
                    (cand_id,)
                )
                p_rows = cursor.fetchall()
                candidate_posts = [{"platform": pr[0], "content": pr[1], "published_at": pr[2]} for pr in p_rows]
            finally:
                cursor.close()
                conn.close()

            # 3. 存在博文时调用 LLM 智能体判定
            if candidate_posts:
                from src.agents.event_agent import analyze_candidate_posts
                try:
                    llm_res = await analyze_candidate_posts(name, candidate_posts)
                    is_coser_by_posts = llm_res.get("is_active_coser", False)
                    llm_reason = llm_res.get("reason", "无")
                    
                    if is_coser_by_posts:
                        return {
                            "cand": cand,
                            "action": "approve",
                            "verify_reason": f"[LLM] {llm_reason}",
                            "bili_uid": bili_uid,
                            "weibo_uid": weibo_uid
                        }
                    else:
                        confidence = llm_res.get("confidence", 1.0)
                        if confidence >= 0.8:
                            return {
                                "cand": cand,
                                "action": "reject",
                                "reject_reason": "LLM_VERIFY_FAILED_HAS_RUN"
                            }
                        else:
                            return {
                                "cand": cand,
                                "action": "set_undetermined",
                                "reason": f"[LLM Low Confidence {confidence}] {llm_reason}"
                            }
                except Exception as e:
                    # 发生暂时性 LLM 异常，返回待处理状态
                    log_event("WARNING", "DiscoveryService", f"候选人 [{name}] 智能体核验发生暂时性异常: {e}", str(e))
                    return {
                        "cand": cand,
                        "action": "keep_pending",
                        "reason": f"智能体核验暂时性异常: {e}"
                    }

            # 4. 如果没有博文数据，检查是否因为爬取时发生异常
            if cand_id in failed_crawl_cand_ids:
                return {
                    "cand": cand,
                    "action": "keep_pending",
                    "reason": "博文抓取异常"
                }

            # 5. 没有博文数据且爬取没有发生异常，判定为非 Coser 忽略
            return {
                "cand": cand,
                "action": "reject",
                "reject_reason": "NO_POSTS_AND_BIO_FAILED"
            }

        # 引入 Semaphore 限频大模型请求 (Semaphore concurrency limit of 5)
        sem = asyncio.Semaphore(5)

        async def evaluate_single_candidate_with_sem(cand):
            async with sem:
                return await evaluate_single_candidate(cand)

        eval_tasks = [evaluate_single_candidate_with_sem(cand) for cand in candidates_to_run]
        eval_results = []
        if eval_tasks:
            eval_results = await asyncio.gather(*eval_tasks)

        # 串行写入数据库，防止 SQLite 并发写锁冲突
        newly_verified = 0
        for res in eval_results:
            cand = res["cand"]
            cand_id = cand["id"]
            name = cand["name"]
            action = res["action"]
            
            if action == "approve":
                verify_reason = res["verify_reason"]
                bili_uid = res["bili_uid"]
                weibo_uid = res["weibo_uid"]
                success = DBService.add_candidate(
                    name=name,
                    platform=cand["platform"],
                    source_ref=cand["source_ref"],
                    matched_bili_uid=bili_uid,
                    matched_weibo_uid=weibo_uid,
                    match_score=candidate_bili_scores.get(cand_id, 0.0),
                    is_verified=1,
                    verify_reason=verify_reason
                )
                if success:
                    # 自动核验自动通过 (Auto-Promotion) 并物理清理临时博文
                    DBService.approve_candidate(cand_id)
                    newly_verified += 1
                    bili_info = f" -> B站(UID: {bili_uid})" if bili_uid else ""
                    weibo_info = f" -> 微博(UID: {weibo_uid})" if weibo_uid else ""
                    print(f"\x1b[1;32m[Discovery] ✓ 成功自动验证并批准候选人 [{name}]{bili_info}{weibo_info} | 原因: {verify_reason} | 置信度: {candidate_bili_scores.get(cand_id, 0.0):.1f}\x1b[0m")
            elif action == "reject":
                reject_reason = res["reject_reason"]
                bili_uid = candidate_uids.get(cand_id)
                if reject_reason == "ALREADY_TRACKED":
                    uid_str = bili_uid or res.get("weibo_uid") or ""
                    print(f"\x1b[1;33m[Discovery] ⚠ 候选人 [{name}] 的 UID ({uid_str}) 已在正式追踪名单中，自动忽略此候选人。\x1b[0m")
                elif reject_reason == "LLM_VERIFY_FAILED_HAS_RUN":
                    print(f"\x1b[1;33m[Discovery] ⚠ 候选人 [{name}] 未通过 LLM 博文核验，自动置为忽略。\x1b[0m")
                elif not bili_uid:
                    print(f"\x1b[1;33m[Discovery] ⚠ 候选人 [{name}] B站未检索到任何 UP 主，且未通过微博属性校验，自动置为忽略。\x1b[0m")
                else:
                    print(f"\x1b[1;33m[Discovery] ⚠ 候选人 [{name}] 未通过二次元属性及相似度校验，自动置为忽略。\x1b[0m")
                DBService.reject_candidate(cand_id)
            elif action == "set_undetermined":
                print(f"\x1b[1;33m[Discovery] ⚠ 候选人 [{name}] 置信度较低，暂时标记为待定（undetermined）: {res['reason']}\x1b[0m")
                DBService.set_candidate_undetermined(cand_id)
            elif action == "keep_pending":
                print(f"\x1b[1;33m[Discovery] ⚠ 候选人 [{name}] 核验流程不完整（{res['reason']}），保留 pending 状态以供下次重试。\x1b[0m")

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
