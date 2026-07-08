import sqlite3
from src.models.db_models import get_db_connection
from src.utils.logger import log_event
from src.utils.time import beijing_now_str

class CandidateRepository:
    """
    Coser 候选库仓储服务
    管理自动发现的 Coser 候选状态流转，与生产正式表物理隔离
    """

    @staticmethod
    def add_candidate(
        name: str, 
        platform: str, 
        source_ref: str = None, 
        matched_bili_uid: str = None, 
        matched_weibo_uid: str = None, 
        matched_xhs_uid: str = None, 
        match_score: float = 0.0,
        is_verified: int = 0,
        verify_reason: str = None
    ) -> bool:
        """新增 Coser 候选记录（已存在同名且处于 pending 状态时进行覆盖更新，若已 approved/ignored 则跳过）"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            now_str = beijing_now_str()
            
            # 先查询是否已存在此候选人
            cursor.execute("SELECT id, status FROM coser_candidates WHERE name = ?", (name,))
            row = cursor.fetchone()
            
            if row:
                cand_id, status = row
                if status in ("pending", "undetermined"):
                    # 查询既存属性以便合并，防止新扫描的空字段覆盖掉旧的有效 UID (Finding 5)
                    cursor.execute(
                        """
                        SELECT platform, source_ref, matched_bili_uid, matched_weibo_uid, matched_xhs_uid, match_score, is_verified, verify_reason 
                        FROM coser_candidates 
                        WHERE id = ?;
                        """,
                        (cand_id,)
                    )
                    exist_plat, exist_ref, exist_bili, exist_weibo, exist_xhs, exist_score, exist_verified, exist_reason = cursor.fetchone()
                    
                    merged_bili = matched_bili_uid if matched_bili_uid not in (None, "", "-") else exist_bili
                    merged_weibo = matched_weibo_uid if matched_weibo_uid not in (None, "", "-") else exist_weibo
                    merged_xhs = matched_xhs_uid if matched_xhs_uid not in (None, "", "-") else exist_xhs
                    merged_score = match_score if match_score > 0.0 else (exist_score or 0.0)
                    merged_ref = source_ref if source_ref else exist_ref
                    merged_plat = platform if platform else exist_plat
                    merged_verified = 1 if (is_verified == 1 or exist_verified == 1) else 0
                    merged_reason = verify_reason if verify_reason else exist_reason

                    cursor.execute(
                        """
                        UPDATE coser_candidates 
                        SET platform = ?, source_ref = ?, matched_bili_uid = ?, matched_weibo_uid = ?, matched_xhs_uid = ?, match_score = ?, is_verified = ?, verify_reason = ?, status = 'pending', status_updated_at = ?
                        WHERE id = ?;
                        """,
                        (merged_plat, merged_ref, merged_bili, merged_weibo, merged_xhs, merged_score, merged_verified, merged_reason, now_str, cand_id)
                    )
                    conn.commit()
                    return True
                else:
                    # 已经是 approved/ignored 状态，不作处理，返回 True 避免阻断主链路
                    return True
            
            # 全新记录直接插入
            cursor.execute(
                """
                INSERT INTO coser_candidates 
                (name, platform, source_ref, matched_bili_uid, matched_weibo_uid, matched_xhs_uid, match_score, status, is_verified, verify_reason, status_updated_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?);
                """,
                (name, platform, source_ref, matched_bili_uid, matched_weibo_uid, matched_xhs_uid, match_score, is_verified, verify_reason, now_str, now_str)
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            log_event("ERROR", "CandidateRepository", f"新增候选人 [{name}] 失败: {e}", str(e))
            return False
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def list_candidates(status: str = "pending") -> list[dict]:
        """按状态获取候选人列表"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, name, platform, source_ref, matched_bili_uid, matched_weibo_uid, matched_xhs_uid, match_score, status, is_verified, verify_reason, created_at
                FROM coser_candidates
                WHERE status = ?;
                """,
                (status,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "platform": r[2],
                    "source_ref": r[3],
                    "matched_bili_uid": r[4],
                    "matched_weibo_uid": r[5],
                    "matched_xhs_uid": r[6],
                    "match_score": r[7],
                    "status": r[8],
                    "is_verified": r[9],
                    "verify_reason": r[10],
                    "created_at": r[11]
                } for r in rows
            ]
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def approve_candidate(candidate_id: int) -> bool:
        """批准候选人，将其导入正式 cosers 表（原子性 SQL 事务，包含冲突验证）"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # 1. 查询候选人详情
            cursor.execute(
                """
                SELECT name, matched_bili_uid, matched_weibo_uid, matched_xhs_uid 
                FROM coser_candidates 
                WHERE id = ? AND status IN ('pending', 'undetermined');
                """,
                (candidate_id,)
            )
            row = cursor.fetchone()
            if not row:
                log_event("WARNING", "CandidateRepository", f"未找到 ID 为 {candidate_id} 且处于 pending 或 undetermined 状态的候选人")
                return False
                
            name, bili_uid, weibo_uid, xhs_uid = row
            
            # 1.5. 执行实体命名模糊碰撞及 UID 占用校验，记录警告至系统日志 (Finding 7)
            from src.services.db.coser_repository import CoserRepository
            warnings = CoserRepository.check_coser_duplicates(
                name=name, 
                weibo_uid=weibo_uid, 
                bilibili_uid=bili_uid, 
                xhs_uid=xhs_uid, 
                check_name_similarity=True
            )
            for warning in warnings:
                log_event("WARNING", "CandidateRepository", f"[Approve Conflict Check] {warning}")
            
            # 2. 插入或更新 cosers 表
            cursor.execute("SELECT id, bilibili_uid, weibo_uid, xhs_uid FROM cosers WHERE name = ?", (name,))
            exist_coser = cursor.fetchone()
            
            now_str = beijing_now_str()
            
            if exist_coser:
                coser_id, exist_bili, exist_weibo, exist_xhs = exist_coser
                
                # 合并函数：若原本值为空或占位减号，则允许被真实 UID 覆盖更新 (Finding 6)
                def merge_uid(existing, incoming):
                    if existing in (None, "", "-"):
                        return incoming if incoming not in (None, "", "-") else existing
                    return existing
                    
                new_bili = merge_uid(exist_bili, bili_uid)
                new_weibo = merge_uid(exist_weibo, weibo_uid)
                new_xhs = merge_uid(exist_xhs, xhs_uid)
                
                cursor.execute(
                    """
                    UPDATE cosers 
                    SET bilibili_uid = ?, weibo_uid = ?, xhs_uid = ?, is_active = 1
                    WHERE id = ?;
                    """,
                    (new_bili, new_weibo, new_xhs, coser_id)
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO cosers (name, weibo_uid, bilibili_uid, xhs_uid, is_active, created_at)
                    VALUES (?, ?, ?, ?, 1, ?);
                    """,
                    (name, weibo_uid, bili_uid, xhs_uid, now_str)
                )
                
            # 3. 标记候选人为 approved
            cursor.execute(
                "UPDATE coser_candidates SET status = 'approved', status_updated_at = ? WHERE id = ?;",
                (now_str, candidate_id)
            )
            
            # 4. 物理清理该候选人关联的临时博文数据
            cursor.execute(
                "DELETE FROM candidate_raw_posts WHERE candidate_id = ?;",
                (candidate_id,)
            )
            
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            log_event("ERROR", "CandidateRepository", f"批准候选人 ID {candidate_id} 失败: {e}", str(e))
            return False
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def reject_candidate(candidate_id: int) -> bool:
        """拒绝/忽略候选人，标记为 ignored"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            now_str = beijing_now_str()
            cursor.execute(
                "UPDATE coser_candidates SET status = 'ignored', status_updated_at = ? WHERE id = ? AND status IN ('pending', 'undetermined');",
                (now_str, candidate_id)
            )
            updated = cursor.rowcount > 0
            if updated:
                # 物理清理该候选人关联的临时博文数据
                cursor.execute(
                    "DELETE FROM candidate_raw_posts WHERE candidate_id = ?;",
                    (candidate_id,)
                )
            conn.commit()
            return updated
        except Exception as e:
            conn.rollback()
            log_event("ERROR", "CandidateRepository", f"忽略候选人 ID {candidate_id} 失败: {e}", str(e))
            return False
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def set_candidate_undetermined(candidate_id: int) -> bool:
        """将候选人标记为 undetermined，并物理清理该候选人关联的临时博文数据"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            now_str = beijing_now_str()
            cursor.execute(
                "UPDATE coser_candidates SET status = 'undetermined', status_updated_at = ? WHERE id = ? AND status = 'pending';",
                (now_str, candidate_id)
            )
            updated = cursor.rowcount > 0
            if updated:
                # 物理清理该候选人关联的临时博文数据
                cursor.execute(
                    "DELETE FROM candidate_raw_posts WHERE candidate_id = ?;",
                    (candidate_id,)
                )
            conn.commit()
            return updated
        except Exception as e:
            conn.rollback()
            log_event("ERROR", "CandidateRepository", f"标记候选人 ID {candidate_id} 为待定失败: {e}", str(e))
            return False
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def save_candidate_raw_posts(candidate_id: int, platform: str, posts: list[dict]) -> int:
        """物理隔离保存候选人的博文数据"""
        conn = get_db_connection()
        cursor = conn.cursor()
        inserted_count = 0
        try:
            now_str = beijing_now_str()
            for post in posts:
                post_id = post["post_id"]
                content = post["content"]
                post_url = post.get("post_url")
                published_at = post.get("published_at")

                # 插入并且去重
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO candidate_raw_posts 
                    (candidate_id, platform, post_id, content, post_url, published_at, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (candidate_id, platform, post_id, content, post_url, published_at, now_str)
                )
                if cursor.rowcount > 0:
                    inserted_count += 1
            conn.commit()
            return inserted_count
        except Exception as e:
            conn.rollback()
            log_event("ERROR", "CandidateRepository", f"保存候选人博文失败: {e}", str(e))
            return 0
        finally:
            cursor.close()
            conn.close()
