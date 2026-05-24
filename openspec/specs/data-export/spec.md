# data-export Specification

## Purpose
TBD - created by archiving change cosplay-event-workflow. Update Purpose after archive.
## Requirements
### Requirement: click 命令行支持一键无乱码 CSV 导出与二次置信度精筛
Click 命令行必须提供 `cosevent export` 子命令，允许用户将 `cosplay_events` 数据表中的活动列表导出至本地文件。导出的 CSV 文件必须：
- 采用 `utf-8-sig` (UTF-8 with BOM) 编码，以保证 Windows 平台下的 Microsoft Excel 双击打开直接浏览时不发生中文字符乱码；
- 包含标准表头：`Coser昵称`, `活动名称`, `活动日期`, `活动地点`, `详情/Coser行程`, `原帖链接`, `入库时间`；
- 支持可选命令行参数 `--confidence-threshold` (FLOAT)。若提供，导出逻辑必须对 `cosplay_events` 表中的数据进行过滤，仅导出 `confidence` 大于或等于该筛选阈值的记录。这使用户能够在 analyze 阶段使用较低阈值进行宽泛收集（例如 0.3）的前提下，在 export 阶段使用更高阈值（例如 0.8）对导出报表进行精细化精筛。

#### Scenario: 成功导出非乱码且满足高置信度精筛的 CSV 活动数据报表
- **WHEN** 数据库中包含置信度为 0.5 和 0.9 的活动，用户执行命令 `cosevent export --output ./results.csv --confidence-threshold 0.8` 时
- **THEN** 本地指定路径成功生成 CSV 文件，其中仅包含置信度为 0.9 的活动数据，且使用 Excel 打开时所有中文字符均能正常、不乱码地清晰展示

