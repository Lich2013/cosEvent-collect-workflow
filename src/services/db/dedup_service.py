import sqlite3
import datetime
from src.models.db_models import get_db_connection
from src.services.fusion_service import EventFusionService
from src.utils.parsers import clean_event_name


class UnionFind:
    def __init__(self, elements):
        self.parent = {el: el for el in elements}

    def find(self, x):
        if self.parent[x] == x:
            return x
        self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x != root_y:
            # 较小 ID 的节点作为 Parent (Winner)
            if root_x < root_y:
                self.parent[root_y] = root_x
            else:
                self.parent[root_x] = root_y


def is_date_compatible(sA: str, eA: str, sB: str, eB: str) -> bool:
    """
    判断两个时间区间是否在 ±7 天内相容。
    若任何一方有未知时间（None 或 "未知"），视为相容（允许秒配）。
    """
    if not sA or sA == "未知" or not eA or eA == "未知":
        return True
    if not sB or sB == "未知" or not eB or eB == "未知":
        return True

    try:
        start_A = datetime.datetime.strptime(sA, "%Y-%m-%d").date()
        end_A = datetime.datetime.strptime(eA, "%Y-%m-%d").date()
        start_B = datetime.datetime.strptime(sB, "%Y-%m-%d").date()
        end_B = datetime.datetime.strptime(eB, "%Y-%m-%d").date()

        # 区间距离在 7 天内
        return (start_A - datetime.timedelta(days=7)) <= end_B and (start_B - datetime.timedelta(days=7)) <= end_A
    except Exception:
        return True


class DeduplicationService:
    @staticmethod
    def deduplicate_database() -> dict:
        """
        在单一 SQL 原子事务中实现基于 [city, name_slug, date_window (±7天)] 规则的存量冗余超级节点智能合并算法。
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        stats = {
            "processed_groups": 0,
            "merged_nodes": 0,
            "alias_redirects": 0,
            "alias_conflicts": 0,
            "deleted_nodes": 0
        }

        try:
            with conn:
                # SQLite 事务升级强锁，抢占写锁规避高并发写死锁冲突
                cursor.execute("BEGIN IMMEDIATE;")

                # 1. 查找所有 normalized_events
                cursor.execute("SELECT id, event_fingerprint, standard_name, city, start_date, end_date, event_type FROM normalized_events;")
                all_events = cursor.fetchall()

                # 2. 按照 (city, name_slug, event_type) 分组
                groups = {}
                for row in all_events:
                    c_id, fingerprint, standard_name, city, start_date, end_date, event_type = row
                    name_slug = clean_event_name(standard_name)
                    key = (city, name_slug, event_type)
                    groups.setdefault(key, []).append({
                        "id": c_id,
                        "fingerprint": fingerprint,
                        "standard_name": standard_name,
                        "city": city,
                        "start_date": start_date,
                        "end_date": end_date,
                        "event_type": event_type
                    })

                # 3. 对每个分组进行 ±7 天窗口的 Union-Find 聚类
                for key, events in groups.items():
                    if len(events) <= 1:
                        continue

                    stats["processed_groups"] += 1

                    # 初始化 UnionFind
                    event_ids = [e["id"] for e in events]
                    uf = UnionFind(event_ids)

                    # 两两进行时间相容性校验
                    for i in range(len(events)):
                        for j in range(i + 1, len(events)):
                            e1 = events[i]
                            e2 = events[j]
                            if is_date_compatible(e1["start_date"], e1["end_date"], e2["start_date"], e2["end_date"]):
                                uf.union(e1["id"], e2["id"])

                    # 按照聚类根节点（即 Winner）对 Losers 进行归类
                    clusters = {}
                    for e_id in event_ids:
                        root = uf.find(e_id)
                        clusters.setdefault(root, []).append(e_id)

                    # 执行物理去重逻辑
                    for winner_id, member_ids in clusters.items():
                        losers = [m for m in member_ids if m != winner_id]
                        if not losers:
                            continue

                        for loser_id in losers:
                            # a. 重定向 cosplay_events 日程记录
                            cursor.execute("UPDATE cosplay_events SET normalized_event_id = ? WHERE normalized_event_id = ?;", (winner_id, loser_id))
                            stats["merged_nodes"] += 1

                            # b. 级联重定向别名并处理冲突
                            cursor.execute("SELECT id, alias_name, city FROM event_aliases WHERE normalized_event_id = ?;", (loser_id,))
                            alias_rows = cursor.fetchall()
                            for alias_id, alias_name, city in alias_rows:
                                try:
                                    cursor.execute("UPDATE event_aliases SET normalized_event_id = ? WHERE id = ?;", (winner_id, alias_id))
                                    stats["alias_redirects"] += 1
                                except sqlite3.IntegrityError as e:
                                    # 冲突捕获，输出 [Spatial Rectification Audit] 警告审计日志
                                    print(f"\x1b[1;33m[Spatial Rectification Audit] UNIQUE constraint conflict during deduplication. Winner ID: {winner_id}, Loser ID: {loser_id}, Alias Name: '{alias_name}', City: '{city}'. Error: {e}\x1b[0m")
                                    # 安全物理删除 Loser 冲突别名行，杜绝 SQLite 主键死锁崩溃
                                    cursor.execute("DELETE FROM event_aliases WHERE id = ?;", (alias_id,))
                                    stats["alias_conflicts"] += 1

                            # c. 安全删除 Loser 节点，由 try-except sqlite3.IntegrityError 健壮保护
                            try:
                                cursor.execute("DELETE FROM normalized_events WHERE id = ?;", (loser_id,))
                                stats["deleted_nodes"] += 1
                            except sqlite3.IntegrityError as e:
                                print(f"\x1b[1;33m[Database Warning] Skipped deleting loser normalized_event ID {loser_id} due to IntegrityError: {e}\x1b[0m")

                        # d. 更新 Winner 节点的最宽举办日期区间
                        EventFusionService.update_event_bounding_box(cursor, winner_id)

            print(f"\x1b[1;32m[Deduplicate Success] 数据库去重已成功物理提交并应用！详情: {stats}\x1b[0m")
            return stats
        except Exception as e:
            print(f"\x1b[1;31m[Deduplicate Error] 数据库去重事务中途崩溃，已自动 ROLLBACK！错误: {e}\x1b[0m")
            raise e
