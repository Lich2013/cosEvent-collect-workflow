## MODIFIED Requirements

### Requirement: 分析与状态更新的数据库事务原子性约束
系统必须确保增量分析的数据库完整性。每次执行单条博文的活动数据入库时，将解析出的多条 `cosplay_events` 活动记录插入数据库的操作，以及将对应 `raw_posts.id` 的 `is_analyzed` 更新为 `1` 的操作，**必须且 SHALL 统一在同一个数据库 SQL 事务中执行**。任何一步执行抛出异常，整个事务必须执行 ROLLBACK，以彻底避免局部写入失败引发的活动丢失或重复分析的灾难。为了避免与 Python 内置 `sqlite3` 的隐式自动事务管理冲突导致死锁或异常，系统**必须且 SHALL** 采用标准 Python 数据库连接上下文管理器 `with conn:` 自动且优雅地进行事务隔离、自动 Commit 与 Rollback 控制。系统**必须且 SHALL** 保证所有的 SQLite 游标（Cursor）操作由 `try...finally cursor.close()` 或游标上下文管理器彻底物理关闭，以确保资源使用完毕后被百分之百彻底安全释放，杜绝游标泄漏及 SQLite `database is locked` 死锁隐患。系统**必须且 SHALL** 对数据库所有表的创建与审计时间列（包括 `cosers.created_at`, `raw_posts.scraped_at`, `cosplay_events.created_at` 等所有时间段）进行应用层锁死，统一强行以东八区北京时区当前时间且格式为 `"YYYY-MM-DD HH:MM:SS"` 的字符串由 Python 写入，废弃 SQLite 原生 UTC 时间 `DEFAULT CURRENT_TIMESTAMP` 差异，实现全库时间一致性。

#### Scenario: 数据库并发写游标安全闭合释放
- **WHEN** 增量保存活动执行完毕，游标上下文块退出时
- **THEN** 游标对象在数据库连接关闭前已被标准库自动执行 close() 释放，无连接残留

#### Scenario: 数据库新增实体与审计数据成功锁定写入北京时间
- **WHEN** 向 cosers, raw_posts, 或者是 cosplay_events 表写入或更新数据时
- **THEN** 其 created_at/scraped_at 等时间相关审计字段均被精确记录为北京时间 YYYY-MM-DD HH:MM:SS，而非 UTC 滞后时间
