## Context

`MaterializeService.rebuild_view()` 是系统在 `process` 任务链末尾执行的批量物化重建服务，负责将分析阶段写入的原始日程事实记录（`cosplay_events`）聚合并写入最终展示层（`final_exhibition_view` + `event_mappings`）。

当前实现存在一个根本性的架构矛盾：**物化层在 Fusion Engine 已完成判定之后，又独立运行了一套聚类算法**，而两套算法的判定标准不同：

- **Fusion Engine（analyze 阶段）**：`SequenceMatcher ratio >= 0.75` 进相似区，`0.2 <= ratio < 0.75` 进 LLM 裁判灰区，裁判结果写入 `cosplay_events.normalized_event_id`（旧轨）
- **MaterializeService（materialize 阶段）**：仅凭 `ratio >= 0.75` 或 `name_slug` 完全一致做 Union-Find，**完全丢弃了 LLM 裁判的结果**

通过数据库调查，确认了以下实际案例：
- `cosplay_events.id=154`（远航星SC·TIA）与 `id=180`（成都远航星SC·TIA动漫游戏嘉年华）的 ratio ≈ 0.69，Fusion Agent 已判定为 `True`（同一活动），`normalized_event_id` 均为 100
- 但物化层 Union-Find 因 ratio < 0.75 将其分裂为 `97bec...` 和 `ee521...` 两个独立展示节点

## Goals / Non-Goals

**Goals:**
- 消除物化聚类与 Fusion Engine 判定结果之间的语义不一致
- 使 `final_exhibition_view` 中的节点与 `normalized_events` 中的节点保持一对一或多对一的正确映射关系
- 移除冗余的 Union-Find 聚类代码，简化服务层实现
- 保持冷热分区、确定性哈希 ID、原子事务等核心架构不变

**Non-Goals:**
- 修改 Fusion Engine（analyze 阶段）的判定逻辑
- 修改数据库表结构（`final_exhibition_view`、`event_mappings`、`normalized_events` 表结构均不变）
- 修改 `query_service.py` 的 UNION ALL 兼容路径（保持安全兜底）
- 解决 Fusion Engine 本身的误判或漏判问题

## Decisions

### 1. 以 `normalized_event_id` 为物化分组键，完全替代 Union-Find

**方案选择**：在 Step 6 处将 `active_schedules` 按 `cosplay_events.normalized_event_id` 分组，同一 `normalized_event_id` 的所有日程合并为一个物化超级节点。通过 LEFT JOIN `normalized_events` 直接获取权威 `standard_name`、`city`、`event_type` 字段作为展示信息。

**对比权衡**：

| | 方向 A（补丁）| 方向 B（本方案）|
|---|---|---|
| 原理 | 在 Union-Find 前预先 union 同 ne_id 的记录 | 完全跳过 Union-Find，直接按 ne_id 分组 |
| 代码变更 | +40 行，Union-Find 与预分组并存 | -200 行净减，逻辑单一清晰 |
| 根治程度 | 治标（仍依赖 Union-Find 处理未绑定记录）| 治本（物化层彻底信任 Fusion Engine）|
| 维护成本 | 两套聚类逻辑并行 | 单一来源 |

**选择 B 的核心 rationale**：`cosplay_events.normalized_event_id` 在实际数据中 100% 填充率（133/133），Fusion Engine 是系统中唯一具备 LLM 语义理解能力的聚类来源，物化层不应该也不需要重新发明一套纯统计聚类。

### 2. 权威名称来自 `normalized_events.standard_name`，而非 `cosplay_events.event_name` 代表值

**方案选择**：通过 `LEFT JOIN normalized_events ne ON ce.normalized_event_id = ne.id`，直接读取 `ne.standard_name` 作为物化节点的 `standard_name`，而不是从聚类组内取 min-id 记录的 `event_name`。

**rationale**：`normalized_events.standard_name` 是 Fusion Engine 在创建超级节点时确立的权威名称（通常是最先到来的那条日程的名称）。原来的 min-id 代表法在此案例中会把"远航星SC·TIA"（id=154）确立为代表名——这是正确的，但其逻辑依赖在 Union-Find 有多个成员时仍然偶然正确，而直接读 `ne.standard_name` 从机制上保证正确。

### 3. 保留 `normalized_event_id` 为 NULL 的防御性降级路径

**方案选择**：对 `normalized_event_id` 为 NULL 的日程（正常情况不存在），仍为其单独建档，使用 `f"{name_slug}_{ce.id}"` 附加 ce.id 防止哈希碰撞，不触发 Union-Find。

