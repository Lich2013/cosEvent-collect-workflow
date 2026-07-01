## MODIFIED Requirements

### Requirement: 抓取调度层条件筛选与免冷启动熔断
工作流编排调度层 `WorkflowOrchestrator.run_scrape` 必须且 SHALL 接收 `coser_name` 与 `platform` 作为可选筛选参数，并结合全局滑动窗口调度获取待抓取的活跃 Coser。
- 全局滑动窗口调度：若未指定 `coser_name`，系统必须且 SHALL 统一按 Coser 维度获取全局最久未被爬取的活跃 Coser 队列进行处理（基于 `cosers.last_scraped_at` 字段进行升序排序，其中 `NULL` 值优先），单次调度上限由 `batch_size` 限制。
- 平台按需分发：针对被选出的 Top 队列中的每一位 Coser，系统必须且 SHALL 仅当该 Coser 绑定了对应平台 UID 且 `platform` 参数包含该平台（或为 `all`）时，才将其推入该平台的待抓取队列。
- 姓名过滤：在捞取活跃名单后，若指定了姓名过滤，系统必须且 SHALL 在内存中进行精准裁剪。若名单匹配后为空，系统必须且 SHALL 打印黄色 `WARNING` 并优雅返回 `(0, {}, 0)`，绝不允许抛出任何异常。
- 平台过滤：在大循环派发任务前，系统必须且 SHALL 进行平台校验。对于未被指定的平台，系统必须且 SHALL 提前执行 `continue` 跳过，杜绝其 Scraper 实例的构建、Playwright 无头浏览器冷启动与超时等待。
- 数据兼容：即使仅抓取单人或单平台，调度层返回的返回值必须且 SHALL 严格对齐已存的三元组契约 `(total_cosers, success_platforms, total_inserted)` 以保证终端渲染及统计层在零修改的前提下完全适配。

#### Scenario: 匹配特定 Coser 平台成功执行抓取并返回三元组契约
- **WHEN** 调度器传入有效的 Coser 姓名及指定平台进行同步抓取且有数据入库
- **THEN** 系统顺利仅对该 Coser 对应平台执行同步、物理去重及事务入库，并成功返回三元组契约以渲染精美的总结报告

#### Scenario: 统一的全局滑动窗口调度
- **WHEN** 调度器不指定姓名过滤且 platform="all"，且存在已配置 UID 的活跃 Coser 时
- **THEN** 系统 SHALL 统一取全局最久未爬取的 30 位 Coser，并在本批次中抓取这 30 位 Coser 所配置的所有社交平台，并在抓取后更新其在 `cosers` 表中的 `last_scraped_at` 字段
