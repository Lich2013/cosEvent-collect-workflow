import csv
import sys
from src.services.db_service import DBService

class ExportService:
    @staticmethod
    def export_events(
        output_path: str = None,
        confidence_threshold: float = 0.0,
        scope: str = "future",
        fmt: str = None,
        view: str = "default",
        event_type: str = None
    ) -> int:
        """
        多范围、多格式的统一导出控制入口：
        1. 自动根据文件名后缀推理格式 (fmt or suffix)
        2. 根据 view 类型分流获取数据 (Coser日程 或 超级漫展排期)
        3. 分流渲染至 CSV 或纯文本 (TXT/Markdown/Stdout)
        """
        # 1. 自动格式推理
        if not fmt:
            if output_path:
                suffix = output_path.lower().split(".")[-1]
                # md 等后缀自动以纯文本 markdown 处理
                fmt = suffix if suffix in ("csv", "txt", "md") else "csv"
            else:
                fmt = "txt"  # stdout 默认输出纯文本

        # 转换为内部通用格式
        fmt_type = "csv" if fmt == "csv" else "txt"

        if view == "calendar":
            # 2.A 漫展日历视图：从 DBService 中调取归一化漫展节点
            # 如果未显式指定 event_type，在 calendar 视图下默认展示 '漫展'
            effective_type = event_type if event_type is not None else "漫展"
            events = DBService.get_normalized_events(city=None, scope=scope, event_type=effective_type)
            
            # 3.A 渲染日历输出
            if fmt_type == "csv":
                return ExportService._write_calendar_to_csv(output_path, events)
            else:
                return ExportService._write_calendar_to_markdown(output_path, events, scope)
        else:
            # 2.B 默认排班视图：从 DBService 中调取符合 scope 与 confidence 要求的有效活动
            events = DBService.get_all_events(confidence_threshold, scope, event_type=event_type)

            # 3.B 渲染日程输出
            if fmt_type == "csv":
                return ExportService._write_to_csv(output_path, events)
            else:
                return ExportService._write_to_txt(output_path, events, scope)

    @staticmethod
    def _write_to_csv(output_path: str, events: list[dict]) -> int:
        """输出为 Excel 友好 CSV 文件 (携带 UTF-8 BOM 头)"""
        if not output_path:
            # 如果输出到 stdout 但指定了 csv 格式，利用 sys.stdout 输出
            # 主动在 stdout 头部注入 UTF-8 BOM 字符，以支撑 Excel 直接打开重定向文件无乱码
            try:
                sys.stdout.write('\ufeff')
            except Exception:
                pass
            writer = csv.writer(sys.stdout)
            headers = ["Coser昵称", "活动名称", "活动日期", "活动地点", "详情/Coser行程", "原帖链接", "入库时间"]
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
            print(f"\x1b[1;31m[Export ERROR] 写入 CSV 失败: {e}\x1b[0m")
            raise e

    @staticmethod
    def _write_to_txt(output_path: str, events: list[dict], scope: str) -> int:
        """输出为排版美观整齐的纯文本，支持文件系统与控制台标准输出"""
        title_scope = "未来及未知" if scope == "future" else "全量"
        lines = []
        lines.append("=" * 60)
        lines.append(f"            Cosplay 活动日程表 (范围: {title_scope})")
        lines.append("=" * 60)

        for e in events:
            lines.append(f"Coser 昵称 : {e['coser_name']}")
            lines.append(f"活动名称   : {e['event_name']}")
            lines.append(f"活动日期   : {e['event_date']}")
            lines.append(f"活动地点   : {e['event_place']}")
            lines.append(f"原帖链接   : {e.get('source_url') or ''}")
            desc = e.get('event_description') or ''
            lines.append(f"详情/行程  : {desc.strip() if desc else ''}")
            lines.append("-" * 60)

        lines.append(f"[共成功导出 {len(events)} 条活动记录]")
        text_content = "\n".join(lines) + "\n"

        if not output_path:
            import click
            # 直接打印输出到控制台标准输出
            click.echo(text_content)
            return len(events)

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(text_content)
            return len(events)
        except Exception as e:
            print(f"\x1b[1;31m[Export ERROR] 写入文本失败: {e}\x1b[0m")
            raise e

    @staticmethod
    def _write_calendar_to_csv(output_path: str, events: list[dict]) -> int:
        """输出日历看板为 Excel 友好 CSV 文件 (携带 UTF-8 BOM 头)"""
        if not output_path:
            try:
                sys.stdout.write('\ufeff')
            except Exception:
                pass
            writer = csv.writer(sys.stdout)
            headers = ["日期", "城市", "漫展名称", "参展热度 (已登记Coser数)", "核心展位信息"]
            writer.writerow(headers)
            for e in events:
                date_str = e['start_date']
                if e['start_date'] != '未知' and e['end_date'] != '未知':
                    date_str = f"{e['start_date']} 至 {e['end_date']}"
                writer.writerow([
                    date_str,
                    e["city"],
                    e["standard_name"],
                    f"{e['coser_count']}位",
                    e["core_info"]
                ])
            return len(events)

        headers = ["日期", "城市", "漫展名称", "参展热度 (已登记Coser数)", "核心展位信息"]
        try:
            with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for e in events:
                    date_str = e['start_date']
                    if e['start_date'] != '未知' and e['end_date'] != '未知':
                        date_str = f"{e['start_date']} 至 {e['end_date']}"
                    writer.writerow([
                        date_str,
                        e["city"],
                        e["standard_name"],
                        f"{e['coser_count']}位",
                        e["core_info"]
                    ])
            return len(events)
        except Exception as e:
            print(f"\x1b[1;31m[Export ERROR] 写入日历 CSV 失败: {e}\x1b[0m")
            raise e

    @staticmethod
    def _write_calendar_to_markdown(output_path: str, events: list[dict], scope: str) -> int:
        """输出排版美观的 Markdown 表格日历，支持文件系统与控制台标准输出"""
        title_scope = "未来及未知" if scope == "future" else "全量"
        lines = []
        lines.append("## 📅 二次元超级漫展排期日历看板")
        lines.append(f"> 提炼范围: {title_scope} | 数据自动融合自 Coser 实名日程\n")
        lines.append("| 日期 | 城市 | 漫展名称 | 参展热度 (已登记Coser数) | 核心展位信息 |")
        lines.append("| :--- | :--- | :--- | :---: | :--- |")
        
        for e in events:
            date_str = e['start_date']
            if e['start_date'] != '未知' and e['end_date'] != '未知':
                date_str = f"{e['start_date']} 至 {e['end_date']}"
            lines.append(f"| {date_str} | {e['city']} | **{e['standard_name']}** | {e['coser_count']}位 | {e['core_info']} |")
            
        text_content = "\n".join(lines) + "\n"
        
        if not output_path:
            import click
            click.echo(text_content)
            return len(events)
            
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(text_content)
            return len(events)
        except Exception as e:
            print(f"\x1b[1;31m[Export ERROR] 写入 Markdown 失败: {e}\x1b[0m")
            raise e

    @staticmethod
    def export_events_to_csv(output_path: str, confidence_threshold: float = 0.0) -> int:
        """向后兼容原有单元测试的别名方法，默认导出全量 CSV"""
        return ExportService.export_events(
            output_path=output_path,
            confidence_threshold=confidence_threshold,
            scope="all",
            fmt="csv"
        )
