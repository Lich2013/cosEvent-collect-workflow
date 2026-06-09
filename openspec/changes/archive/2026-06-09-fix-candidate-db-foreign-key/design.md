## Context

当前系统在运行 `coser discover` 时，待验证候选人数量始终卡在 `103` 无法减少。分析发现，在先前的数据库迁移中重建了 `coser_candidates` 表，但在迁移中子表 `candidate_raw_posts` 的外键约束未同步更新，而是因为 `sqlite` 的重命名机制自动变更为引用 `coser_candidates_old` 表。在 `coser_candidates_old` 表被 `DROP` 后，`candidate_raw_posts` 指向了不存在的表。

由于每个数据库连接默认开启了 `PRAGMA foreign_keys = ON;`，当调用 `reject_candidate` 等流转状态的更新操作时，SQLite 触发外键校验，抛出 `no such table: main.coser_candidates_old` 异常。此异常被 `try-except` 捕获并回滚，导致更新未生效且待验证候选人数据状态未改变。

## Goals / Non-Goals

**Goals:**
- 在数据库初始化逻辑中自动识别并清除错误的 `coser_candidates_old` 外键引用。
- 重建 `candidate_raw_posts` 表，正确建立与 `coser_candidates(id)` 的级联删除（`ON DELETE CASCADE`）外键约束。
- 确保 `DBService.reject_candidate`、`DBService.approve_candidate` 等状态流转操作在有外键校验的情况下正常执行。

**Non-Goals:**
- 在不保留原有外键检查的情况下直接关闭 `foreign_keys` 选项。
- 试图进行复杂的数据表就地列重建（SQLite 对 `ALTER TABLE` 修改外键支持有限，直接 `DROP` 重建更安全，因为 `candidate_raw_posts` 仅作为隔离博文缓存，无持久化历史日程）。

## Decisions

### 1. 采用 DDL 影子检查与自动 `DROP` 自愈重建
由于 SQLite 对外键修改支持能力极弱（不支持 `ALTER TABLE DROP CONSTRAINT` 等），对错误约束最好的处理方式是重建该表。
`candidate_raw_posts` 保存的是未审核候选人的临时爬取博文。在候选人审核完成后，关联博文会被立刻物理删除。因此，在迁移过程中直接 `DROP` 并重建 `candidate_raw_posts` 不会对正式日程数据和追踪的 Coser 实体造成任何资产损失。

**具体逻辑**：
- 在 `init_db()` 中，检索 `sqlite_schema` 捞取 `candidate_raw_posts` 的 DDL 创建 SQL。
- 检测 DDL 创建 SQL 中是否包含 `"coser_candidates_old"`。
- 若包含，执行 `DROP TABLE candidate_raw_posts;`。
- 随后的 `CREATE TABLE IF NOT EXISTS candidate_raw_posts` 逻辑会自动将该表重新以最新的规范创建，其 `FOREIGN KEY` 将正确指向 `coser_candidates`。

## Risks / Trade-offs

- **[Risk]** 重建 `candidate_raw_posts` 表时，若当时有正在运行的验证爬虫，可能引发瞬间死锁。
  - **Mitigation**：此自愈逻辑在 CLI 初始化启动（即主线程的 `init_db()` 阶段）执行，此时没有任何异步爬虫进程启动，因此属于安全的单线程阻塞操作，能完全规避并发冲突。
