## ADDED Requirements

### Requirement: 纯漫展视角时间轴日历看板 (Event Calendar)
Click 命令行工具必须提供 `cosevent calendar` 子命令，允许用户纯粹以“时间 + 空间”为维度查询高价值漫展列表。
1. **参数过滤契约**：
   - 必须支持可选参数 `--city`（例如 `--city 上海`），指定时系统 SHALL 仅输出该城市的漫展。
   - 必须支持可选参数 `--scope`（Choice: `["future", "all"]`，默认值为 `future`）。
     - 当 `scope` 为 `future` 时，系统 SHALL 仅保留 `end_date >= 当前日期` 或日期未知的超级漫展节点，自动过滤过期活动。
     - 当 `scope` 为 `all` 时，系统 SHALL 输出历史与未来全量漫展。
2. **多月聚合与嵌套时间轴格式**：
   - 终端打印时，系统 SHALL 按照“举办月份”（如 `2026年5月`）进行物理分组。
   - 在每个月份下，按照举办日期升序排列展示各城市及漫展的名称、举办时间、具体场馆，并显示已登记的参展 Coser 数量（例如：`👥 已集结 3 位 Coser`）。

#### Scenario: 成功按城市和未来时域过滤并打印展单
- **WHEN** 用户执行 `cosevent calendar --city 上海 --scope future`
- **THEN** 系统自动过滤掉发生在上海的历史过期漫展，并在终端打印出未来在上海举办的所有标准漫展排期，按日期升序输出，退出状态码为 0
