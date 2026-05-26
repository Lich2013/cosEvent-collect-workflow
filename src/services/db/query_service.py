import sqlite3
import datetime
from src.models.db_models import get_db_connection

class QueryService:
    @staticmethod
    def get_all_events(confidence_threshold: float = 0.0, scope: str = "all", event_type: str = None) -> list[dict]:
        """获取所有置信度高于阈值的有效活动，支持按范围与活动类型分流"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            sql = """
            SELECT id, raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, created_at
            FROM cosplay_events
            WHERE confidence >= ? AND status != '已取消'
            """
            params = [confidence_threshold]
            
            if event_type:
                sql += " AND event_type = ?"
                params.append(event_type)
            
            if scope == "future":
                beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
                current_date = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d")
                sql += " AND (event_date >= ? OR event_date = '未知')"
                params.append(current_date)
                
            sql += " ORDER BY event_date ASC;"
            cursor.execute(sql, tuple(params))
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

    @staticmethod
    def get_event_centric_summary(confidence_threshold: float = 0.0, event_type: str = None) -> list[dict]:
        """
        获取以漫展为维度的集结大看板数据，支持按活动类型筛选
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            sql = """
            SELECT 
                ne.id AS event_id,
                ne.standard_name,
                ne.city,
                ne.start_date,
                ne.end_date,
                ce.coser_name,
                ce.event_date,
                ce.event_place,
                ce.event_description,
                ce.confidence
            FROM normalized_events ne
            JOIN cosplay_events ce ON ne.id = ce.normalized_event_id
            WHERE ce.status != '已取消' AND ce.confidence >= ?
            """
            params = [confidence_threshold]
            if event_type:
                sql += " AND ce.event_type = ?"
                params.append(event_type)
            sql += " ORDER BY ne.start_date IS NULL, ne.start_date ASC, ce.event_date IS NULL, ce.event_date ASC;"
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            
            events_map = {}
            for r in rows:
                ev_id = r[0]
                if ev_id not in events_map:
                    events_map[ev_id] = {
                        "id": ev_id,
                        "standard_name": r[1],
                        "city": r[2],
                        "start_date": r[3] or "未知",
                        "end_date": r[4] or "未知",
                        "cosers": []
                    }
                events_map[ev_id]["cosers"].append({
                    "coser_name": r[5],
                    "event_date": r[6],
                    "event_place": r[7],
                    "event_description": r[8],
                    "confidence": r[9]
                })
            return list(events_map.values())
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_normalized_events(city: str = None, scope: str = "future", event_type: str = "漫展") -> list[dict]:
        """
        获取纯超级漫展节点列表（不带 Coser 详情），支持按城市、未来时域与活动类型过滤，并包含聚合的核心展位信息
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            sql = """
            SELECT DISTINCT ne.id, ne.standard_name, ne.city, ne.start_date, ne.end_date 
            FROM normalized_events ne
            JOIN cosplay_events ce ON ne.id = ce.normalized_event_id
            WHERE ce.status != '已取消'
            """
            params = []
            
            if event_type:
                sql += " AND ne.event_type = ?"
                params.append(event_type)
                
            if city:
                sql += " AND ne.city = ?"
                params.append(city)
                
            if scope == "future":
                beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
                current_date = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d")
                sql += " AND (ne.end_date >= ? OR ne.end_date IS NULL)"
                params.append(current_date)
                
            sql += " ORDER BY ne.start_date IS NULL, ne.start_date ASC;"
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            
            result = []
            for r in rows:
                ev_id = r[0]
                cursor.execute(
                    """
                    SELECT COUNT(DISTINCT coser_name) FROM cosplay_events
                    WHERE normalized_event_id = ? AND status != '已取消';
                    """,
                    (ev_id,)
                )
                coser_count = cursor.fetchone()[0]
                
                # 智能提取该漫展下关联的所有 Coser 参展摊位/角色以汇总为“核心展位信息”
                cursor.execute(
                    """
                    SELECT coser_name, event_description FROM cosplay_events
                    WHERE normalized_event_id = ? AND status != '已取消';
                    """,
                    (ev_id,)
                )
                details = []
                for cos_name, desc in cursor.fetchall():
                    if desc:
                        cleaned_desc = desc.strip().replace("\n", " ")
                        if len(cleaned_desc) > 15:
                            cleaned_desc = cleaned_desc[:15] + "..."
                        details.append(f"{cos_name} ({cleaned_desc})")
                    else:
                        details.append(cos_name)
                core_info = " | ".join(details) if details else "无固定展位"
                
                result.append({
                    "id": ev_id,
                    "standard_name": r[1],
                    "city": r[2],
                    "start_date": r[3] or "未知",
                    "end_date": r[4] or "未知",
                    "coser_count": coser_count,
                    "core_info": core_info
                })
            return result
        finally:
            cursor.close()
            conn.close()
