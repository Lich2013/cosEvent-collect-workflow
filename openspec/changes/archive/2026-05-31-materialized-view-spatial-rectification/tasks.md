## 1. 内存级分流与对照索引构建

- [x] 1.1 修改 `src/services/db/materialize_service.py`：在 `rebuild_view` 内存聚类段，将活跃日程 `remaining_schedules` 物理分流为 `concrete_schedules` (具体城市日程) 与 `unknown_schedules` (未知城市日程)。
- [x] 1.2 在聚类完具体城市生成 `new_normalized_nodes` 后，编写融合收集逻辑，合并 `frozen_nodes` 与 `new_normalized_nodes` 中所有的具体城市展示节点，构建内存全局对照对照索引池 `all_concrete_nodes`。

## 2. 空间自适应纠偏与自愈归位算法实现

- [x] 2.1 编写遍历比对逻辑：对所有 `unknown_schedules` 在 `all_concrete_nodes` 中检索匹配（复用 `is_date_compatible`、`SequenceMatcher` 及 `alias_cache` 快取）。
- [x] 2.2 实现匹配后的级联纠偏动作：匹配成功直接计入 `new_mappings_dict` 并统计；未成功匹配的日程放入 `remaining_unknown_schedules` 中并兜底进行未知子池内的聚类。

## 3. 单元测试更新与回归验证

- [x] 3.1 在 `tests/test_niche_events.py` 的物化视图单元测试中追加测试断言：在数据库写入具体城市节点（上海 BW，7.10-7.12）以及未知城市节点（BW，7.11-7.12），验证物化重构重建后，未知 BW 被自动升级并纠偏归并至上海 BW 节点中。
- [x] 3.2 运行全量 `.venv/bin/pytest tests/` 回归测试套件，验证纠偏匹配精确性并确保 100% 绿色通过。
