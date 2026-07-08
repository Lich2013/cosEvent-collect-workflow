import sqlite3
import re
from src.models.db_models import get_db_connection
from src.services.fusion_service import EventFusionService
from src.utils.logger import log_event
from src.utils.validation import validate_status, validate_type
from src.utils.parsers import parse_city
from src.utils.time import beijing_today_str, beijing_now_str

class EventRepository:
    @staticmethod
    def save_extracted_events_transactional(raw_post_id: int, events: list[dict], confidence_threshold: float) -> bool:
        """
        核心原子事务控制：
        1. 获取真实 Coser 昵称 (注入 coser_name)
        2. 基于系统当前参考日期执行增量合并（时间轴分流）：
           - 历史活动日程（早于今日）进行冻结保护，只增不删。
           - 未来活动日程（大于等于今日/未知）执行增量合并（Upsert）与状态对齐物理清理（Delete）。
        3. 自动与时空融合引擎 (EventFusionService) 对齐归一化超级漫展 ID (normalized_event_id)
        4. 同步将对应的 raw_posts.is_analyzed 标志更新为 1
        5. 任何一步异常均由 sqlite3 标准连接上下文管理器管理回滚
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # 3. 利用 standard conn 管理上下文的自动 Commit/Rollback 原子事务
            with conn:
                # 3.0 SQLite 事务升级强锁：抢占写锁规避高并发写死锁冲突
                cursor.execute("BEGIN IMMEDIATE;")

                # 1. 查找对应的 coser.name, post_id, platform (已放入事务锁包裹中以防脏读)
                cursor.execute(
                    """
                    SELECT r.post_id, r.platform, c.name FROM cosers c
                    JOIN raw_posts r ON c.id = r.coser_id
                    WHERE r.id = ?;
                    """,
                    (raw_post_id,)
                )
                row = cursor.fetchone()
                if not row:
                    print(f"\x1b[1;31m[Database ERROR] 关联博文 ID {raw_post_id} 找不到匹配的 Coser 实体！\x1b[0m")
                    return False
                post_id, platform, coser_name = row

                # 获取该博文的逻辑 base_post_id (支持 #v 后缀版本)
                base_post_id = post_id.split("#")[0] if post_id else ""

                # 查找该博文既往的所有版本（包括当前版本）的 raw_posts.id
                cursor.execute(
                    """
                    SELECT id FROM raw_posts
                    WHERE platform = ? AND (post_id = ? OR post_id LIKE ?);
                    """,
                    (platform, base_post_id, f"{base_post_id}#v%")
                )
                all_version_ids = [r[0] for r in cursor.fetchall()]
                previous_version_ids = [vid for vid in all_version_ids if vid != raw_post_id]

                # 2. 查出当前版本数据库中已有的活动列表
                cursor.execute(
                    "SELECT id, event_name, event_date, event_place, status, normalized_event_id FROM cosplay_events WHERE raw_post_id = ?;",
                    (raw_post_id,)
                )
                existing_rows = cursor.fetchall()
                
                # 以统一北京时间为分流基准线。
                current_date = beijing_today_str()
                now_str = beijing_now_str()

                def is_historical_date(date_val: str) -> bool:
                    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_val or "")) and date_val < current_date
                
                # 查询该 Coser 在全局所有平台的所有既存活动（排除已取消的）以进行全局 Upsert 合并
                cursor.execute(
                    """
                    SELECT id, raw_post_id, event_name, event_date, event_place, event_description, source_url, confidence, status, normalized_event_id, event_type
                    FROM cosplay_events
                    WHERE coser_name = ? AND status != '已取消';
                    """,
                    (coser_name,)
                )
                coser_active_rows = cursor.fetchall()
                coser_future_events = []
                for r in coser_active_rows:
                    r_id, r_raw_post_id, r_name, r_date, r_place, r_desc, r_source_url, r_conf, r_status, r_norm_id, r_type = r
                    is_historical_r = is_historical_date(r_date)
                    if not is_historical_r:
                        coser_future_events.append(list(r))
                
                # 分离出已存未来行程的唯一键映射 {(name, date, place): (id, norm_id)}
                existing_future_map = {}
                for r_id, r_name, r_date, r_place, r_status, r_norm_id in existing_rows:
                    if r_status != '已取消':
                        is_historical_r = is_historical_date(r_date)
                        
                        if not is_historical_r:
                            existing_future_map[(r_name, r_date, r_place)] = (r_id, r_norm_id)

                affected_norm_ids = set()
                seen_db_ids = set()

                def is_date_compatible(date1: str, date2: str) -> bool:
                    if date1 == '未知' or date2 == '未知':
                        return True
                    return date1 == date2

                def merge_descriptions(desc1: str, desc2: str) -> str:
                    if not desc1 and not desc2:
                        return ""
                    if not desc1:
                        return desc2 or ""
                    if not desc2:
                        return desc1 or ""
                    d1 = desc1.strip()
                    d2 = desc2.strip()
                    if d1 == d2:
                        return d1
                    if d1 in d2:
                        return d2
                    if d2 in d1:
                        return d1
                    
                    parts1 = [p.strip() for p in d1.split("|") if p.strip()]
                    parts2 = [p.strip() for p in d2.split("|") if p.strip()]
                    merged_parts = []
                    for p in parts1:
                        if p not in merged_parts:
                            merged_parts.append(p)
                    for p in parts2:
                        if p not in merged_parts:
                            is_sub = False
                            for existing in merged_parts:
                                if p in existing or existing in p:
                                    is_sub = True
                                    if len(p) > len(existing):
                                        idx = merged_parts.index(existing)
                                        merged_parts[idx] = p
                                    break
                            if not is_sub:
                                merged_parts.append(p)
                    return " | ".join(merged_parts)
                
                # 3.1 批量软取消既往历史版本的未来有效行程
                if previous_version_ids:
                    validate_status('已取消')
                    placeholders = ",".join(["?"] * len(previous_version_ids))
                    
                    # 软取消前先搜集受影响的超级节点ID以更新区间
                    cursor.execute(
                        f"""
                        SELECT DISTINCT normalized_event_id FROM cosplay_events
                        WHERE raw_post_id IN ({placeholders}) AND event_date >= ? AND status = '未开始' AND normalized_event_id IS NOT NULL;
                        """,
                        (*previous_version_ids, current_date)
                    )
                    for norm_r in cursor.fetchall():
                        affected_norm_ids.add(norm_r[0])
                        
                    cursor.execute(
                        f"""
                        UPDATE cosplay_events
                        SET status = '已取消'
                        WHERE raw_post_id IN ({placeholders}) AND event_date >= ? AND status = '未开始';
                        """,
                        (*previous_version_ids, current_date)
                    )

                new_future_keys = set()
                
                for event in events:
                    if "status" in event:
                        validate_status(event["status"])
                    confidence = float(event.get("confidence", 1.0))
                    if confidence < confidence_threshold:
                        continue
                    
                    event_name = event["event_name"]
                    event_date = event["event_date"]
                    event_place = event["event_place"]
                    event_description = event.get("event_description")
                    source_url = event.get("source_url")
                    event_type = event.get("event_type", "漫展") or "漫展"
                    validate_type(event_type)
                    
                    # 判断当前活动是否为历史发生行程
                    is_historical = is_historical_date(event_date)
                        
                    if is_historical:
                        err_msg = f"LLM 返回历史活动 [{event_name}]({event_date})，早于当前参考日期 {current_date}，已跳过写入。"
                        log_event("WARNING", "event_history_filter", err_msg, source_url or "")
                        continue
                    else:
                        # 城市智能解析与时空融合归一化判定。历史活动在此之前已被跳过，避免污染归一化节点。
                        city = parse_city(event_place)
                        normalized_id = EventFusionService.find_or_create_normalized_event(
                            cursor, event_name, city, event_date, event_type
                        )
                        affected_norm_ids.add(normalized_id)

                        # 未来行程增量对齐合并 (Upsert)
                        key = (event_name, event_date, event_place)
                        new_future_keys.add(key)
                        
                        # 尝试在全局已存未来日程中寻找相同 normalized_event_id 且日期相容的行进行 In-place 合并
                        match_idx = -1
                        for idx, r in enumerate(coser_future_events):
                            r_id, r_raw_post_id, r_name, r_date, r_place, r_desc, r_source_url, r_conf, r_status, r_norm_id, r_type = r
                            if r_norm_id == normalized_id and is_date_compatible(r_date, event_date):
                                match_idx = idx
                                break
                        
                        if match_idx != -1:
                            # 存在：对既存行执行 In-place 覆盖合并
                            r = coser_future_events[match_idx]
                            r_id, r_raw_post_id, r_name, r_date, r_place, r_desc, r_source_url, r_conf, r_status, r_norm_id, r_type = r
                            
                            if r_norm_id:
                                affected_norm_ids.add(r_norm_id)
                                
                            final_date = event_date if r_date == '未知' else r_date
                            merged_description = merge_descriptions(r_desc, event_description)
                            
                            seen_db_ids.add(r_id)
                            validate_status('未开始')
                            
                            cursor.execute(
                                """
                                UPDATE cosplay_events
                                SET event_date = ?, event_description = ?, confidence = ?, source_url = ?, status = '未开始', normalized_event_id = ?, event_type = ?, raw_post_id = ?
                                WHERE id = ?;
                                """,
                                (final_date, merged_description, confidence, source_url, normalized_id, event_type, raw_post_id, r_id)
                            )
                            
                            # 更新内存记录以供后续合并链条使用
                            coser_future_events[match_idx] = [r_id, raw_post_id, r_name, final_date, r_place, merged_description, source_url, confidence, '未开始', normalized_id, event_type]
                        else:
                            # 不存在：全新未来日程，执行插入
                            validate_status('未开始')
                            cursor.execute(
                                """
                                INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, status, normalized_event_id, event_type, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '未开始', ?, ?, ?);
                                """,
                                (raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, normalized_id, event_type, now_str)
                            )
                            new_id = cursor.lastrowid
                            seen_db_ids.add(new_id)
                            # 并入内存列表
                            coser_future_events.append([new_id, raw_post_id, event_name, event_date, event_place, event_description, source_url, confidence, '未开始', normalized_id, event_type])
                
                # 4. 软取消失效日程：将所有在最新分析中已消失的未来日程（已取消或已改期日程）的 status 更新为 '已取消'
                for key, (db_id, norm_id) in existing_future_map.items():
                    if db_id not in seen_db_ids:
                        if norm_id:
                            affected_norm_ids.add(norm_id)
                        validate_status('已取消')
                        cursor.execute(
                            "UPDATE cosplay_events SET status = '已取消' WHERE id = ?;",
                            (db_id,)
                        )
                
                # 5. 重新刷新本轮事务波及到的所有归一化超级漫展节点的时间最宽包络
                for norm_id in affected_norm_ids:
                    EventFusionService.update_event_bounding_box(cursor, norm_id)

                # 6. 将对应博文标记为已分析 (is_analyzed = 1)
                cursor.execute(
                    "UPDATE raw_posts SET is_analyzed = 1 WHERE id = ?;",
                    (raw_post_id,)
                )
                
            # 在主事务提交后，自动触发一次快速物化视图重建，确保数据实时一致性
            try:
                from src.services.db.materialize_service import MaterializeService
                MaterializeService.rebuild_view()
            except Exception as mat_err:
                print(f"\x1b[1;33m[Materialize Warning] 自动物化重建失败，已忽略以防阻断分析: {mat_err}\x1b[0m")
                
            return True
        except (AssertionError, sqlite3.IntegrityError, ValueError, TypeError, AttributeError) as permanent_err:
            # 结构性、永久性硬故障：回退后重新 raise 出来供外层执行熔断标记为 2
            err_msg = f"写入活动发生结构性永久冲突/校验失败，已自动回滚事务！原因: {permanent_err}"
            print(f"\x1b[1;31m[Database TRANSACTION FAILURE] {err_msg}\x1b[0m")
            log_event("ERROR", "database_transaction_permanent", err_msg, str(permanent_err))
            raise permanent_err
        except Exception as e:
            # 暂时性/偶发性故障：仅回滚事务并返回 False，保持 is_analyzed = 0 下轮重新尝试
            err_msg = f"写入活动发生暂时性系统异常，已触发事务回滚！原因: {e}"
            print(f"\x1b[1;31m[Database TRANSACTION ERROR] {err_msg}\x1b[0m")
            log_event("ERROR", "database_transaction_transient", err_msg, str(e))
            return False
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def mark_post_analysis_failed(raw_post_id: int) -> bool:
        """
        以独立且精简的短事务方式，将 raw_posts.is_analyzed 强制标记为 2（熔断挂起）。
        供外部编排器发生结构性硬异常时物理隔离调用，彻底规避写锁并发死锁。
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            with conn:
                cursor.execute("BEGIN IMMEDIATE;")
                cursor.execute(
                    "UPDATE raw_posts SET is_analyzed = 2 WHERE id = ?;",
                    (raw_post_id,)
                )
            print(f"\x1b[1;32m[Database Breaker] 成功将博文 ID {raw_post_id} 变更为分析熔断状态 (is_analyzed = 2)。\x1b[0m")
            return True
        except Exception as e:
            err_msg = f"标记博文 ID {raw_post_id} 为分析失败熔断状态失败: {e}"
            print(f"\x1b[1;31m[Database Breaker ERROR] {err_msg}\x1b[0m")
            log_event("ERROR", "database_breaker", err_msg, str(e))
            return False
        finally:
            cursor.close()
            conn.close()
