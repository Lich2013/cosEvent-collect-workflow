import sqlite3
import datetime
from src.models.db_models import get_db_connection

class CoserRepository:
    @staticmethod
    def add_coser(name: str, weibo_uid: str = None, bilibili_uid: str = None, xhs_uid: str = None) -> bool:
        """新增 Coser"""
        conn = get_db_connection()
        cursor = conn.cursor()
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
