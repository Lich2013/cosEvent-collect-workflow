import sqlite3
import logging
import json
import datetime
from src.models.db_models import get_db_connection

from src.utils.logger import log_event

class DBService:
    @staticmethod
    def add_coser(name: str, weibo_uid: str = None, bilibili_uid: str = None, xhs_uid: str = None) -> bool:
        """新增 Coser"""
        conn = get_db_connection()
        cursor = conn.cursor()
        import datetime
        try:
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO cosers (name, weibo_uid, bilibili_uid, xhs_uid, created_at) VALUES (?, ?, ?, ?, ?);",
                (name, weibo_uid, bilibili_uid, xhs_uid, now_str)
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"\x1b[1;31m[Database ERROR] 新增 Coser 失败: {e}\x1b[0m")
            return False
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def list_cosers(only_active: bool = False) -> list[dict]:
        """获取 Coser 列表"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT id, name, weibo_uid, bilibili_uid, xhs_uid, is_active, created_at FROM cosers"
            if only_active:
                query += " WHERE is_active = 1"
            cursor.execute(query)
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "weibo_uid": r[2],
                    "bilibili_uid": r[3],
                    "xhs_uid": r[4],
                    "is_active": r[5],
                    "created_at": r[6]
                } for r in rows
            ]
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def update_coser(name: str, weibo_uid: str = None, bilibili_uid: str = None, xhs_uid: str = None, is_active: int = None) -> bool:
        """更新 Coser 属性或启用状态"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # 动态拼接更新字段
            fields = []
            params = []
            if weibo_uid is not None:
                fields.append("weibo_uid = ?")
                params.append(weibo_uid if weibo_uid != "" else None)
            if bilibili_uid is not None:
                fields.append("bilibili_uid = ?")
                params.append(bilibili_uid if bilibili_uid != "" else None)
            if xhs_uid is not None:
                fields.append("xhs_uid = ?")
                params.append(xhs_uid if xhs_uid != "" else None)
            if is_active is not None:
                fields.append("is_active = ?")
                params.append(is_active)
            
            if not fields:
                return False
                
            params.append(name)
            sql = f"UPDATE cosers SET {', '.join(fields)} WHERE name = ?;"
            cursor.execute(sql, tuple(params))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            print(f"\x1b[1;31m[Database ERROR] 更新 Coser 失败: {e}\x1b[0m")
            return False
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def delete_coser(name: str) -> bool:
        """删除 Coser 记录 (级联删除其 raw_posts 和 cosplay_events)"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM cosers WHERE name = ?;", (name,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            print(f"\x1b[1;31m[Database ERROR] 删除 Coser 失败: {e}\x1b[0m")
            return False
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def save_raw_posts(coser_id: int, platform: str, posts: list[dict]) -> int:
        """保存原始博文记录，实现版本号比对去重与二次编辑更新"""
        conn = get_db_connection()
        cursor = conn.cursor()
        inserted_count = 0
        import datetime
        try:
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
            for post in posts:
                post_id = post["post_id"]
                content = post["content"]
                post_url = post.get("post_url")
                edit_count = int(post.get("edit_count") or 0)
                published_at = post.get("published_at")

                base_post_id = post_id.split("#")[0]

                # 1. 查找该博文的最新已存版本以获取内容和版本信息
                cursor.execute(
                    """
                    SELECT id, post_id, edit_count, content FROM raw_posts
                    WHERE platform = ? AND (post_id = ? OR post_id LIKE ?)
                    ORDER BY edit_count DESC LIMIT 1;
                    """,
                    (platform, base_post_id, f"{base_post_id}#v%")
                )
                row = cursor.fetchone()

                if row:
                    stored_id, stored_post_id, stored_edit_count, stored_content = row
                    stored_edit_count = int(stored_edit_count or 0)

                    # B站/小红书自适应内容变动合成版本控制
                    if platform in ("bilibili", "xhs"):
                        if content != stored_content:
                            # 内容发生变化，虚拟递增版本号
                            edit_count = stored_edit_count + 1
                            versioned_post_id = f"{base_post_id}#v{edit_count}"
                            # 重锚北京抓取时间作为发布时间
                            published_at = now_str
                            
                            # 插入全新版本行
                            cursor.execute(
                                """
                                INSERT INTO raw_posts (coser_id, platform, post_id, content, post_url, edit_count, published_at, is_analyzed, scraped_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?);
                                """,
                                (coser_id, platform, versioned_post_id, content, post_url, edit_count, published_at, now_str)
                            )
                            inserted_count += 1
                    else:
                        # 微博等平台已在爬虫端计算好 post_id 后缀与 edit_count
                        # 如果是更新的版本，且该具体 post_id（如 123#v2）在库中完全不存在，则执行插入
                        if "#v" not in post_id:
                            # 兼容老测试用例：在 post_id 无后缀但 edit_count 提升时，执行原位更新
                            if edit_count > stored_edit_count:
                                cursor.execute(
                                    """
                                    UPDATE raw_posts
                                    SET content = ?, edit_count = ?, published_at = ?, is_analyzed = 0, scraped_at = ?
                                    WHERE id = ?;
                                    """,
                                    (content, edit_count, published_at, now_str, stored_id)
                                )
                                inserted_count += 1
                        else:
                            cursor.execute(
                                "SELECT id FROM raw_posts WHERE platform = ? AND post_id = ?;",
                                (platform, post_id)
                            )
                            if not cursor.fetchone():
                                cursor.execute(
                                    """
                                    INSERT INTO raw_posts (coser_id, platform, post_id, content, post_url, edit_count, published_at, is_analyzed, scraped_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?);
                                    """,
                                    (coser_id, platform, post_id, content, post_url, edit_count, published_at, now_str)
                                )
                                inserted_count += 1
                else:
                    # 全新博文，执行首次插入
                    cursor.execute(
                        """
                        INSERT INTO raw_posts (coser_id, platform, post_id, content, post_url, edit_count, published_at, is_analyzed, scraped_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?);
                        """,
                        (coser_id, platform, post_id, content, post_url, edit_count, published_at, now_str)
                    )
                    inserted_count += 1
            conn.commit()
            return inserted_count
        except Exception as e:
            conn.rollback()
            print(f"\x1b[1;31m[Database ERROR] 保存原始博文失败: {e}\x1b[0m")
            return 0
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_unanalyzed_posts() -> list[dict]:
        """获取所有未分析的增量原始博文"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, coser_id, platform, post_id, content, post_url, published_at, scraped_at 
                FROM raw_posts 
                WHERE is_analyzed = 0;
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "coser_id": r[1],
                    "platform": r[2],
                    "post_id": r[3],
                    "content": r[4],
                    "post_url": r[5],
                    "published_at": r[6],
                    "scraped_at": r[7]
                } for r in rows
            ]
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def save_extracted_events_transactional(raw_post_id: int, events: list[dict], confidence_threshold: float) -> bool:
        """
        核心原子事务控制：
        1. 获取真实 Coser 昵称 (注入 coser_name)
        2. 基于系统当前参考日期执行增量合并（时间轴分流）：
           - 历史活动日程（早于今日）进行冻结保护，只增不删。
           - 未来活动日程（大于等于今日/未知）执行增量合并（Upsert）与状态对齐物理清理（Delete）。
        3. 同步将对应的 raw_posts.is_analyzed 标志更新为 1
        4. 任何一步异常均由 sqlite3 标准连接上下文管理器管理回滚
        """
        import datetime
        import re
        
        # 状态列防御性校验
        def validate_status(status_val: str):
            assert status_val in ('未开始', '已结束', '已取消'), f"Status '{status_val}' is invalid!"

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
                "SELECT id, event_name, event_date, event_place, status FROM cosplay_events WHERE raw_post_id = ?;",
                (raw_post_id,)
            )
            existing_rows = cursor.fetchall()
            
            # 以当前日期为分流基准线，强行对齐到北京时间 (UTC+8)
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            current_date = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d")
            now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
            
            # 分离出已存未来行程的唯一键映射 {(name, date, place): id}
            existing_future_map = {}
            for r_id, r_name, r_date, r_place, r_status in existing_rows:
                if r_status != '已取消':
                    is_historical_r = False
                    if re.match(r"^\d{4}-\d{2}-\d{2}$", r_date):
                        is_historical_r = r_date < current_date
                    
                    if not is_historical_r:
                        existing_future_map[(r_name, r_date, r_place)] = r_id

            # 3. 利用 standard conn 管理上下文的自动 Commit/Rollback 原子事务
            with conn:
                # 3.1 批量软取消既往历史版本的未来有效行程
                if previous_version_ids:
                    validate_status('已取消')
                    placeholders = ",".join(["?"] * len(previous_version_ids))
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
                    
                    # 判断当前活动是否为历史发生行程
                    is_historical = False
                    if re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
                        is_historical = event_date < current_date
                        
                    if is_historical:
                        # 历史行程冻结保护：仅当完全不存在相同活动且未被取消时才作为增量写入，绝不覆盖/删除历史
                        duplicate_history = False
                        for r_id, r_name, r_date, r_place, r_status in existing_rows:
                            if r_name == event_name and r_date == event_date and r_place == event_place and r_status != '已取消':
                                duplicate_history = True
                                break
                        if not duplicate_history:
                            validate_status('未开始')
                            cursor.execute(
                                """
                                INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, status, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '未开始', ?);
                                """,
                                (raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, now_str)
                            )
                    else:
                        # 未来行程增量对齐合并 (Upsert)
                        key = (event_name, event_date, event_place)
                        new_future_keys.add(key)
                        
                        if key in existing_future_map:
                            # 存在：更新内容（描述、置信度和来源 URL）
                            db_id = existing_future_map[key]
                            validate_status('未开始')
                            cursor.execute(
                                """
                                UPDATE cosplay_events
                                SET event_description = ?, confidence = ?, source_url = ?, status = '未开始'
                                WHERE id = ?;
                                """,
                                (event_description, confidence, source_url, db_id)
                            )
                        else:
                            # 不存在：全新未来日程，执行插入
                            validate_status('未开始')
                            cursor.execute(
                                """
                                INSERT INTO cosplay_events (raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, status, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '未开始', ?);
                                """,
                                (raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, now_str)
                            )
                
                # 4. 软取消失效日程：将所有在最新分析中已消失的未来日程（已取消或已改期日程）的 status 更新为 '已取消'
                for key, db_id in existing_future_map.items():
                    if key not in new_future_keys:
                        validate_status('已取消')
                        cursor.execute(
                            "UPDATE cosplay_events SET status = '已取消' WHERE id = ?;",
                            (db_id,)
                        )
                
                # 5. 将对应博文标记为已分析 (is_analyzed = 1)
                cursor.execute(
                    "UPDATE raw_posts SET is_analyzed = 1 WHERE id = ?;",
                    (raw_post_id,)
                )
                
            return True
        except Exception as e:
            # 注意: with conn 上下文退出时如果抛出异常，Python 已经在底层执行了 conn.rollback()
            err_msg = f"写入活动及标记已分析失败，已触发事务回滚！原因: {e}"
            print(f"\x1b[1;31m[Database TRANSACTION ERROR] {err_msg}\x1b[0m")
            log_event("ERROR", "database_transaction", err_msg, str(e))
            return False
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_all_events(confidence_threshold: float = 0.0) -> list[dict]:
        """获取所有置信度高于阈值的有效活动"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, created_at
                FROM cosplay_events
                WHERE confidence >= ? AND status != '已取消'
                ORDER BY event_date ASC;
                """,
                (confidence_threshold,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "raw_post_id": r[1],
                    "coser_name": r[2],
                    "event_name": r[3],
                    "event_date": r[4],
                    "event_place": r[5],
                    "event_description": r[6],
                    "confidence": r[7],
                    "source_url": r[8],
                    "created_at": r[9]
                } for r in rows
            ]
        finally:
            cursor.close()
            conn.close()
