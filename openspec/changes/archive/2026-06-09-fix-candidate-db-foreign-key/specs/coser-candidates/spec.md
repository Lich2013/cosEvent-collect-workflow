## MODIFIED Requirements

### Requirement: 候选人数据库 is_verified 验证状态与热迁移
系统必须且 SHALL 在候选人表 `coser_candidates` 中完整支持 `is_verified` 验证字段与 `'undetermined'` 软状态（通过 CHECK 约束硬锁死在 `('pending', 'approved', 'ignored', 'undetermined')` 范围内）。在 CLI 启动时，系统必须且 SHALL 能够安全自动地对已存在的老版数据库进行影子表重构（DDL）热迁移，无损还原历史数据及字段。
此外，为了防止历史迁移产生悬空外键或失效表名关联，系统在启动初始化数据库时，必须且 SHALL 自动检测隔离博文表 `candidate_raw_posts` 的外键约束是否指向已被删除的临时表 `coser_candidates_old`；一旦检测到，系统必须且 SHALL 安全地 `DROP` 并重建 `candidate_raw_posts` 表，以确保外键级联关系正确绑定在活动的 `coser_candidates` 上，避免引发外键冲突导致候选人流转事务被阻断。

#### Scenario: CLI 启动自动执行包含新状态约束的影子表热迁移升级
- **WHEN** 启动 CLI 命令行且检测到老数据库的 CHECK 约束不支持 `'undetermined'` 时
- **THEN** 系统通过自动执行影子表（Shadow Table）热重建事务，完成 `coser_candidates` 重建并迁移全量历史数据

#### Scenario: 隔离博文表包含失效外键约束时自动重建自愈
- **WHEN** 启动 CLI 命令行且检测到 `candidate_raw_posts` 表的外键引用指向 `'coser_candidates_old'` 时
- **THEN** 系统自动删除并物理重建 `candidate_raw_posts` 表，将外键重新绑定到正式的 `coser_candidates` 表，并在后续验证操作中使得状态更新事务顺利执行
