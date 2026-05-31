## Context

在全新重构的物化呈现去重服务中，`MaterializeService.rebuild_view()` 会读取活跃事实日程并在内存中划分 `(parsed_city, event_type)` 聚类子池单独运行 Union-Find 算法。这种设计的性能和结构非常清晰，但物理上彻底隔离了“未知”城市与“具体”城市的数据流。这导致任何地名提取为 `"未知"` 的日程（即使其名字为 “Bilibili World 2026”）在物化呈现阶段都无法归入 `"上海"` 的具体漫展超级节点中，分裂成了冗余节点，违背了系统自动时空纠偏的设计原则。

## Goals / Non-Goals

**Goals:**
- 在不破坏现有三表解耦及物理隔离高性能的前提下，实现物化重建阶段的“离线空间自适应纠偏”。
- 确保未知地名但时间档期、相似名称符合的日程（如“上海BW”在上海与“BW”在未知）能够被智能重定向并级联归宿到具体城市的超级展示节点中。
- 保留未匹配成功的未知日程在“未知”子池中的兜底聚类聚合能力。

**Non-Goals:**
- 变更 `cosplay_events` 的只读事实表状态，不对爬取/提取日程数据执行 destructive mutation。

## Decisions

### 1. 聚类重组与多阶段流式比对
重构 `MaterializeService.rebuild_view()` 内部的 Union-Find 聚类部分：
1. **日程按空间分流**：
   将 `remaining_schedules`（待处理活跃日程）物理划分为 `concrete_schedules`（具体城市日程，`parsed_city != "未知"`）与 `unknown_schedules`（未知城市日程，`parsed_city == "未知"`）。
2. **第一阶段：聚类具体城市**：
   先仅使用 `concrete_schedules` 划分子池聚类，在 `new_normalized_nodes` 中生成所有活跃的具体城市超级节点。
3. **构建具体城市对照池**：
   汇总 `frozen_nodes` 中的具体城市冻结节点与新生成的活跃具体城市节点，形成一个全局具体城市超级节点集合 `all_concrete_nodes`，提取其 `name_slug` 作为比对依据。
4. **第二阶段：未知日程自愈升级与级联匹配**：
   遍历 `unknown_schedules`，对其在 `all_concrete_nodes` 中进行 $\pm 7$ 天时间窗相容和名称相似度 $\ge 0.75$ 的核验。若匹配成功，直接将其 `new_mappings_dict` 级联重定向映射至该具体城市超级节点 ID；若不匹配，则放入 `remaining_unknown_schedules` 中。
5. **第三阶段：未知日程兜底聚类**：
   仅对 `remaining_unknown_schedules` 独立在 `"未知"` 子池内运行 Union-Find 并生成新的 `"未知"` 属性超级节点。

### 2. 匹配规则复用
级联匹配时，无损复用系统原有的 `is_date_compatible` 时空区间相容条件、SequenceMatcher 相似度比对、以及 `alias_cache` 别名表快取规则，保证匹配决策的高抗灾和完全对齐。

## Risks / Trade-offs

* **[Risk]** $\to$ 新增的两阶段流式比对对内存和计算时间的影响。
* **[Mitigation]** $\to$ 由于具体城市对照池只在内存中检索比对（且在未知日程和具体日程子集上运行），没有新增任何数据库 `SELECT` 物理 IO，检索复杂度仍然保持在极佳的离线线性常数范围内。
