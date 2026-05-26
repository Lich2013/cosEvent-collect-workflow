import sqlite3
import datetime
import re
from src.models.db_models import get_db_connection
from src.services.fusion_service import EventFusionService
from src.utils.logger import log_event
from src.utils.validation import validate_status, validate_type
from src.utils.parsers import parse_city

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
            # 1. 查找对应的 coser.name, post_id, platform
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
            
            # 以当前日期为分流基准线，强行对齐到北京时间 (UTC+8)
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            current_date = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d")
            now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
            
            # 分离出已存未来行程的唯一键映射 {(name, date, place): (id, norm_id)}
            existing_future_map = {}
            for r_id, r_name, r_date, r_place, r_status, r_norm_id in existing_rows:
                if r_status != '已取消':
                    is_historical_r = False
                    if re.match(r"^\d{4}-\d{2}-\d{2}$", r_date):
                        is_historical_r = r_date < current_date
                    
                    if not is_historical_r:
                        existing_future_map[(r_name, r_date, r_place)] = (r_id, r_norm_id)

            affected_norm_ids = set()

            # 3. 利用 standard conn 管理上下文的自动 Commit/Rollback 原子事务
            with conn:
                # 3.0 SQLite 事务升级强锁：抢占写锁规避高并发写死锁冲突
                cursor.execute("BEGIN IMMEDIATE;")
                
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
                    
                    # 城市智能解析与时空融合归一化判定
                    city = parse_city(event_place)
                    normalized_id = EventFusionService.find_or_create_normalized_event(
                        cursor, event_name, city, event_date, event_type
                    )
                    affected_norm_ids.add(normalized_id)
                    
                    # 判断当前活动是否为历史发生行程
                    is_historical = False
                    if re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
                        is_historical = event_date < current_date
                        
                    if is_historical:
                        # 历史行程冻结保护：仅当完全不存在相同活动且未被取消时才作为增量写入，绝不覆盖/删除历史
                        duplicate_history = False
                        for r_id, r_name, r_date, r_place, r_status, r_norm_id in existing_rows:
                            if r_name == event_name and r_date == event_date and r_place == event_place and r_status != '已取消':
                                duplicate_history = True
                                break
                        if not duplicate_history:
                            validate_status('未开始')
                            cursor.execute(
                                """
                                INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, status, normalized_event_id, event_type, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '未开始', ?, ?, ?);
                                """,
                                (raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, normalized_id, event_type, now_str)
                            )
                    else:
                        # 未来行程增量对齐合并 (Upsert)
                        key = (event_name, event_date, event_place)
                        new_future_keys.add(key)
                        
                        if key in existing_future_map:
                            # 存在：更新内容（描述、置信度、来源 URL 以及重新绑定的超级漫展外键）
                            db_id, old_norm_id = existing_future_map[key]
                            if old_norm_id:
                                affected_norm_ids.add(old_norm_id)
                            validate_status('未开始')
                            cursor.execute(
                                """
                                UPDATE cosplay_events
                                SET event_description = ?, confidence = ?, source_url = ?, status = '未开始', normalized_event_id = ?, event_type = ?
                                WHERE id = ?;
                                """,
                                (event_description, confidence, source_url, normalized_id, event_type, db_id)
                            )
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
                
                # 4. 软取消失效日程：将所有在最新分析中已消失的未来日程（已取消或已改期日程）的 status 更新为 '已取消'
                for key, (db_id, norm_id) in existing_future_map.items():
                    if key not in new_future_keys:
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
                
            return True
        except Exception as e:
            err_msg = f"写入活动及标记已分析失败，已触发事务回滚！原因: {e}"
            print(f"\x1b[1;31m[Database TRANSACTION ERROR] {err_msg}\x1b[0m")
            log_event("ERROR", "database_transaction", err_msg, str(e))
            return False
        finally:
            cursor.close()
            conn.close()