**rationale**：零额外成本的防御性保护，确保在数据异常时不会引发 rebuild_view 崩溃，同时不污染正常节点。

### 4. 不修改 `query_service.py` 的 UNION ALL 兼容路径

**方案选择**：保留 `get_event_centric_summary` 和 `get_normalized_events` 中的第二分支（旧轨 normalized_events JOIN cosplay_events WHERE ce.id NOT IN event_mappings）。

**rationale**：此分支在正常流程（materialize 已运行）下返回空集，但在 materialize 尚未首次运行时仍能保障数据可见。保留此安全网是无代价的防御手段，不影响已修复的物化结果。

### 5. 稳定化物化主键 UUID (`winner_id`)，基于 `normalized_event_id` 生成

**方案选择**：对于正常归一化的超级节点，其物化主键 `winner_id` 不再基于可变的时间段/周（`date_bucket`）计算 MD5，而是直接对 `normalized_event_id`（融合引擎输出的唯一、不可变的主键 ID）进行 MD5 编码生成。

**rationale**：原方案中 `date_bucket` 可能会因为后续增量日程的添加而发生变动，进而造成超级展示节点的 UUID 发生哈希抖动。改用 `normalized_event_id` 生成后，只要融合节点不被物理合并/删除，物化展示主键 UUID 保证 100% 绝对稳定。对于 `NULL` 降级兜底的单日程，继续使用 `f"{name_slug}_{ce.id}"`（包含唯一且不动的 `ce.id`）作为输入以确保稳定。

### 6. 引入 SQL 稳定排序，保障冲突解决机制确定性

**方案选择**：在 Step 3 捞取活跃日程的 SQL 查询中追加显式且不随索引变更而飘移的 `ORDER BY ce.id ASC` 稳定排序条件。

**rationale**：在 SQLite 中无 `ORDER BY` 的检索顺序是随机的。如果在不同运行周期内，相同指纹的超级节点之间的排序改变，会导致后续后缀累加（如 `_1`、`_2`）被错误调换。显式排序彻底消除了指纹冲突时的碰撞编号随机化问题。

### 7. 事务前指纹冲突解析内存化，消除写锁内 $O(N)$ SELECT

**方案选择**：在 `BEGIN IMMEDIATE;` 写事务锁前，在内存中汇集已冻结的节点指纹以及本轮即将插入的新节点指纹，在 Python 内存中自增完成冲突去重（后缀分配）。在事务内部仅执行无读操作的 `INSERT`。

**rationale**：原方案中在排他锁事务内以 $O(N)$ 进行 Python-DB 往返查重，会造成 SQLite 锁持有时间过长，并在并发环境下阻塞读写。内存指纹树计算将查询损耗降低为 $O(0)$。

### 8. 日志事务化及防御逻辑解析去重

**方案选择**：
1. 将 `materialize_audit.json` 的物理 I/O 写入逻辑移入 `with conn:` 事务内。如果发生磁盘或文件系统异常抛出，将触发数据库 `ROLLBACK`，并准确打印回滚警告，避免状态与提示违背。
2. 消除防御逻辑中重复的 `parse_city` 以及两次重复的 `strptime` 日期转换。

---

## Risks / Trade-offs

- **[Risk 1] Fusion Engine 本身的误判会被直接物化**
  - *Mitigation*：这是正确的行为——物化层应该体现 Fusion Engine 的判定结果，包括其错误。修正 Fusion Engine 的误判逻辑是独立的关注点，不在本变更范围内。现有的 `event_aliases` 缓存和 LLM 3 次重试机制已对此有基础防护。

- **[Risk 2] 确定性哈希 UUID 在归一化事件节点变更时会变动**
  - *例如*：如果使用了 deduplicate 命令物理删除了 loser 节点，关联的日程会被重定向到 winner 节点，对应的 `normalized_event_id` 改变。
  - *Mitigation*：这是合法的重构行为，因为此时在物理逻辑上确实合并为了另一个事件，主键发生变动是正确的。

---

## Migration Plan

1. 无数据库 Schema 变更，无需迁移脚本
2. 部署新代码后，首次执行 `uv run python src/main.py materialize`（或下一次 `process`），物化表热区将以新算法完整重建
3. 本次重建后，物化超级节点的 UUID 会自动从原本以“周”哈希转为以“归一化ID”哈希，且后续绝对稳定。
4. 无需 Rollback 准备——如需回退，仅需还原 `materialize_service.py` 并重新执行 materialize 命令即可

