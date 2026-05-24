## MODIFIED Requirements

### Requirement: 分析与状态更新的数据库事务原子性约束
系统必须确保增量分析的数据库完整性。每次执行单条博文的活动数据入库时，将解析出的多条 `cosplay_events` 活动记录插入数据库的操作，以及将对应 `raw_posts.id` 的 `is_analyzed` 更新为 `1` 的操作，**必须且 SHALL 统一在同一个数据库 SQL 事务中执行**。任何一步执行抛出异常，整个事务必须执行 ROLLBACK，以彻底避免局部写入失败引发的活动丢失或重复分析的灾难。为了避免与 Python 内置 `sqlite3` 的隐式自动事务管理冲突导致死锁或异常，系统**必须且 SHALL** 采用标准 Python 数据库连接上下文管理器 `with conn:` 自动且优雅地进行事务隔离、自动 Commit 与 Rollback 控制。

#### Scenario: 多活动插入中途失败触发完整事务回滚
- **WHEN** 智能体对某条博文提炼出 3 个活动，前 2 个写入成功，第 3 个由于数据库死锁或长度约束插入失败，导致抛出异常时
- **THEN** 数据库事务执行回滚，`cosplay_events` 中未写入关于该博文的任何活动记录，且对应的 `raw_posts` 中 `is_analyzed` 状态值依旧为 0
