import sqlite3
import datetime
import hashlib
import json
import os
import difflib
from src.models.db_models import get_db_connection
from src.utils.parsers import parse_city, clean_event_name


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
            # 使用较小 ID 作为 Parent，确保聚类代表性稳定
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

        return (start_A - datetime.timedelta(days=7)) <= end_B and (start_B - datetime.timedelta(days=7)) <= end_A
    except Exception:
        return True


class MaterializeService:
    @staticmethod
    def generate_deterministic_id(city: str, name_slug: str, event_type: str, date_bucket: str) -> str:
        """
        通过对事件的核心特征生成 MD5 确定性哈希，杜绝自增主键抖动。
        """
        payload = f"{city.lower()}_{name_slug}_{event_type}_{date_bucket}"
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def rebuild_view() -> dict:
        """
        全量/滑动窗口物化视图重建核心服务层：
        1. 划分冷热数据区间，已冻结的历史展示节点和关联事实表不做重建修改。
        2. 对热区间内（未来和近期未知）的活跃排班进行内存级 Gated 融合聚类。
        3. 利用 BEGIN IMMEDIATE 在单一 SQL 原子事务中清空热区展示数据，批量重写新行与 mappings 关联。
        4. 级联审计日志并对即将过期的活跃展会进行自动冻结归档。
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        stats = {
            "frozen_nodes": 0,
            "active_schedules": 0,
            "mapped_to_frozen": 0,
            "new_clusters": 0,
            "new_normalized_nodes": 0,
            "newly_frozen_nodes": 0
        }

        audit_log = {
            "timestamp": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
            "frozen_nodes": [],
            "new_clusters": []
        }

        try:
            # 1. 查找所有已被冻结的历史超级展示节点
            cursor.execute("SELECT id, event_fingerprint, standard_name, city, start_date, end_date, event_type FROM final_exhibition_view WHERE is_frozen = 1;")
            frozen_rows = cursor.fetchall()
            stats["frozen_nodes"] = len(frozen_rows)

            frozen_nodes = []
            frozen_ids = set()
            for r in frozen_rows:
                frozen_ids.add(r[0])
                fn = {
                    "id": r[0],
                    "fingerprint": r[1],
                    "standard_name": r[2],
                    "city": r[3],
                    "start_date": r[4],
                    "end_date": r[5],
                    "event_type": r[6],
                    "name_slug": clean_event_name(r[2])
                }
                frozen_nodes.append(fn)
                audit_log["frozen_nodes"].append(fn)

            # 2. 查出当前已绑定的 mapping 关系
            cursor.execute("SELECT raw_event_id, normalized_event_id FROM event_mappings;")
            mappings = {r[0]: r[1] for r in cursor.fetchall()}

            # 3. 捞取 cosplay_events 事实表中的所有未取消日程日程
            cursor.execute(
                """
                SELECT ce.id, ce.coser_name, ce.event_name, ce.event_date, ce.event_place, ce.event_description, ce.confidence, ce.source_url, ce.status, ce.event_type, ce.created_at, rp.published_at
                FROM cosplay_events ce
                JOIN raw_posts rp ON ce.raw_post_id = rp.id
                WHERE ce.status != '已取消';
                """
            )
            all_schedules = []
            for r in cursor.fetchall():
                all_schedules.append({
                    "id": r[0],
                    "coser_name": r[1],
                    "event_name": r[2],
                    "event_date": r[3],
                    "event_place": r[4],
                    "event_description": r[5],
                    "confidence": r[6],
                    "source_url": r[7],
                    "status": r[8],
                    "event_type": r[9],
                    "created_at": r[10],
                    "published_at": r[11],
                    "parsed_city": parse_city(r[4]),
                    "name_slug": clean_event_name(r[2])
                })

            # 4. 滑动窗口临界点
            today = datetime.date.today()
            t_cold = today - datetime.timedelta(days=30)
            t_cold_str = t_cold.strftime("%Y-%m-%d")

            # 5. 日程事实筛选分流：过滤出活跃（非冷冻）日程
            active_schedules = []
            for sch in all_schedules:
                # 检查此日程是否已绑定至某个已冻结的超级展示节点
                bound_node_id = mappings.get(sch["id"])
                if bound_node_id and bound_node_id in frozen_ids:
                    stats["mapped_to_frozen"] += 1
                    continue
                
                # 若未绑定至冻结节点，双重检查它本身是否已属于需冷冻的旧日程（防止冷冻追溯遗漏）
                is_old_concrete = sch["event_date"] != "未知" and sch["event_date"] < t_cold_str
                is_old_unknown = sch["event_date"] == "未知" and sch["published_at"] and sch["published_at"] < t_cold_str
                
                # 如果这个日程非常古老，但在上一次物化重建时未生成任何冻结节点，这次依然将其拉入计算重新生成
                active_schedules.append(sch)

            stats["active_schedules"] = len(active_schedules)

            # 6. 加载别名表缓存，以便进行别名确权秒配
            cursor.execute("SELECT alias_name, city, normalized_event_id FROM event_aliases;")
            alias_cache = {}
            for alias_name, city, ne_id in cursor.fetchall():
                alias_cache[(city, alias_name)] = ne_id

            # 7. 冷热边界比对：将活跃日程与既存冷冻节点比对
            remaining_schedules = []
            schedule_to_frozen_mapping = {}

            for sch in active_schedules:
                matched_frozen_id = None
                for fn in frozen_nodes:
                    if fn["city"] == sch["parsed_city"] and fn["event_type"] == sch["event_type"]:
                        # 检查时间区间与名称相似度
                        if is_date_compatible(sch["event_date"], sch["event_date"], fn["start_date"], fn["end_date"]):
                            ratio = difflib.SequenceMatcher(None, sch["name_slug"], fn["name_slug"]).ratio()
                            alias_match = (
                                alias_cache.get((sch["parsed_city"], sch["name_slug"])) == fn["id"] or
                                alias_cache.get((fn["city"], fn["name_slug"])) == fn["id"]
                            )
                            if sch["name_slug"] == fn["name_slug"] or ratio >= 0.75 or alias_match:
                                matched_frozen_id = fn["id"]
                                break
                
                if matched_frozen_id:
                    schedule_to_frozen_mapping[sch["id"]] = matched_frozen_id
                    stats["mapped_to_frozen"] += 1
                else:
                    remaining_schedules.append(sch)

            # 8. 内存级 Union-Find Gated 聚类（针对热活跃日程）
            # 8.1 将待处理日程划分为具体城市日程与“未知”城市日程
            concrete_schedules = [s for s in remaining_schedules if s["parsed_city"] != "未知"]
            unknown_schedules = [s for s in remaining_schedules if s["parsed_city"] == "未知"]

            new_mappings_dict = {}
            new_normalized_nodes = []

            # 8.2 对具体城市日程进行并查集聚类
            concrete_pools = {}
            for sch in concrete_schedules:
                key = (sch["parsed_city"], sch["event_type"])
                concrete_pools.setdefault(key, []).append(sch)

            for key, pool in concrete_pools.items():
                parsed_city, event_type = key
                schedule_ids = [s["id"] for s in pool]
                uf = UnionFind(schedule_ids)

                # 两两比对进行 Gated 时空聚类
                for i in range(len(pool)):
                    for j in range(i + 1, len(pool)):
                        s1 = pool[i]
                        s2 = pool[j]
                        if is_date_compatible(s1["event_date"], s1["event_date"], s2["event_date"], s2["event_date"]):
                            ratio = difflib.SequenceMatcher(None, s1["name_slug"], s2["name_slug"]).ratio()
                            alias_match = (
                                alias_cache.get((s1["parsed_city"], s1["name_slug"])) == alias_cache.get((s2["parsed_city"], s2["name_slug"]))
                                and alias_cache.get((s1["parsed_city"], s1["name_slug"])) is not None
                            )
                            if s1["name_slug"] == s2["name_slug"] or ratio >= 0.75 or alias_match:
                                uf.union(s1["id"], s2["id"])

                # 提取聚类群组
                clusters = {}
                for s_id in schedule_ids:
                    root = uf.find(s_id)
                    clusters.setdefault(root, []).append(s_id)

                stats["new_clusters"] += len(clusters)

                # 逐个聚类生成确定性超级节点
                for root_id, member_ids in clusters.items():
                    cluster_schedules = [s for s in pool if s["id"] in member_ids]
                    
                    # 选取 ID 最小的作为代表名称
                    rep_schedule = min(cluster_schedules, key=lambda s: s["id"])
                    rep_name = rep_schedule["event_name"]
                    name_slug = clean_event_name(rep_name)

                    # 计算最宽日期区间
                    concrete_dates = [s["event_date"] for s in cluster_schedules if s["event_date"] != "未知"]
                    if concrete_dates:
                        start_date = min(concrete_dates)
                        end_date = max(concrete_dates)
                        try:
                            dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
                            date_bucket = dt.strftime("%Y-W%W")
                        except Exception:
                            date_bucket = start_date
                    else:
                        start_date = "未知"
                        end_date = "未知"
                        date_bucket = "未知"

                    # 计算确定性 MD5 主键 ID
                    winner_id = MaterializeService.generate_deterministic_id(parsed_city, name_slug, event_type, date_bucket)

                    # 判定该超级展示节点是否达到冷冻线
                    is_frozen = 0
                    if concrete_dates:
                        if end_date < t_cold_str:
                            is_frozen = 1
                            stats["newly_frozen_nodes"] += 1
                    else:
                        # 均为未知时间日程，以最晚的博文发布时间为判定
                        max_pub = max([s["published_at"] for s in cluster_schedules if s["published_at"]])
                        if max_pub and max_pub < t_cold_str:
                            is_frozen = 1
                            stats["newly_frozen_nodes"] += 1

                    new_normalized_nodes.append({
                        "id": winner_id,
                        "standard_name": rep_name,
                        "city": parsed_city,
                        "start_date": start_date if start_date != "未知" else None,
                        "end_date": end_date if end_date != "未知" else None,
                        "event_type": event_type,
                        "is_frozen": is_frozen
                    })

                    # 记录映射
                    for s_id in member_ids:
                        new_mappings_dict[s_id] = winner_id

                    # 记录审计日志
                    audit_log["new_clusters"].append({
                        "deterministic_id": winner_id,
                        "standard_name": rep_name,
                        "city": parsed_city,
                        "event_type": event_type,
                        "start_date": start_date,
                        "end_date": end_date,
                        "is_frozen": is_frozen,
                        "schedules": [
                            {"id": s["id"], "coser_name": s["coser_name"], "event_name": s["event_name"], "event_date": s["event_date"]}
                            for s in cluster_schedules
                        ]
                    })

            # 8.3 动态融合构建全局具体城市对照超级节点索引池
            all_concrete_nodes = []
            for fn in frozen_nodes:
                if fn["city"] != "未知":
                    all_concrete_nodes.append(fn)

            for node in new_normalized_nodes:
                if node["city"] != "未知":
                    all_concrete_nodes.append({
                        "id": node["id"],
                        "standard_name": node["standard_name"],
                        "city": node["city"],
                        "start_date": node["start_date"],
                        "end_date": node["end_date"],
                        "event_type": node["event_type"],
                        "name_slug": clean_event_name(node["standard_name"])
                    })

            # 8.4 对所有未知城市的活跃日程进行自愈归位扫描比对 (时空匹配纠偏)
            remaining_unknown_schedules = []

            for sch in unknown_schedules:
                matched_concrete_id = None
                for cn in all_concrete_nodes:
                    if cn["event_type"] == sch["event_type"]:
                        # 校验时间窗口相容性与名字相似度
                        if is_date_compatible(sch["event_date"], sch["event_date"], cn["start_date"], cn["end_date"]):
                            ratio = difflib.SequenceMatcher(None, sch["name_slug"], cn["name_slug"]).ratio()
                            alias_match = (
                                alias_cache.get((cn["city"], sch["name_slug"])) == cn["id"] or
                                alias_cache.get((cn["city"], cn["name_slug"])) == cn["id"]
                            )
                            if sch["name_slug"] == cn["name_slug"] or ratio >= 0.75 or alias_match:
                                matched_concrete_id = cn["id"]
                                break
                
                if matched_concrete_id:
                    # 成功完成离线空间纠偏，直接绑定至具体城市超级展示节点
                    new_mappings_dict[sch["id"]] = matched_concrete_id
                    stats["mapped_to_frozen"] += 1
                else:
                    # 未匹配成功，保留在未知日程池中进入下一步的兜底聚类
                    remaining_unknown_schedules.append(sch)

            # 8.5 对未能合并的“未知”城市日程运行兜底聚类
            unknown_pools = {}
            for sch in remaining_unknown_schedules:
                key = (sch["parsed_city"], sch["event_type"])
                unknown_pools.setdefault(key, []).append(sch)

            for key, pool in unknown_pools.items():
                parsed_city, event_type = key
                schedule_ids = [s["id"] for s in pool]
                uf = UnionFind(schedule_ids)

                for i in range(len(pool)):
                    for j in range(i + 1, len(pool)):
                        s1 = pool[i]
                        s2 = pool[j]
                        if is_date_compatible(s1["event_date"], s1["event_date"], s2["event_date"], s2["event_date"]):
                            ratio = difflib.SequenceMatcher(None, s1["name_slug"], s2["name_slug"]).ratio()
                            alias_match = (
                                alias_cache.get((s1["parsed_city"], s1["name_slug"])) == alias_cache.get((s2["parsed_city"], s2["name_slug"]))
                                and alias_cache.get((s1["parsed_city"], s1["name_slug"])) is not None
                            )
                            if s1["name_slug"] == s2["name_slug"] or ratio >= 0.75 or alias_match:
                                uf.union(s1["id"], s2["id"])

                clusters = {}
                for s_id in schedule_ids:
                    root = uf.find(s_id)
                    clusters.setdefault(root, []).append(s_id)

                stats["new_clusters"] += len(clusters)

                for root_id, member_ids in clusters.items():
                    cluster_schedules = [s for s in pool if s["id"] in member_ids]
                    
                    rep_schedule = min(cluster_schedules, key=lambda s: s["id"])
                    rep_name = rep_schedule["event_name"]
                    name_slug = clean_event_name(rep_name)

                    concrete_dates = [s["event_date"] for s in cluster_schedules if s["event_date"] != "未知"]
                    if concrete_dates:
                        start_date = min(concrete_dates)
                        end_date = max(concrete_dates)
                        try:
                            dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
                            date_bucket = dt.strftime("%Y-W%W")
                        except Exception:
                            date_bucket = start_date
                    else:
                        start_date = "未知"
                        end_date = "未知"
                        date_bucket = "未知"

                    winner_id = MaterializeService.generate_deterministic_id(parsed_city, name_slug, event_type, date_bucket)

                    is_frozen = 0
                    if concrete_dates:
                        if end_date < t_cold_str:
                            is_frozen = 1
                            stats["newly_frozen_nodes"] += 1
                    else:
                        max_pub = max([s["published_at"] for s in cluster_schedules if s["published_at"]])
                        if max_pub and max_pub < t_cold_str:
                            is_frozen = 1
                            stats["newly_frozen_nodes"] += 1

                    new_normalized_nodes.append({
                        "id": winner_id,
                        "standard_name": rep_name,
                        "city": parsed_city,
                        "start_date": start_date if start_date != "未知" else None,
                        "end_date": end_date if end_date != "未知" else None,
                        "event_type": event_type,
                        "is_frozen": is_frozen
                    })

                    for s_id in member_ids:
                        new_mappings_dict[s_id] = winner_id

                    audit_log["new_clusters"].append({
                        "deterministic_id": winner_id,
                        "standard_name": rep_name,
                        "city": parsed_city,
                        "event_type": event_type,
                        "start_date": start_date,
                        "end_date": end_date,
                        "is_frozen": is_frozen,
                        "schedules": [
                            {"id": s["id"], "coser_name": s["coser_name"], "event_name": s["event_name"], "event_date": s["event_date"]}
                            for s in cluster_schedules
                        ]
                    })

            stats["new_normalized_nodes"] = len(new_normalized_nodes)

            # 9. 原子 SQL 事务写入隔离
            with conn:
                cursor.execute("BEGIN IMMEDIATE;")

                # 9.1 清空物化表中的热活跃节点 (只保留 is_frozen = 1 的节点)
                cursor.execute("DELETE FROM final_exhibition_view WHERE is_frozen = 0;")

                # 9.2 写入新生成的超级物化节点
                now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                for node in new_normalized_nodes:
                    fingerprint = f"{node['city'].lower()}_{clean_event_name(node['standard_name'])}"
                    
                    # 避免唯一约束冲突，加上随机指纹偏移
                    base_fp = fingerprint
                    counter = 1
                    while True:
                        cursor.execute("SELECT id FROM final_exhibition_view WHERE event_fingerprint = ? AND id != ?;", (fingerprint, node["id"]))
                        if not cursor.fetchone():
                            break
                        fingerprint = f"{base_fp}_{counter}"
                        counter += 1

                    cursor.execute(
                        """
                        INSERT INTO final_exhibition_view (id, event_fingerprint, standard_name, city, start_date, end_date, event_type, is_frozen, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            standard_name = excluded.standard_name,
                            start_date = excluded.start_date,
                            end_date = excluded.end_date,
                            is_frozen = excluded.is_frozen;
                        """,
                        (node["id"], fingerprint, node["standard_name"], node["city"], node["start_date"], node["end_date"], node["event_type"], node["is_frozen"], now_str)
                    )

                # 9.3 清理非冻结日程的关系映射
                # 收集所有新生成的映射和冷热交界重定向映射
                final_mappings = {}
                final_mappings.update(schedule_to_frozen_mapping)
                final_mappings.update(new_mappings_dict)

                # 清理已重新映射日程在 event_mappings 中的老记录
                if final_mappings:
                    raw_ids_placeholders = ",".join(["?"] * len(final_mappings))
                    cursor.execute(
                        f"DELETE FROM event_mappings WHERE raw_event_id IN ({raw_ids_placeholders});",
                        tuple(final_mappings.keys())
                    )

                    # 批量写入新 mappings
                    for raw_id, norm_id in final_mappings.items():
                        cursor.execute(
                            """
                            INSERT INTO event_mappings (raw_event_id, normalized_event_id, created_at)
                            VALUES (?, ?, ?);
                            """,
                            (raw_id, norm_id, now_str)
                        )

            # 10. 输出归并轨迹审计日志
            os.makedirs("runtime/logs", exist_ok=True)
            with open("runtime/logs/materialize_audit.json", "w", encoding="utf-8") as f:
                json.dump(audit_log, f, ensure_ascii=False, indent=2)

            print(f"\x1b[1;32m[Materialize View] 物化展示表重建成功完成！详情: {stats}\x1b[0m")
            return stats
        except Exception as e:
            print(f"\x1b[1;31m[Materialize Error] 物化重建中途崩溃，已自动 ROLLBACK！错误: {e}\x1b[0m")
            raise e
        finally:
            cursor.close()
            conn.close()
