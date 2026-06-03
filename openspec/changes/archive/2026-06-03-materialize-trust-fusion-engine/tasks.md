## 1. 重构 `MaterializeService.rebuild_view()` 核心聚类逻辑

- [x] 1.1 修改 Step 3 的 SQL 查询，增加 `LEFT JOIN normalized_events ne ON ce.normalized_event_id = ne.id`，在结果集中新增 `ne.standard_name`、`ne.city`、`ne.event_type` 三列，并在 Python 中映射为 `canonical_name`、`canonical_city`、`canonical_event_type` 字段（`NULL` 时降级回 `ce.*` 字段兜底）。
- [x] 1.2 移除 Step 6（alias_cache 加载逻辑）。
- [x] 1.3 移除 Step 7（活跃日程与冻结节点的名称相似度边界比对逻辑，约 25 行）。
- [x] 1.4 将 Step 8（Union-Find 两两比对聚类，含 Step 8.1-8.5，约 240 行）替换为以 `normalized_event_id` 为分组键的直接聚合逻辑：将 `active_schedules` 按 `normalized_event_id` 分桶（`norm_groups: dict[int, list]`），同组日程生成同一个物化超级节点。
- [x] 1.5 在分组聚合逻辑中，使用 `canonical_name` / `canonical_city` / `canonical_event_type` 作为超级节点的权威展示字段，与原有的 `generate_deterministic_id` 和冷热冻结判定逻辑对接（逻辑不变，仅输入来源变化）。
- [x] 1.6 新增 `normalized_event_id` 为 `NULL` 的防御性降级分支：对 `ungrouped_schedules` 中每条日程，使用 `f"{name_slug}_{ce.id}"` 作为哈希种子单独建档，不触发聚类。
- [x] 1.7 简化 Step 9.3 的 `final_mappings` 合并逻辑，移除已不存在的 `schedule_to_frozen_mapping`，直接使用 `new_mappings_dict` 写入 `event_mappings`。

## 2. 清理不再使用的模块级代码

- [x] 2.1 删除 `materialize_service.py` 顶部的 `UnionFind` 类（约 18 行）。
- [x] 2.2 删除模块级 `is_date_compatible` 函数（约 20 行）。
- [x] 2.3 移除已不再使用的 `difflib` 导入（仅 materialize_service 使用，fusion_service 有独立导入）。

## 3. 测试验证

- [x] 3.1 手动执行 `uv run python src/main.py materialize`，在运行日志中确认：不再出现 Union-Find 相关日志，且 `[Materialize View] 物化展示表重建成功完成！` 中 `new_clusters` 数量与 `normalized_events` 中活跃节点数一致。
- [x] 3.2 执行 `uv run python src/main.py summary --by-event`，确认"远航星SC·TIA"与"成都远航星SC·TIA动漫游戏嘉年华"不再作为两个独立节点出现，坂坂白与粽子淞均显示在同一超级节点下。
- [x] 3.3 运行全量回归测试 `uv run pytest tests/ -v`，确保 100% 绿色通过。

## 4. 优化与健壮性加固（基于 CR 评审反馈）

- [x] 4.1 重构 `winner_id` 生成逻辑：对于正常归一化的超级节点，直接使用 `normalized_event_id` 的 MD5 散列作为物化主键，确保主键稳定性。
- [x] 4.2 在 Step 3 的 SQL 查询末尾追加 `ORDER BY ce.id ASC`，保障读取顺序的绝对稳定性。
- [x] 4.3 在内存中提前完成 `new_normalized_nodes` 的指纹重名检测与后缀生成（结合 `is_frozen = 1` 历史节点指纹及本轮已分配指纹），消除写事务（BEGIN IMMEDIATE）内部的 $O(N)$ 循环 SELECT 查询。
- [x] 4.4 将审计日志的物理写入 `materialize_audit.json` 移入 `with conn:` 数据库事务块内部（COMMIT 之前），使磁盘 I/O 错误能触发数据库 Rollback，并保证回滚错误日志与真实状态一致。
- [x] 4.5 简化 Step 8 `ungrouped_schedules` 中的兜底逻辑，直接复用已经挂载的 `canonical_*` 属性，消除重复调用 `parse_city` 冗余。
- [x] 4.6 优化 Step 8 的日期校验，保存首次 `strptime` 产生的 `dt` 实例，消除重复解析开销。
- [x] 4.7 运行全量测试并观察 `summary` 结果，验证各项加固是否正常运转。

