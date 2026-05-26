## Context

当前系统的 `cosevent export` 功能在数据分析提炼完成后为用户提供了一键离线 CSV 归档的能力。然而，用户通常只关心未来即将开始（以及未知）的日程计划以进行行程编排。目前直接导出所有日程（包含了已逝去的陈年历史日程）极易对用户造成行程混乱。

此外，在纯命令行环境或服务器端流式调度中，用户需要不用打开任何 CSV 编辑软件，即可在控制台快速、优美地打印预览当前日程列表。现存的代码完全绑定了文件系统写入以及单类型的 CSV 文件，我们需要重构这部分设计以支持更高精度的时域区间过滤与纯文本（txt/stdout）支持。

## Goals / Non-Goals

**Goals:**
- **动态时域过滤 (Future Scope Check)**：当用户指定 `scope="future"` 时，能够精准截取 `event_date >= today_str` 以及 `event_date = '未知'` 的行。
- **多格式渲染与自适应推理 (Smart Routing)**：系统根据 `--format` 或文件名后缀自动分流：文件为 `.csv` 输出 Excel CSV，`.txt` 输出排版精美的纯文本报表。
- **标准输出无缝支持 (Stdout Mode)**：当用户省略 `--output` 时，静默路由到纯文本 stdout 输出，让用户能在命令行终端一览所有日程，提升极客体验。
- **100% 向后兼容性**：保留原有 `ExportService.export_events_to_csv` 函数作为向后兼容包装器，防止破坏既有测试代码。

**Non-Goals:**
- **不对 cosplay_events 的物理表结构进行任何字段变更或增加**（严守 `AGENTS.md` 的零字段污染原则）。
- **不对 LLM 智能提取阶段做任何改动**（提取仍保持高精度过滤与软状态机状态对齐）。

## Decisions

### 决策 1：在 `db_service.py` 的 `get_all_events` 注入动态时域分流

为了实现 SQL 级的高性能筛选，我们在获取所有行程的 SQL 中动态拼接过滤语句：
```python
    @staticmethod
    def get_all_events(confidence_threshold: float = 0.0, scope: str = "all") -> list[dict]:
        """获取所有置信度高于阈值的有效活动，支持按范围分流"""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            sql = """
            SELECT id, raw_post_id, coser_name, event_name, event_date, event_place, event_description, confidence, source_url, created_at
            FROM cosplay_events
            WHERE confidence >= ? AND status != '已取消'
            """
            params = [confidence_threshold]
            
            if scope == "future":
                import datetime
                beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
                current_date = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d")
                sql += " AND (event_date >= ? OR event_date = '未知')"
                params.append(current_date)
                
            sql += " ORDER BY event_date ASC;"
            cursor.execute(sql, tuple(params))
            ...
```

### 决策 2：`ExportService` 的多渠道自适应分流

在 `export_service.py` 中重构导出机制，提供 `export_events` 控制核心：
```python
class ExportService:
    @staticmethod
    def export_events(
        output_path: str = None,
        confidence_threshold: float = 0.0,
        scope: str = "future",
        fmt: str = None
    ) -> int:
        """多范围、多格式的统一导出控制入口"""
        # 1. 自动格式推理
        if not fmt:
            if output_path:
                suffix = output_path.lower().split(".")[-1]
                fmt = suffix if suffix in ("csv", "txt") else "csv"
            else:
                fmt = "txt" # 默认 stdout 输出纯文本
                
        # 2. 从数据库获取 events
        events = DBService.get_all_events(confidence_threshold, scope)
        
        # 3. 渲染分流
        if fmt == "csv":
            return ExportService._write_to_csv(output_path, events)
        elif fmt == "txt":
            return ExportService._write_to_txt(output_path, events, scope)
        else:
            raise ValueError(f"Unsupported format: {fmt}")
```

- 当 `output_path` 为 `None` 且 `fmt == "txt"` 时，`_write_to_txt` 会直接将文本结果通过 `click.echo` 或标准输出流打印。
- 文本格式中，各属性字段严格使用空格对齐以保证极致的美学排版效果。

## Risks / Trade-offs

- **[Risk] `event_date = '未知'` 怎么排序？**
  - **[Mitigation]**：SQLite 在 `ORDER BY event_date ASC` 时，由于非标时间字符串 `'未知'` 的 ASCII 字符在数值（如 2026）之后，会自然地把 `未知` 放到列表的尾部。这完全符合人类“先看明确排班，最后预览待定日程”的正常阅读心理，不需要额外进行复杂的应用层多维排序重组。
- **[Risk] stdout 输出到控制台时如何保证中文字符的对齐美观度？**
  - **[Mitigation]**：因为中文在绝大多数等宽字体终端中占双字节宽度，采用中文全角分隔符或限制每项属性标题长度能规避对齐错落。在纯文本模板中，采用排版精美的多行文本渲染，并附带明确的分隔边界。
