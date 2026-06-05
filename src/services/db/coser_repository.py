import sqlite3
import datetime
from src.models.db_models import get_db_connection
from src.utils.logger import log_event

class CoserRepository:
    @staticmethod
    def check_coser_duplicates(
        name: str, 
        weibo_uid: str = None, 
        bilibili_uid: str = None, 
        xhs_uid: str = None, 
        exclude_name: str = None, 
        check_name_similarity: bool = True
    ) -> list[str]:
        """检查 Coser 名字相似度与平台 UID 占用冲突，返回警告信息列表"""
        import re
        import difflib

        warnings = []
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # 1. 名字相似度校验（仅在启用姓名检查且 name 不为空时）
            if check_name_similarity and name:
                cursor.execute("SELECT name FROM cosers")
                exist_names = [row[0] for row in cursor.fetchall()]

                def clean_name(s: str) -> str:
                    if not s:
                        return ""
                    return re.sub(r"[\s\-\_\,\.\!\?\#\&\*\/]", "", s).lower()

                cleaned_input = clean_name(name)
                for exist_name in exist_names:
                    if exclude_name and exist_name == exclude_name:
                        continue
                        
                    cleaned_exist = clean_name(exist_name)
                    is_similar = False
                    
                    # (1) 归一化比对
                    if cleaned_input == cleaned_exist:
                        is_similar = True
                    # (2) 子串包含判定（较短方长度 >= 2）
                    elif cleaned_input and cleaned_exist:
                        shorter_len = min(len(cleaned_input), len(cleaned_exist))
                        if shorter_len >= 2:
                            if cleaned_input in cleaned_exist or cleaned_exist in cleaned_input:
                                is_similar = True
                    
                    # (3) difflib 相似度比对
                    if not is_similar and cleaned_input and cleaned_exist:
                        ratio = difflib.SequenceMatcher(None, cleaned_input, cleaned_exist).ratio()
                        if ratio >= 0.7:
                            is_similar = True
                            
                    if is_similar:
                        warnings.append(f"⚠️ [警告] 名字相似度碰撞：新指定的 Coser 姓名 '{name}' 与已存在的 Coser '{exist_name}' 相似！")

            # 2. 多平台 UID 占用冲突校验（在 SQL 层 O(1) 进行匹配）
            uids_to_check = {
                "weibo": weibo_uid,
                "bilibili": bilibili_uid,
                "xhs": xhs_uid
            }
            
            for platform, uid in uids_to_check.items():
                if uid is None:
                    continue
                uid_str = str(uid).strip()
                if not uid_str or uid_str in ("", "-"):
                    continue
                
                sql = f"SELECT name FROM cosers WHERE TRIM({platform}_uid) = ? AND name != ?"
                cursor.execute(sql, (uid_str, exclude_name or ""))
                rows = cursor.fetchall()
                for row in rows:
                    warnings.append(f"⚠️ [警告] 平台 UID 冲突检测：新指定的 {platform}_uid '{uid_str}' 已被 Coser [{row[0]}] 绑定！")
                    
            return warnings
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def add_coser(name: str, weibo_uid: str = None, bilibili_uid: str = None, xhs_uid: str = None) -> bool:
        """新增 Coser"""
        # 前置校验名字相似度与平台 UID 占用冲突，并将警报写入日志
        warnings = CoserRepository.check_coser_duplicates(name, weibo_uid, bilibili_uid, xhs_uid, check_name_similarity=True)
        for warning in warnings:
            log_event("WARNING", "CoserRepository", warning)

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
    def list_cosers(only_active: bool = False, conn=None) -> list[dict]:
        """获取所有追踪的 Coser 列表"""
        local_conn = conn or get_db_connection()
        cursor = local_conn.cursor()
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
            if not conn:
                local_conn.close()

    @staticmethod
    def list_active_cosers_by_schedule(platform: str, limit: int, conn=None) -> list[dict]:
        """根据滑动窗口调度算法获取当前平台最久未被爬取的活跃 Coser 列表"""
        if platform not in ("weibo", "bilibili", "xhs"):
            raise ValueError(f"Invalid platform: {platform}")
        local_conn = conn or get_db_connection()
        cursor = local_conn.cursor()
        try:
            platform_uid_col = f"{platform}_uid"
            query = f"""
                SELECT c.id, c.name, c.weibo_uid, c.bilibili_uid, c.xhs_uid, c.is_active, c.created_at
                FROM cosers c
                LEFT JOIN coser_scrape_state s 
                  ON c.id = s.coser_id AND s.platform = ?
                WHERE c.is_active = 1 
                  AND c.{platform_uid_col} IS NOT NULL 
                  AND c.{platform_uid_col} != '' 
                  AND c.{platform_uid_col} != '-'
                ORDER BY s.last_scraped_at ASC
                LIMIT ?;
            """
            cursor.execute(query, (platform, limit))
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
            if not conn:
                local_conn.close()

    @staticmethod
    def update_scrape_timestamp(coser_id: int, platform: str, conn=None) -> bool:
        """更新对应平台的爬取时间戳，采用 INSERT OR REPLACE 逻辑支持首次写入"""
        if platform not in ("weibo", "bilibili", "xhs"):
            raise ValueError(f"Invalid platform: {platform}")
        local_conn = conn or get_db_connection()
        cursor = local_conn.cursor()
        try:
            import datetime
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            now_str = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                """
                INSERT OR REPLACE INTO coser_scrape_state (coser_id, platform, last_scraped_at)
                VALUES (?, ?, ?);
                """,
                (coser_id, platform, now_str)
            )
            local_conn.commit()
            return True
        except Exception as e:
            local_conn.rollback()
            print(f"\x1b[1;31m[Database ERROR] 更新爬取时间戳失败: {e}\x1b[0m")
            return False
        finally:
            cursor.close()
            if not conn:
                local_conn.close()


    @staticmethod
    def get_active_cosers_without_bilibili() -> list[dict]:
        """获取所有未绑定 B站 UID 且处于激活状态的 Coser 列表"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, name, weibo_uid, bilibili_uid, xhs_uid, is_active, created_at 
                FROM cosers
                WHERE is_active = 1 AND (bilibili_uid IS NULL OR bilibili_uid = '' OR bilibili_uid = '-');
                """
            )
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
        # 前置校验平台 UID 占用冲突（排除当前 Coser 自己，且不校验名字相似度）
        warnings = CoserRepository.check_coser_duplicates(name, weibo_uid, bilibili_uid, xhs_uid, exclude_name=name, check_name_similarity=False)
        for warning in warnings:
            log_event("WARNING", "CoserRepository", warning)

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
    def save_raw_posts(coser_id: int, platform: str, posts: list[dict], conn=None) -> int:
        """保存原始博文记录，实现版本号比对去重与二次编辑更新"""
        local_conn = conn or get_db_connection()
        cursor = local_conn.cursor()
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

                # 1. 查找该博文的最新已存版本以获取内容、版本信息及发布/编辑时间
                cursor.execute(
                    """
                    SELECT id, post_id, edit_count, content, published_at FROM raw_posts
                    WHERE platform = ? AND (post_id = ? OR post_id LIKE ?)
                    ORDER BY edit_count DESC LIMIT 1;
                    """,
                    (platform, base_post_id, f"{base_post_id}#v%")
                )
                row = cursor.fetchone()

                if row:
                    stored_id, stored_post_id, stored_edit_count, stored_content, stored_published_at = row
                    stored_edit_count = int(stored_edit_count or 0)

                    # B站 gRPC 模式下的物理版本控制
                    if platform == "bilibili" and post.get("is_grpc"):
                        if post.get("is_edited", False):
                            # 如果是编辑过的版本，且物理编辑时间不同，则递增版本号插入新版
                            if published_at != stored_published_at:
                                edit_count = stored_edit_count + 1
                                versioned_post_id = f"{base_post_id}#v{edit_count}"
                                cursor.execute(
                                    """
                                    INSERT INTO raw_posts (coser_id, platform, post_id, content, post_url, edit_count, published_at, is_analyzed, scraped_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?);
                                    """,
                                    (coser_id, platform, versioned_post_id, content, post_url, edit_count, published_at, now_str)
                                )
                                inserted_count += 1
                        # 若未编辑但内容发生了更新（处理 B站不报 is_edited 且不改时间戳的幽灵置顶编辑行为）
                        elif not post.get("is_edited", False) and content != stored_content:
                            # 既然内容变了，说明一定是编辑过。生成全新虚拟版本行，重锚当前抓取时间作为发布时间，以便 AI Agent 准确定位年份
                            edit_count = stored_edit_count + 1
                            versioned_post_id = f"{base_post_id}#v{edit_count}"
                            cursor.execute(
                                """
                                INSERT INTO raw_posts (coser_id, platform, post_id, content, post_url, edit_count, published_at, is_analyzed, scraped_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?);
                                """,
                                (coser_id, platform, versioned_post_id, content, post_url, edit_count, now_str, now_str)
                            )
                            inserted_count += 1
                        # 若未编辑且物理编辑时间、内容完全相同，则作为重复记录直接过滤去重
                        elif not post.get("is_edited", False) and published_at and published_at != stored_published_at:
                            cursor.execute(
                                "UPDATE raw_posts SET published_at = ?, scraped_at = ? WHERE id = ?;",
                                (published_at, now_str, stored_id)
                            )
                    # B站 Playwright 模式与小红书以及所有平台的虚拟 Bio 动态的自适应内容变动合成版本控制
                    elif platform == "xhs" or (platform == "bilibili" and not post.get("is_grpc")) or post_id.startswith("bio_"):
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
            local_conn.commit()
            return inserted_count
        except Exception as e:
            local_conn.rollback()
            print(f"\x1b[1;31m[Database ERROR] 保存原始博文失败: {e}\x1b[0m")
            return 0
        finally:
            cursor.close()
            if not conn:
                local_conn.close()

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
