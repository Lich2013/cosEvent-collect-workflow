import sqlite3
import datetime
import hashlib
import json
import os
from src.models.db_models import get_db_connection
from src.utils.parsers import parse_city, clean_event_name


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
        全量/滑动窗口物化视图重建核心服务层（重构版）：
        1. 划分冷热数据区间，已冻结的历史展示节点和关联事实表不做重建修改。
        2. 以旧轨 normalized_event_id 为权威分组键，直接信任 Fusion Engine 已完成的判定结果，
           取代原有 Union-Find 两两相似度比对方案，从根本上消除物化层与融合层的语义不一致。
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

            frozen_ids = set()
            for r in frozen_rows:
                frozen_ids.add(r[0])
                audit_log["frozen_nodes"].append({
                    "id": r[0], "standard_name": r[2], "city": r[3],
                    "start_date": r[4], "end_date": r[5], "event_type": r[6]
                })

            # 2. 查出当前已绑定的 mapping 关系
            cursor.execute("SELECT raw_event_id, normalized_event_id FROM event_mappings;")
            mappings = {r[0]: r[1] for r in cursor.fetchall()}

            # 3. 捞取所有活跃日程，LEFT JOIN 旧轨归一化节点获取权威名称与城市信息（添加 ce.id ASC 稳定排序保障）
            cursor.execute(
                """
                SELECT
                    ce.id, ce.coser_name, ce.event_name, ce.event_date, ce.event_place,
                    ce.event_description, ce.confidence, ce.source_url, ce.status,
                    ce.event_type, ce.created_at, ce.normalized_event_id,
                    rp.published_at,
                    ne.standard_name AS ne_standard_name,
                    ne.city AS ne_city,
                    ne.event_type AS ne_event_type
                FROM cosplay_events ce
                JOIN raw_posts rp ON ce.raw_post_id = rp.id
                LEFT JOIN normalized_events ne ON ce.normalized_event_id = ne.id
                WHERE ce.status != '已取消'
                ORDER BY ce.id ASC;
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
                    "normalized_event_id": r[11],
                    "published_at": r[12],
                    # 旧轨权威字段（ne.*），若 normalized_event_id 为 NULL 则降级使用 ce 字段兜底
                    "canonical_name": r[13] or r[2],
                    "canonical_city": r[14] or parse_city(r[4]),
                    "canonical_event_type": r[15] or r[9],
                })

            # 4. 滑动窗口临界点
            today = datetime.date.today()
            t_cold = today - datetime.timedelta(days=30)
            t_cold_str = t_cold.strftime("%Y-%m-%d")

            # 5. 日程分流：跳过已绑定至冻结节点的日程
            active_schedules = []
            for sch in all_schedules:
                bound_node_id = mappings.get(sch["id"])
                if bound_node_id and bound_node_id in frozen_ids:
                    stats["mapped_to_frozen"] += 1
                    continue
                active_schedules.append(sch)

            stats["active_schedules"] = len(active_schedules)

            # 6. 以旧轨 normalized_event_id 为分组键，直接聚合归一化展示节点
            #    物化层不再重复计算相似度，完全信任 Fusion Engine 已完成的融合判定结果。
            norm_groups = {}       # normalized_event_id (int) -> list[dict]
            ungrouped_schedules = []  # normalized_event_id 为 NULL 时的降级兜底（防御性，正常不触发）

            for sch in active_schedules:
                ne_id = sch["normalized_event_id"]
                if ne_id is not None:
                    norm_groups.setdefault(ne_id, []).append(sch)
                else:
                    ungrouped_schedules.append(sch)

            new_mappings_dict = {}
            new_normalized_nodes = []

            # 7. 逐组生成确定性超级展示节点
            for ne_id, group_schedules in norm_groups.items():
                # 旧轨权威名称与城市（同组内 canonical 字段相同，取第一条）
                canonical_name = group_schedules[0]["canonical_name"]
                canonical_city = group_schedules[0]["canonical_city"]
                canonical_event_type = group_schedules[0]["canonical_event_type"]
                name_slug = clean_event_name(canonical_name)

                # 计算最宽日期区间
                concrete_dates = []
                for s in group_schedules:
                    ed = s["event_date"]
                    if ed and ed != "未知":
                        try:
                            datetime.datetime.strptime(ed, "%Y-%m-%d")
                            concrete_dates.append(ed)
                        except ValueError:
                            pass

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

                # 计算确定性 MD5 主键 ID（重构为基于 normalized_event_id 的不可变散列，规避日期漂移导致的 ID 抖动）
                winner_id = hashlib.md5(f"norm_{ne_id}".encode("utf-8")).hexdigest()

                # 判定冷冻状态
                is_frozen = 0
                if concrete_dates:
                    if end_date < t_cold_str:
                        is_frozen = 1
                        stats["newly_frozen_nodes"] += 1
                else:
                    pub_dates = [s["published_at"] for s in group_schedules if s["published_at"]]
                    if pub_dates and max(pub_dates) < t_cold_str:
                        is_frozen = 1
                        stats["newly_frozen_nodes"] += 1

                new_normalized_nodes.append({
                    "id": winner_id,
                    "standard_name": canonical_name,
                    "city": canonical_city,
                    "start_date": start_date if start_date != "未知" else None,
                    "end_date": end_date if end_date != "未知" else None,
                    "event_type": canonical_event_type,
                    "is_frozen": is_frozen
                })

                for s in group_schedules:
                    new_mappings_dict[s["id"]] = winner_id

                stats["new_clusters"] += 1
                audit_log["new_clusters"].append({
                    "deterministic_id": winner_id,
                    "standard_name": canonical_name,
                    "city": canonical_city,
                    "event_type": canonical_event_type,
                    "start_date": start_date,
                    "end_date": end_date,
                    "is_frozen": is_frozen,
                    "schedules": [
                        {"id": s["id"], "coser_name": s["coser_name"], "event_name": s["event_name"], "event_date": s["event_date"]}
                        for s in group_schedules
                    ]
                })

            # 8. 对 normalized_event_id 为 NULL 的日程降级兜底处理（防御性，正常情况不触发）
            #    直接复用 canonical_* 属性，并缓存 strptime 的 dt 实例，降低解析开销
            for sch in ungrouped_schedules:
                canonical_city = sch["canonical_city"]
                canonical_name = sch["canonical_name"]
                canonical_event_type = sch["canonical_event_type"]
                name_slug = clean_event_name(canonical_name)

                ed = sch["event_date"]
                if ed and ed != "未知":
                    try:
                        dt = datetime.datetime.strptime(ed, "%Y-%m-%d")
                        start_date = end_date = ed
                        date_bucket = dt.strftime("%Y-W%W")
                    except ValueError:
                        start_date = end_date = "未知"
                        date_bucket = "未知"
                else:
                    start_date = end_date = "未知"
                    date_bucket = "未知"

                # 附加 ce.id 确保每条无归属日程都获得唯一 ID
                winner_id = MaterializeService.generate_deterministic_id(
                    canonical_city, f"{name_slug}_{sch['id']}", canonical_event_type, date_bucket
                )

                is_frozen = 0
                if start_date != "未知" and start_date < t_cold_str:
                    is_frozen = 1
                    stats["newly_frozen_nodes"] += 1
                elif start_date == "未知" and sch["published_at"] and sch["published_at"] < t_cold_str:
                    is_frozen = 1
                    stats["newly_frozen_nodes"] += 1

                new_normalized_nodes.append({
                    "id": winner_id,
                    "standard_name": canonical_name,
                    "city": canonical_city,
                    "start_date": start_date if start_date != "未知" else None,
                    "end_date": end_date if end_date != "未知" else None,
                    "event_type": canonical_event_type,
                    "is_frozen": is_frozen
                })
                new_mappings_dict[sch["id"]] = winner_id
                stats["new_clusters"] += 1

            stats["new_normalized_nodes"] = len(new_normalized_nodes)

            # 8.5 在内存中提前解决 event_fingerprint 的冲突与后缀计数器，完全消除写事务内循环 SELECT 查询
            frozen_id_to_fingerprint = {r[0]: r[1] for r in frozen_rows if r[1]}
            used_fingerprints = {r[1] for r in frozen_rows if r[1]}
            for node in new_normalized_nodes:
                if node["id"] in frozen_id_to_fingerprint:
                    node["fingerprint"] = frozen_id_to_fingerprint[node["id"]]
                else:
                    fingerprint = f"{node['city'].lower()}_{clean_event_name(node['standard_name'])}"
                    base_fp = fingerprint
                    counter = 1
                    while fingerprint in used_fingerprints:
                        fingerprint = f"{base_fp}_{counter}"
                        counter += 1
                    used_fingerprints.add(fingerprint)
                    node["fingerprint"] = fingerprint

            # 9. 原子 SQL 事务写入隔离
            with conn:
                cursor.execute("BEGIN IMMEDIATE;")

                # 9.1 清空物化表中的热活跃节点（只保留 is_frozen = 1 的节点）
                cursor.execute("DELETE FROM final_exhibition_view WHERE is_frozen = 0;")

                # 9.2 写入新生成的超级物化节点
                now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                for node in new_normalized_nodes:
                    cursor.execute(
                        """
                        INSERT INTO final_exhibition_view (id, event_fingerprint, standard_name, city, start_date, end_date, event_type, is_frozen, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            event_fingerprint = excluded.event_fingerprint,
                            standard_name = excluded.standard_name,
                            start_date = excluded.start_date,
                            end_date = excluded.end_date,
                            is_frozen = excluded.is_frozen;
                        """,
                        (node["id"], node["fingerprint"], node["standard_name"], node["city"], node["start_date"], node["end_date"], node["event_type"], node["is_frozen"], now_str)
                    )

                # 9.3 清理已重新映射日程在 event_mappings 中的老记录并批量写入新 mappings
                if new_mappings_dict:
                    raw_ids_placeholders = ",".join(["?"] * len(new_mappings_dict))
                    cursor.execute(
                        f"DELETE FROM event_mappings WHERE raw_event_id IN ({raw_ids_placeholders});",
                        tuple(new_mappings_dict.keys())
                    )

                    for raw_id, norm_id in new_mappings_dict.items():
                        cursor.execute(
                            """
                            INSERT INTO event_mappings (raw_event_id, normalized_event_id, created_at)
                            VALUES (?, ?, ?);
                            """,
                            (raw_id, norm_id, now_str)
                        )

                # 9.4 输出归并轨迹审计日志到文件（置于事务提交前，确保 I/O 失败时回滚事务，保障一致性）
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
