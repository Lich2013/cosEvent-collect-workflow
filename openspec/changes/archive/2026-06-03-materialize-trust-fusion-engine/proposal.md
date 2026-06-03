## Why

`MaterializeService.rebuild_view()` 在批量重建物化展示层时，独立运行了一套基于 `SequenceMatcher` 相似度阈值（`ratio >= 0.75`）的 Union-Find 聚类算法，与 `EventFusionService` 在 analyze 阶段已完成的 LLM 裁判判定结果完全脱节。这导致相似度落在 0.75 灰区的同义活动（如"远航星SC·TIA"与"成都远航星SC·TIA动漫游戏嘉年华"，ratio ≈ 0.69）即使在融合裁判已确认为同一活动后，在物化层仍会被错误分裂为两个独立的超级展示节点，产生前台看板的冗余重复展示。

## What Changes

- **物化聚类算法重构（核心）**：完全移除 `MaterializeService.rebuild_view()` 中的 Union-Find 两两相似度比对逻辑（原文件 Step 6-8.5，约 278 行），替换为以 `cosplay_events.normalized_event_id`（旧轨 Fusion Engine 已完成的判定结果）为权威分组键的直接聚合方案。物化层不再重新计算相似度，彻底信任 Fusion Engine 的结论。
- **旧轨权威信息直接继承**：在 SQL 查询中 JOIN `normalized_events` 表，直接读取 `ne.standard_name`（权威名称）和 `ne.city`（权威城市）作为物化节点的展示信息，取代原有从 `cosplay_events.event_name` 推导的方案。
- **防御性降级兜底**：对极少数 `normalized_event_id` 为 `NULL` 的日程（正常情况下不存在），保留单条独立建档的降级路径，附加 `ce.id` 防止哈希碰撞。
- **代码净减**：移除不再需要的 `UnionFind` 类、`is_date_compatible` 模块级函数及 alias 缓存加载逻辑，净减约 200 行代码。

## Capabilities

### New Capabilities
<!-- 无 -->

### Modified Capabilities
- `event-materialized-view`：修改物化重建的聚类策略——物化层不再独立运行相似度聚类，改为直接以旧轨 `normalized_event_id` 为分组键，确保 Fusion Engine 的 LLM 裁判结果在物化展示层完整体现。

## Impact

- **Affected Code**：`src/services/db/materialize_service.py`（核心重构，净减 ~200 行）
- **New Code**：无
- **Dependencies**：无新增依赖
- **Compatibility**：100% 向后兼容。`final_exhibition_view`、`event_mappings` 表结构不变，`query_service.py` 的 UNION ALL 兼容路径保持不变。
