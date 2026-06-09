## Why

由于在先前的数据库迁移中重建了 `coser_candidates` 表（旧表被重命名为 `coser_candidates_old` 并随后被删除），但子表 `candidate_raw_posts` 的外键约束未被相应更新，仍然引用了已不存在的 `"coser_candidates_old"`。这导致在候选人流转为 `ignored`（忽略）或 `approved`（批准）状态时，触发外键约束检查失败并导致事务静默回滚，最终造成待验证候选人数量和状态停滞不变的死循环。

本项变更旨在修复该外键引用冲突，确保候选人发现与审核流程的状态机能够顺畅流转。

## What Changes

- **外键约束纠偏与自动重建**：在数据库初始化及热迁移逻辑中，自动检测 `candidate_raw_posts` 是否引用了已失效的旧表 `coser_candidates_old`，若存在则自动执行安全重建。
- **防止外键失效检测防御**：确保下次对候选人表进行迁移时，任何对其引用的子表也得到同步修正，或通过检测逻辑自动修复。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- `coser-candidates`: 在数据库初始化与状态流转层面，增强对候选人临时博文隔离表的外键自愈性，修复失效的 `coser_candidates_old` 外键约束。

## Impact

- 影响模块：数据库模型及迁移层 `src/models/db_models.py`，候选人仓储层 `src/services/db/candidate_repository.py`
- 影响行为：在 CLI 启动初始化数据库时会自动进行影子表结构检查与自愈；候选人状态在忽略/删除时，外键级联操作及删除动作能够顺畅执行，不再发生静默回滚。
