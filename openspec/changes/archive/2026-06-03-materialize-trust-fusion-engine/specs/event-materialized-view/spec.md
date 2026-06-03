## MODIFIED Requirements

### Requirement: 滑动冷热区间划分与未知时间日程逻辑冷冻
系统在物化呈现阶段，必须且 SHALL 执行冷热数据滑动窗口分区计算，仅对活跃的热日程进行增量物化处理以保障性能：
1. 热活跃窗口阈值：设定为 `T_cold = 今天 - 30天`。
2. 历史冷整展冻结：对于有明确日期的超级节点，只有当该节点下的最大结束时间 $\max(\text{event\_date}) < T_{cold}$ 时，才将其在物化视图表中标记为冻结（`is_frozen = 1`）；
3. 未知时间逻辑冷冻：对于 `"未知"` 日期的日程，若其关联博文的发布时间 `raw_posts.published_at` 早于 30 天之前，系统必须将其标记为冷数据（`is_frozen = 1`）进行归档冷冻，不再参与活跃区物化计算。

> **变更说明**：删除原文中"热活跃聚类算法"的表述。物化层不再运行独立的相似度聚类，而是直接以 `normalized_event_id` 分组，冷热判定逻辑不变。

#### Scenario: 活跃日程参与热物化分组，而古老未知日程被安全冻结
- **WHEN** 重建物化呈现视图时，检测到 10 天前的活跃日程"Nikke罗森一日店长"（热日程）与 90 天前发布且至今未纠偏的未知时间"店长"（冷日程）
- **THEN** 活跃店长日程以其 `normalized_event_id` 为分组键正常参与物化重建，而古老未知日程被物理冻结，直接归档至历史展示分区，不触发任何 LLM 调用

## NEW Requirements

### Requirement: 物化重建聚类策略——以旧轨融合判定为权威分组来源
系统在物化重建时，必须且 SHALL 以 `cosplay_events.normalized_event_id`（由 analyze 阶段 Fusion Engine 写入的旧轨归一化 ID）为唯一聚类分组键，将同一 `normalized_event_id` 下的所有活跃日程合并为一个物化超级展示节点。系统 **严禁且 SHALL NOT** 在物化阶段独立运行基于 `SequenceMatcher` 相似度阈值的 Union-Find 重新聚类算法，以避免物化层与 Fusion Engine 判定结果产生语义不一致。

聚类规则：
1. **权威分组键**：以 `normalized_event_id`（整数，引用 `normalized_events.id`）作为唯一分组键。
2. **权威展示信息**：通过 `LEFT JOIN normalized_events` 读取 `ne.standard_name`（权威名称）和 `ne.city`（权威城市）作为物化节点的展示字段，不从 cosplay_events.event_name 推导。
3. **防御性降级**：对极少数 `normalized_event_id` 为 `NULL` 的日程（正常情况下不存在），系统必须为其单独建档，使用 `f"{name_slug}_{ce.id}"` 作为哈希种子防止碰撞，不触发聚类逻辑。

#### Scenario: Fusion Engine 裁判过的同义活动在物化层正确合并为单一节点
- **WHEN** 数据库中存在两条 `cosplay_events` 记录——坂坂白的"远航星SC·TIA"与粽子淞的"成都远航星SC·TIA动漫游戏嘉年华"——二者的 `normalized_event_id` 均指向同一个 `normalized_events.id`（由 Fusion Agent 在 analyze 阶段裁定并写入）
- **THEN** 物化重建后，`final_exhibition_view` 中仅生成一个展示节点（`standard_name` 取自 `normalized_events.standard_name`），`event_mappings` 中两条 cosplay_events 的 `raw_event_id` 均指向该同一 UUID 节点，`summary --by-event` 输出中不再出现两个独立的"远航星SC·TIA"相关节点

#### Scenario: normalized_event_id 为 NULL 的孤立日程降级独立建档
- **WHEN** 物化重建时发现某条 cosplay_events 记录的 `normalized_event_id` 为 `NULL`（防御性场景）
- **THEN** 系统为该日程单独生成一个物化超级节点，使用 `f"{name_slug}_{ce.id}"` 作为哈希种子计算确定性 UUID，不触发聚类逻辑，不引发 rebuild_view 崩溃

## REMOVED Requirements

### Requirement: 物化重建空间自适应纠偏
**Reason**：本需求依赖独立的 Union-Find 相似度聚类架构（原 Step 8.3-8.4），专门处理"未知"城市日程与具体城市节点的跨空间合并。在新方案中，"未知"城市的日程已由 Fusion Engine 在 analyze 阶段通过时空纠偏写入正确的 `normalized_event_id`（旧轨 `fusion_service.py` 中的 Task 3.2 就地物理升级逻辑），物化层无需再单独处理未知城市的空间自适应问题。

**Migration**：无需迁移操作。依赖 Fusion Engine 的 `find_or_create_normalized_event` 方法中既有的"未知"城市就地升级机制（`city_cleaned != '未知'` 时的 `unknown_nodes` 升级路径）保障空间一致性。
