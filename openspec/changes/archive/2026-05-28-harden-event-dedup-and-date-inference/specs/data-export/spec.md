## MODIFIED Requirements

### Requirement: click 命令行支持一键多格式、多范围精细过滤导出

Click 命令行必须提供 `cosevent export` 子命令，允许用户将 `cosplay_events` 数据表中的活动列表进行灵活的筛选和导出。导出命令必须满足以下要求：

1. **时域区间筛选 (`--scope`)**：
   - 必须支持可选命令行参数 `--scope`（Choice: `["future", "all"]`，默认值为 `future`）。
   - 当 `scope` 为 `future` 时，系统**必须且 SHALL** 仅过滤日期大于或等于当前北京日期（格式 `YYYY-MM-DD`）以及日期标识为 `"未知"` 的日程，以保障未来规划不被漏掉。
   - 当 `scope` 为 `all` 时，系统**必须且 SHALL** 导出全量日程。
   - **软注销屏蔽**：系统在任何过滤模式下，**必须且 SHALL** 物理过滤掉 `status == '已取消'` 的脏日程。

2. **自适应格式智能推理与渲染 (`--format`)**：
   - 必须支持参数 `--format`（Choice: `["csv", "txt"]`，默认值为 `None`）。
   - **自适应推理**：若省略此参数，当指定 `--output` 时，系统**必须且 SHALL** 依据文件名后缀进行自适应识别（`.csv` 推理为 CSV 表格，`.txt` 推理为纯文本）；当未指定 `--output` 时，系统**必须且 SHALL** 自动以 `txt`（纯文本）格式在终端控制台进行打印。
   - **无乱码 CSV 文件**：导出为文件时，必须采用带 UTF-8 BOM 头前缀（`\xef\xbb\xbf`）的 `utf-8-sig` 编码写入。
   - **美观等宽纯文本**：文本格式下，系统**必须且 SHALL** 按照 Coser 昵称、活动名称、活动日期、活动地点、详情行程以空格等宽对齐并使用分隔符美化输出。
   - **推算日期动态继承**：在默认导出文本或 CSV 格式中，若 Coser 某一单体日程的 `event_date` 为 `'未知'`，但超级节点包络时间有效，导出时系统 SHALL 动态继承超级节点的 `start_date` 与 `end_date` 并附加 `(推算自超级节点)` 字样展现。

3. **标准输出与重定向管道友好 (`stdout` 与 `stderr` 分流)**：
   - 命令行参数 `--output` 必须为可选参数。若省略，系统**必须且 SHALL** 将渲染后的活动数据流直接向标准输出（`stdout`）打印。
   - **管道防污染**：向标准输出打印数据时，系统**必须且 SHALL** 将所有终端进度、成功及统计 secho 提示语通过标准错误流（`stderr`，即 `err=True`）打印。这保证了用户通过 Shell 重定向捕获的文本文件（如 `export > list.txt`）纯净无暇。
   - **管道 CSV BOM 注入**：当使用 `--format csv` 且重定向标准输出时，系统**必须且 SHALL** 主动在 stdout 最前方写入 `\ufeff` 字符，确保重定向生成的 CSV 文件在 Windows Excel 下双击打开无任何乱码。

4. **活动类型过滤 (`--type`)**：
   - 必须支持可选命令行参数 `--type`（Choice: `['漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售']`，默认值为 `None`）。
   - 当指定 `--type` 时，导出模块**必须且 SHALL** 仅过滤该指定分类下的日程。
   - 当省略 `--type` 时，默认导出全量类型的日程。

#### Scenario: 成功将未来漫展重定向至标准输出且提示信息分流至 stderr
- **WHEN** 数据库包含 2 个未来漫展，用户执行命令 `cosevent export --scope future > results.txt` 时
- **THEN** 本地 `results.txt` 成功生成，且内容仅包含这 2 个未来行程的工整文本；终端屏幕上显示高亮的成功提示语（不混入 `results.txt`），且退出状态码为 0

#### Scenario: 指定活动类型成功筛选导出
- **WHEN** 用户执行 `cosevent export --type 一日店长 --format txt --output ./niche.txt` 时
- **THEN** 本地生成 `niche.txt`，且文件内容仅包含属于 "一日店长" 的小众行程，退出状态码为 0

### Requirement: data-export 支持纯漫展 calendar 视图模式一键导出
系统在 `cosevent export` 子命令中，必须且 SHALL 扩展支持 `--view` 参数（Choice: `["default", "calendar"]`，默认值为 `default`）。
1. **Markdown 排期看板格式化**：
   - 当 `--view` 指定为 `calendar` 且输出目标为 `.md` 文件或控制台标准输出时，系统 SHALL 格式化输出为 Markdown 样式的表格。
   - 表格必须包含五列：`日期`、`城市`、`漫展名称`、`参展热度 (已登记Coser数)`、`核心展位信息`。
2. **纯文本或 CSV 降级渲染**：
   - 当 `--view calendar` 且输出目标为 `.csv` 时，系统 SHALL 导出包含上述五列属性 of 无乱码 Excel 兼容 CSV 文件（使用 `utf-8-sig` 编码与 UTF-8 BOM 头）。
   - 当输出目标未指定时，以纯文本 Markdown 表格渲染打印到标准输出（`stdout`），且将统计 secho 警告消息分流打印到 `stderr`。
3. **日历视图下的分类筛选支持**：
   - 当 `--view calendar` 时，若指定了 `--type` 参数，系统在生成超级节点时间轴排期日历表格时，必须且 SHALL 仅保留对应活动类型的超级节点与对应的登记 Coser 数量。
4. **日历视图下的时间包络渲染继承**：
   - 生成日历表格时，所有超级节点的日期均自动渲染为标准的 `start_date 至 end_date` 包络区间以保障日历完整度。

#### Scenario: 成功将未来漫展日历导出为 Markdown 表格文件
- **WHEN** 用户执行 `cosevent export --scope future --view calendar --output ./calendar.md` 时
- **THEN** 本地生成 `calendar.md` 文件，其内容为标准的 Markdown 等宽对齐表格，格式完整，且退出状态码为 0

#### Scenario: 成功将一日店长日历导出为 Markdown 表格文件
- **WHEN** 用户执行 `cosevent export --scope future --view calendar --type 一日店长 --output ./niche_calendar.md` 时
- **THEN** 本地生成 `niche_calendar.md` 文件，包含 "一日店长" 类型的日历 Markdown 表格，且退出状态码为 0
