## 1. 跨平台与跨博文 Coser 级 In-place 智能去重合并

- [x] 1.1 在 `src/services/db/event_repository.py` 的 `save_extracted_events_transactional` 方法中，新增在 IMMEDIATE 锁内对该 Coser 已存 active 未来日程的查询过滤逻辑。
- [x] 1.2 实现 `cosplay_events` 存在重复日程时的 In-place 覆盖合并逻辑（拼接合并描述 `old_desc | new_desc`、升级 `raw_post_id`、`source_url` 与 `confidence`），避免插入重复冗余行。

## 2. 简称对齐与自适应时空裁判介入

- [x] 2.1 在 `src/services/fusion_service.py` 的 `_clean_name` 清洗方法中，添加常用 ACG 简称（"bw" -> "bilibiliworld", "cp" -> "comicup"）的预处理替换对齐。
- [x] 2.2 在 `src/services/fusion_service.py` 的时空匹配逻辑中，针对同城且档期窗口 $\le 3$ 天内重叠的既存节点，放开 LLM 裁判的 ratio 得分触发区间（从原先的 $[0.5, 0.75)$ 放宽到 $[0.2, 0.75)$）。

## 3. 看板与导出动态时间推算继承

- [x] 3.1 在 `src/services/db/query_service.py` 中，重构 `get_all_events`、`get_event_centric_summary` 聚合查询，让读取到的 '未知' 日期日程能够动态继承其关联超级漫展的 `start_date` 与 `end_date` 包络区间。
- [x] 3.2 升级 `src/views/terminal_renderer.py` 中 summary 看板与 calendar 看板的展现逻辑，当日程日期为推算时间时，在控制台追加 `(推算自超级节点)` 字样并进行等宽彩显拼接。
- [x] 3.3 升级 `src/services/export_service.py` 的导出渲染逻辑，确保导出的 txt 报表、csv 报表与 Markdown 日历表格能自动继承超级节点包络时间。

## 4. 单元测试覆盖与全面功能验证

- [x] 4.1 在 `tests/` 下新建单元测试，验证 Coser 多平台重复发布同一活动时，日程行数不增加，且描述成功拼接、链接成功更新。
- [x] 4.2 编写简称对齐与裁判低得分区间触发测试，验证 "上海bw2026" 能与 "bilibiliworld2026" 成功通过 LLM 裁判融合并写入别名缓存表。
- [x] 4.3 编写时间推算继承单元测试，验证单体日程为 '未知' 时，日历看板、控制台以及导出文件均正确继承超级节点的包络时间。
- [x] 4.4 运行全量 `pytest` 确保 100% 绿灯无损兼容。
