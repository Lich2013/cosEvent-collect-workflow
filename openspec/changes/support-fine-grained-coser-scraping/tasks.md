## 1. CLI 命令行参数扩展

- [x] 1.1 修改 `src/main.py` 的 `scrape_command` CLI 定义，新增可选命令行参数 `--name`（姓名昵称）与枚举参数 `--platform`（`weibo`、`bilibili`、`xhs`、`all`，默认 `all`）。
- [x] 1.2 升级 Click 解析逻辑，将接收到的参数安全转换为 `coser_name` 与 `platform`，并无损透传给调度层 `WorkflowOrchestrator.run_scrape`。

## 2. 调度内核条件过滤与冷启动裁剪

- [x] 2.1 重构 `src/services/workflow_orchestrator.py` 的 `WorkflowOrchestrator.run_scrape` 方法，使其接收可选的 `coser_name: str = None` 与 `platform: str = "all"` 参数。
- [x] 2.2 在 `run_scrape` 名单捞取层，若传入 `coser_name`，在内存中进行推导匹配；若裁剪后的活跃 Coser 名单为空，打印黄色 `WARNING` 警告并优雅熔断返回 `(0, {}, 0)`。
- [x] 2.3 在 `run_scrape` 循环体任务派发层，增加针对平台的匹配检查（如 `platform in ("weibo", "all")`）；若不符合平台过滤，必须且 SHALL 执行 `continue` 提前旁路跳过，杜绝无用 Scraper 的实例化与 Playwright 浏览器冷启动。
- [x] 2.4 保持返回值 `(total_cosers, success_platforms, total_inserted)` 的三元组契约一致，保证终端看板统计层零改动兼容。

## 3. 测试与验证

- [x] 3.1 编写单元测试或集成测试，覆盖单点姓名与平台过滤抓取场景，验证在空匹配、单点匹配时的拦截过滤行为，以及不带参数时的全量兼容性行为。
- [x] 3.2 运行测试并执行真实命令，验证终端统计报告完美输出。
