## ADDED Requirements

### Requirement: data-export 支持纯漫展 calendar 视图模式一键导出
系统在 `cosevent export` 子命令中，必须且 SHALL 扩展支持 `--view` 参数（Choice: `["default", "calendar"]`，默认值为 `default`）。
1. **Markdown 排期看板格式化**：
   - 当 `--view` 指定为 `calendar` 且输出目标为 `.md` 文件或控制台标准输出时，系统 SHALL 格式化输出为 Markdown 样式的表格。
   - 表格必须包含五列：`日期`、`城市`、`漫展名称`、`参展热度 (已登记Coser数)`、`核心展位信息`。
2. **纯文本或 CSV 降级渲染**：
   - 当 `--view calendar` 且输出目标为 `.csv` 时，系统 SHALL 导出包含上述五列属性的无乱码 Excel 兼容 CSV 文件（使用 `utf-8-sig` 编码与 UTF-8 BOM 头）。
   - 当输出目标未指定时，以纯文本 Markdown 表格渲染打印到标准输出（`stdout`），且将统计 secho 警告消息分流打印到 `stderr`。

#### Scenario: 成功将未来漫展日历导出为 Markdown 表格文件
- **WHEN** 用户执行 `cosevent export --scope future --view calendar --output ./calendar.md` 时
- **THEN** 本地生成 `calendar.md` 文件，其内容为标准的 Markdown 等宽对齐表格，格式完整，且退出状态码为 0
