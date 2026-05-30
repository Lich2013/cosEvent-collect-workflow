## 1. 事务隔离区重构与强写锁闭环

- [x] 1.1 在 `src/services/db/event_repository.py` 的 `save_extracted_events_transactional` 方法中，将 `with conn:` 移至查询之前，实现全生命周期由连接上下文管理。
- [x] 1.2 在进入 `with conn:` 块的第一时间执行 `cursor.execute("BEGIN IMMEDIATE;")`，强行升级为独占排他写锁以杜绝脏读和并发锁冲突。
- [x] 1.3 将原先在事务外的查询 coser 昵称、查找历史行程等所有 `SELECT` 动作全部移动到 `BEGIN IMMEDIATE;` 锁的包裹内部。
- [x] 1.4 在 `save_extracted_events_transactional` 的异常捕获逻辑中，如果捕获到 `AssertionError`、`ValidationError`、`IntegrityError` 等永久性硬错误，显式执行 `ROLLBACK` 并重新 `raise` 抛出异常（或返回特定状态码），以允许外层进行分类熔断。

## 2. 三态状态机熔断器与编排器异常分流

- [x] 2.1 在 `src/services/db/event_repository.py` 中新增 `mark_post_analysis_failed` 静态方法，启用独立短事务强行将 `raw_posts.is_analyzed` 变更为 `2`（熔断状态）。
- [x] 2.2 在 `src/services/db_service.py` 桥接暴露 `mark_post_analysis_failed` 方法给应用服务层。
- [x] 2.3 在 `src/services/workflow_orchestrator.py` 的 `run_analyze` 逻辑中，对博文分析及事务写入进行多层精细化异常捕获分流：
  - 如果抛出 `AssertionError`、`ValidationError`、`IntegrityError`（或捕获到对应抛出的硬错误），则在主事务安全回滚后，独立调用 `DBService.mark_post_analysis_failed(raw_post_id)`，物理上隔离数据库连接上下文，将状态置为 `2` 熔断豁免并记录 ERROR 审计。
  - 如果抛出大模型 API 超时、网络抖动等普通 `Exception`，仅打 Warning 日志并优雅略过，状态保持为 `0` 以备下轮重试。
- [x] 2.4 在 `WorkflowOrchestrator.run_analyze` 返回的 Summary 中，增加对于被分析熔断（状态变为 2）博文的计数与汇总展示，更新终端美化渲染器的状态统计。

## 3. 爬虫数据更新状态联动重置

- [x] 3.1 修改 `src/services/db/coser_repository.py` 中的博文更新（Upsert）逻辑。
- [x] 3.2 确保在 `edit_count` 递增触发内容更新时，对应的 `is_analyzed` 不仅从 `1` 被重置为 `0`，原先状态为 `2`（熔断）的博文也必须被一并强制重置为 `0`，重新激活下游增量提炼分析。

## 4. 单元测试覆盖与整体验证

- [x] 4.1 在 `tests/test_cosevent.py` 中，编写/更新针对三态熔断器的测试用例。
- [x] 4.2 测试用例 1：模拟大模型提炼通过，但在入库约束（如 `validate_status`）中故意触发 `AssertionError`，验证主活动表未插入任何脏数据，而 `raw_posts.is_analyzed` 状态成功置为 `2` 且下一轮分析不再加载。
- [x] 4.3 测试用例 2：模拟网络超时类异常，验证状态依旧为 `0`，并且下一轮能够继续捞出重试。
- [x] 4.4 测试用例 3：模拟将已熔断（状态为 2）的博文进行爬虫更新，验证其 `is_analyzed` 状态被成功洗回 `0`。
- [x] 4.5 运行 `poetry run pytest` 确保全量测试绿灯。
