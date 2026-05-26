## Why

当前系统的 Cosplay 活动导出命令 `cosevent export` 功能较为单一，存在两个核心局限：
1. **时间范围不够灵活**：目前仅支持单一种类的导出。用户在大部分情况下只需要查看**未来即将发生**（或日期未知，有可能在未来发生）的 Cosplay 日程，以便安排出行；但在某些审计、归档或统计场景中，用户也需要能够导出**全量历史日程**。
2. **导出格式不够丰富**：目前仅支持 CSV 这一种导出形式。但在终端交互、快捷查看或通过命令行脚本进行流式管道处理时，用户极度需要一个高可读性、排版整齐的**纯文本 (Plain Text)** 预览及导出格式，且能够在未指定文件路径时，**直接输出到标准输出 (stdout)**。

为了提升系统的企业级数据交互能力，本变更旨在对导出层进行全面扩展，完美支持“未来范围 (Future) vs 全量范围 (All)”的可选过滤，以及“无乱码 CSV vs 格式化文本 (txt/stdout)”的多格式自适应输出。

## What Changes

- **Click 命令行交互升级**：
  - 将 `--output` 参数由“必填”降级为“可选”。如果不提供 `--output` 参数（或传为 `"-"`），则系统自动将数据直接打印到**标准输出 (stdout)**。
  - 新增 `--scope [future|all]` 选项，默认值为 `future`（导出未来大于等于今天以及未知的有效日程），支持设为 `all`（导出全量历史及未来的所有日程）。
  - 新增 `--format [csv|txt]` 选项。如果不显式指定，系统会自动根据 `--output` 的后缀进行智能格式推理（`.txt` 推理为文本格式，`.csv` 推理为 CSV 格式，默认为 `csv`；若输出到 stdout，则默认采用 `txt` 文本高可读性格式进行优雅打印）。
- **数据服务层时域过滤过滤扩展**：
  - 升级 `DBService.get_all_events` 方法，使其接收 `scope` 参数。若 `scope == "future"`，在 SQL 查询层动态追加 `AND (event_date >= ? OR event_date = '未知')` 的时区对齐过滤。
- **导出模块大版本重构**：
  - 重构 `src/services/export_service.py` 中的逻辑，增加一个集中导出控制器 `export_events`。
  - 实现 `_export_to_csv`（生成带 BOM 头的 CSV 表格）与 `_export_to_txt`（输出排版工整、极具视觉美感的纯文本日程表）的分流渲染。
  - 完美保留向后兼容的别名函数 `export_events_to_csv`，确保已有测试套件 100% 正常运行。

## Capabilities

### New Capabilities

- `data-export-scope-filtering`: 导出功能必须支持时域范围筛选：当用户指定为 `future` 时，系统**必须且 SHALL** 仅过滤保留日期大于或等于当前北京日期（以及日期为 `"未知"`）的有效行程；当指定为 `all` 时，系统**必须且 SHALL** 导出全量日程。
- `data-export-stdout-support`: 导出功能必须支持直接输出到 stdout：如果不指定输出文件路径，系统**必须且 SHALL** 自动以高可读性的纯文本格式，将排版整齐的活动报表打印到控制台屏幕。

### Modified Capabilities

- `data-export`: 导出格式在原有 CSV 基础上**必须且 SHALL** 新增对纯文本 (txt) 的渲染支持，且必须支持基于文件后缀进行自适应智能格式推理。

## Impact

- **物理变更文件**：
  - `src/services/db_service.py`：升级 `get_all_events` 实现 SQL 层 scope 动态参数与北京时间时区对齐过滤。
  - `src/services/export_service.py`：重构导出入口，加入多范围（scope）和多格式（format）处理，增加 `_export_to_txt` 渲染方法。
  - `src/main.py`：升级 `cosevent export` 子命令，补充 Click options 并支持 stdout 直接输出。
  - `tests/test_cosevent.py`：新增全面覆盖 scope 范围和 txt/stdout 格式的 Mock 自动化单元测试。
