## ADDED Requirements

### Requirement: Click 命令行支持抓取细粒度参数过滤
系统终端入口的 `scrape` 命令行必须且 SHALL 支持接收可选的 `--name`（姓名昵称）参数，以及具有指定枚举的选择参数 `--platform`（包含 `weibo`、`bilibili`、`xhs`、`all` 选项，默认 `all`）。
系统必须对这些参数进行正确的类型解析，并安全透传给下游编排调度层。

#### Scenario: 无参数默认执行全量抓取
- **WHEN** 终端以默认形式 `uv run python src/main.py scrape` 启动，未指定任何过滤选项
- **THEN** 系统 SHALL 自动抓取数据库中所有已激活的 Coser 的所有平台（微博、B站、小红书）动态，保持原有全量批处理作业行

#### Scenario: 带过滤参数执行特定单点抓取
- **WHEN** 终端以包含参数的命令（例如 `uv run python src/main.py scrape --name "池咲misa" --platform bilibili`）启动
- **THEN** 系统 SHALL 仅对昵称为 "池咲misa" 且处于激活状态的 Coser 启动 B 站平台抓取任务，其他 Coser 和平台任务必须且 SHALL 优雅旁路跳过

### Requirement: 抓取调度层条件筛选与免冷启动熔断
工作流编排调度层 `WorkflowOrchestrator.run_scrape` 必须且 SHALL 接收 `coser_name` 与 `platform` 作为可选筛选参数。
- 姓名过滤：在捞取活跃名单后，若指定了姓名过滤，系统必须且 SHALL 在内存中进行精准裁剪。若名单匹配后为空，系统必须且 SHALL 打印黄色 `WARNING` 并优雅返回 `(0, {}, 0)`，绝不允许抛出任何异常。
- 平台过滤：在大循环派发任务前，系统必须且 SHALL 进行平台校验。对于未被指定的平台，系统必须且 SHALL 提前执行 `continue` 跳过，杜绝其 Scraper 实例的构建、Playwright 无头浏览器冷启动与超时等待。
- 数据兼容：即使仅抓取单人或单平台，调度层返回的返回值必须且 SHALL 严格对齐已存的三元组契约 `(total_cosers, success_platforms, total_inserted)` 以保证终端渲染及统计层在零修改的前提下完全适配。

#### Scenario: 匹配特定 Coser 平台成功执行抓取并返回三元组契约
- **WHEN** 调度器传入有效的 Coser 姓名及指定平台进行同步抓取且有数据入库
- **THEN** 系统顺利仅对该 Coser 对应平台执行同步、物理去重及事务入库，并成功返回三元组契约以渲染精美的总结报告
