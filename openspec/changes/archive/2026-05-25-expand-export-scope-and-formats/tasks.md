# Task List - expand-export-scope-and-formats

## 1. 数据库服务层 get_all_events 方法扩展

- [x] 1.1 修改 `src/services/db_service.py`，升级 `get_all_events` 方法支持接收 `scope` 参数。若 `scope == 'future'`，采用东八区北京时间作为参考原点，动态在 SQL 中拼接 `AND (event_date >= ? OR event_date = '未知')` 进行精准过滤。

## 2. 导出服务层多格式多范围渲染与向后兼容实现

- [x] 2.1 修改 `src/services/export_service.py`，实现 `export_events` 控制流，加入对格式推理（`.csv`/`.txt` 后缀推理）、`scope` 时域参数传递、以及 stdout 标准输出的自适应检测。
- [x] 2.2 在 `src/services/export_service.py` 中编写 `_write_to_csv` 私有方法，保留原有 BOM 头写 CSV 文件的业务逻辑。
- [x] 2.3 在 `src/services/export_service.py` 中编写 `_write_to_txt` 私有方法，对提取到的活动记录列表进行等宽对齐美化排版。如果 `output_path` 为空，则直接打印输出到控制台标准输出。
- [x] 2.4 保留 `export_events_to_csv` 别名方法，直接返回 `export_events(output_path, confidence_threshold, scope="all", fmt="csv")` 以实现 100% 的向后兼容。
- [x] 2.5 修复 CSV Stdout 重定向 BOM 缺失问题：在 `sys.stdout` 构造 `csv.writer` 之前主动注入 `\ufeff` (BOM)，防止标准输出重定向生成的 CSV 乱码。

## 3. CLI 命令扩展与参数补充

- [x] 3.1 修改 `src/main.py` 的 `@cli.command("export")`，将 `--output` 参数由 `required=True` 变为可选。
- [x] 3.2 增加 `--scope` 和 `--format` 命令行选项（options），分别绑定默认参数 and Choice值域校验，并支持在输出为空时智能路由至标准输出以 plain text 格式打印。

## 4. 全量自动化单元测试与验证

- [x] 4.1 在 `tests/test_cosevent.py` 中新增 `test_export_scope_and_format_variants` 测试用例，全面验证：
  - `scope="future"` 状态下，仅输出大于今天的活动与“未知”活动。
  - `scope="all"` 状态下，完整输出过去及未来的所有活动。
  - `fmt="txt"` 且指定路径时，成功写入美化的 text 文件。
  - 未指定输出路径时，标准输出拦截测试正常。
- [x] 4.2 本地执行 `uv run pytest`，确保全套 25 个测试用例 100% 绿屏成功运行。
- [x] 4.3 补充单元测试验证，在 `--format csv` 且 `output_path=None` 时，stdout 流的头部包含 `\ufeff` 字符。
