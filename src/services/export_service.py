import csv
from src.services.db_service import DBService

class ExportService:
    @staticmethod
    def export_events_to_csv(output_path: str, confidence_threshold: float = 0.0) -> int:
        """
        一键导出格式化活动数据为无乱码 CSV 文件：
        1. 过滤指定置信度阈值的活动记录实现二次精筛
        2. 基于 utf-8-sig (UTF-8 with BOM) 编码，防止 Excel 双击打开乱码
        """
        events = DBService.get_all_events(confidence_threshold)
        
        # 字段表头
        headers = ["Coser昵称", "活动名称", "活动日期", "活动地点", "详情/Coser行程", "原帖链接", "入库时间"]
        
        try:
            with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                
                for e in events:
                    writer.writerow([
                        e["coser_name"],
                        e["event_name"],
                        e["event_date"],
                        e["event_place"],
                        e.get("event_description") or "",
                        e.get("source_url") or "",
                        e["created_at"]
                    ])
            return len(events)
        except Exception as e:
            print(f"\x1b[1;31m[Export ERROR] 导出 CSV 失败: {e}\x1b[0m")
            raise e
