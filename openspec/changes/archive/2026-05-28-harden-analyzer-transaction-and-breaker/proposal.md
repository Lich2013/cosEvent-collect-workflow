## Why

在当前系统中，博文分析提炼模块的设计不够健壮，面临严重的 LLM API 重试死循环与 Token 浪费问题。
主要原因为：
1. **分析状态未有效豁免**：在 [event_repository.py](file:///Users/lich/work/cosEvent-workflow/src/services/db/event_repository.py) 中，活动入库的原子事务将“业务活动插入”与“更新博文状态为已分析 (is_analyzed = 1)”强行捆绑在同一个 SQL 事务中。当大模型返回的活动数据违反某些业务约束（例如 `validate_status` 或 `validate_type` 抛出 `AssertionError`，或数据库主键/唯一约束 `IntegrityError`）时，整个事务回滚，导致该博文的 `is_analyzed` 状态维持在 `0`。在下一轮分析中，该错误博文会被重新拉起并再次调用大模型，造成极其严重的 LLM Token 资金浪费。
2. **并发时空真空**：在事务进入 `with conn` 上下文锁表之前，已经在无锁状态下执行了 `SELECT` 查询旧行程。在高并发环境下这容易引发脏读和状态判断偏离，从而导致约束冲突被回滚，进一步加剧重试黑洞。

因此，现在必须对分析流程的事务包络与状态机进行硬化改造，建立“双轨熔断机制”并收紧并发临界区，以实现非阻塞、零 API 浪费的健壮系统。

## What Changes

- **双轨熔断机制 (Breaker Mechanism)**：引入 `is_analyzed` 三态状态机。
  - `0` (DEFAULT): 未分析。增量分析命令只提取 `is_analyzed = 0` 的记录。
  - `1`: 分析并成功入库。
  - `2`: 分析熔断挂起（分析报错已记录豁免）。
- **校验与永久性异常熔断升级**：
  - 如果大模型提炼活动成功，但在入库时由于格式/约束校验（如 `AssertionError`, `ValidationError` 或 `IntegrityError` 等永久性且不可通过简单重试恢复的硬异常）失败，主事务执行 `ROLLBACK` 确保主数据干净，同时触发外部熔断分支，通过独立写事务将 `raw_posts.is_analyzed` 变更为 `2`。
- **并发锁区重构 (Read-Write Transaction Encapsulation)**：
  - 重构 `EventRepository.save_extracted_events_transactional` 里的游标操作，确保进入 `with conn` 之后立即执行 `BEGIN IMMEDIATE;` 强锁表，随后所有的 `SELECT` 查询与 `INSERT/UPDATE` 均在此原子锁内执行，闭环防脏读和并发锁超时。

## Capabilities

### New Capabilities
<!-- 无新增能力，主要针对提取流程的架构和容错机制硬化 -->

### Modified Capabilities
- `event-extraction`: 细化博文增量提取时的状态转移规则，定义网络暂时性失败与永久性结构异常的数据分流路径，硬化事务原子闭环和三态状态机转移要求，彻底规避 API token 浪费。

## Impact

- 数据库模型：`raw_posts.is_analyzed` 状态定义变更为三态（0:未分析, 1:分析成功, 2:分析失败挂起）。
- 数据库访问层：`src/services/db/event_repository.py` 中的 `save_extracted_events_transactional` 方法。
- 工作流编排器：`src/services/workflow_orchestrator.py` 中的 `run_analyze` 逻辑。
- 单元测试：`tests/test_cosevent.py` 中关于事务回滚与 `is_analyzed` 状态的用例需要进行兼容性与硬化覆盖更新。
