import sqlite3
import datetime
from src.models.db_models import get_db_connection
from src.utils.time import beijing_today_str

class QueryService:
    @staticmethod
    def get_all_events(confidence_threshold: float = 0.0, scope: str = "all", event_type: str = None, city: str = None) -> list[dict]:
        """获取所有置信度高于阈值的有效活动，支持按范围与活动类型及地级市分流"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            sql = """
            SELECT 
                ce.id, ce.raw_post_id, ce.coser_name, ce.event_name, ce.event_date, ce.event_place, ce.event_description, ce.confidence, ce.source_url, ce.created_at,
                COALESCE(ne.start_date, old_ne.start_date) AS start_date,
                COALESCE(ne.end_date, old_ne.end_date) AS end_date,
                COALESCE(ne.city, old_ne.city) AS city
            FROM cosplay_events ce
            LEFT JOIN event_mappings em ON ce.id = em.raw_event_id
            LEFT JOIN final_exhibition_view ne ON em.normalized_event_id = ne.id
            LEFT JOIN normalized_events old_ne ON ce.normalized_event_id = old_ne.id
            WHERE ce.confidence >= ? AND ce.status != '已取消'
            """
            params = [confidence_threshold]
            
            if event_type:
                sql += " AND ce.event_type = ?"
                params.append(event_type)
                
            if city:
                sql += " AND COALESCE(ne.city, old_ne.city) = ?"
                params.append(city)
            
            if scope == "future":
                current_date = beijing_today_str()
                sql += " AND (ce.event_date >= ? OR ce.event_date = '未知')"
                params.append(current_date)
                
            sql += " ORDER BY ce.event_date ASC;"
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            
            result = []
            for r in rows:
                event_date = r[4]
                ne_start = r[10]
                ne_end = r[11]
                
                # 如果单体日程日期为 '未知'，但关联的超级节点日期有效，则进行继承推算
                if event_date == '未知' and ne_start and ne_end:
                    event_date = f"{ne_start} 至 {ne_end} (推算自超级节点)"
                    
                result.append({
                    "id": r[0],
                    "raw_post_id": r[1],
                    "coser_name": r[2],
                    "event_name": r[3],
                    "event_date": event_date,
                    "event_place": r[5],
                    "event_description": r[6],
                    "confidence": r[7],
                    "source_url": r[8],
                    "created_at": r[9],
                    "city": r[12] or "未知"
                })
            return result
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_event_centric_summary(confidence_threshold: float = 0.0, event_type: str = None, city: str = None) -> list[dict]:
        """
        获取以漫展为维度的集结大看板数据，支持按活动类型与地级市精细筛选
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            sql = """
            WITH united_events AS (
                SELECT 
                    ne.id AS event_id,
                    ne.standard_name,
                    ne.city,
                    ne.start_date,
                    ne.end_date,
                    ne.event_type,
                    ce.coser_name,
                    ce.event_date,
                    ce.event_place,
                    ce.event_description,
                    ce.confidence,
                    ce.status,
                    ce.event_type AS ce_event_type
                FROM final_exhibition_view ne
                JOIN event_mappings em ON ne.id = em.normalized_event_id
                JOIN cosplay_events ce ON em.raw_event_id = ce.id
                
                UNION ALL
                
                SELECT 
                    CAST(old_ne.id AS TEXT) AS event_id,
                    old_ne.standard_name,
                    old_ne.city,
                    old_ne.start_date,
                    old_ne.end_date,
                    old_ne.event_type,
                    ce.coser_name,
                    ce.event_date,
                    ce.event_place,
                    ce.event_description,
                    ce.confidence,
                    ce.status,
                    ce.event_type AS ce_event_type
                FROM normalized_events old_ne
                JOIN cosplay_events ce ON old_ne.id = ce.normalized_event_id
                WHERE ce.id NOT IN (SELECT raw_event_id FROM event_mappings)
            )
            SELECT 
                event_id,
                standard_name,
                city,
                start_date,
                end_date,
                coser_name,
                event_date,
                event_place,
                event_description,
                confidence
            FROM united_events
            WHERE status != '已取消' AND confidence >= ?
            """
            params = [confidence_threshold]
            if event_type:
                sql += " AND ce_event_type = ?"
                params.append(event_type)
            if city:
                sql += " AND city = ?"
                params.append(city)
            sql += " ORDER BY start_date IS NULL, start_date ASC, event_date IS NULL, event_date ASC;"
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            
            events_map = {}
            for r in rows:
                ev_id = r[0]
                ne_start = r[3]
                ne_end = r[4]
                coser_date = r[6]
                
                # 如果单体日程日期为 '未知'，但关联的超级节点日期有效，则进行继承推算
                if coser_date == '未知' and ne_start and ne_end:
                    coser_date = f"{ne_start} 至 {ne_end} (推算自超级节点)"
                
                if ev_id not in events_map:
                    events_map[ev_id] = {
                        "id": ev_id,
                        "standard_name": r[1],
                        "city": r[2],
                        "start_date": ne_start or "未知",
                        "end_date": ne_end or "未知",
                        "cosers": []
                    }
                events_map[ev_id]["cosers"].append({
                    "coser_name": r[5],
                    "event_date": coser_date,
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
            WITH united_normalized AS (
                SELECT DISTINCT 
                    ne.id AS event_id, 
                    ne.standard_name, 
                    ne.city, 
                    ne.start_date, 
                    ne.end_date, 
                    ne.event_type,
                    ce.status AS ce_status
                FROM final_exhibition_view ne
                JOIN event_mappings em ON ne.id = em.normalized_event_id
                JOIN cosplay_events ce ON em.raw_event_id = ce.id
                
                UNION ALL
                
                SELECT DISTINCT 
                    CAST(old_ne.id AS TEXT) AS event_id, 
                    old_ne.standard_name, 
                    old_ne.city, 
                    old_ne.start_date, 
                    old_ne.end_date, 
                    old_ne.event_type,
                    ce.status AS ce_status
                FROM normalized_events old_ne
                JOIN cosplay_events ce ON old_ne.id = ce.normalized_event_id
                WHERE ce.id NOT IN (SELECT raw_event_id FROM event_mappings)
            )
            SELECT DISTINCT event_id, standard_name, city, start_date, end_date
            FROM united_normalized
            WHERE ce_status NOT IN ('已取消', '已结束')
            """
            params = []
            
            if event_type:
                sql += " AND event_type = ?"
                params.append(event_type)
                
            if city:
                sql += " AND city = ?"
                params.append(city)
                
            if scope == "future":
                current_date = beijing_today_str()
                sql += " AND (end_date >= ? OR end_date IS NULL)"
                params.append(current_date)
                
            sql += " ORDER BY start_date IS NULL, start_date ASC;"
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            
            result = []
            for r in rows:
                ev_id = r[0]
                cursor.execute(
                    """
                    SELECT COUNT(DISTINCT coser_name) FROM cosplay_events ce
                    LEFT JOIN event_mappings em ON ce.id = em.raw_event_id
                    WHERE (em.normalized_event_id = ? OR CAST(ce.normalized_event_id AS TEXT) = ?) AND ce.status != '已取消';
                    """,
                    (ev_id, ev_id)
                )
                coser_count = cursor.fetchone()[0]
                
                # 智能提取该漫展下关联的所有 Coser 参展摊位/角色以汇总为“核心展位信息”
                cursor.execute(
                    """
                    SELECT coser_name, event_description FROM cosplay_events ce
                    LEFT JOIN event_mappings em ON ce.id = em.raw_event_id
                    WHERE (em.normalized_event_id = ? OR CAST(ce.normalized_event_id AS TEXT) = ?) AND ce.status != '已取消';
                    """,
                    (ev_id, ev_id)
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
