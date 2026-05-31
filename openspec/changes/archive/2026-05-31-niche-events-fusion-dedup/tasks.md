## 1. 共享解析函数抽离与智能旁路闸门实现

- [ ] 1.1 在 `src/utils/parsers.py` 中增加公共事件清洗函数 `clean_event_name(name: str) -> str`，将原 `EventFusionService._clean_name` 中的字符串转换与正则剥离逻辑完整移入并导出。
- [ ] 1.2 重构 `src/services/fusion_service.py` 和 `src/services/db/coser_repository.py` 以从 `src.utils.parsers` 导入和调用 `clean_event_name`。
- [ ] 1.3 在 `src/services/fusion_service.py` 头部增加小众泛称黑名单 `BYPASS_GENERIC_NAMES = {"签售", "一日店长", "店长", "摄影会", "受邀模特", "快闪", "签售会"}`。
- [ ] 1.4 重构 `find_or_create_normalized_event` 头部的小众活动旁路逻辑：利用条件 `(name_slug in BYPASS_GENERIC_NAMES) or (len(name_slug) <= 3 and no_city_name)` 精准判断旁路决策。确保“一日店长”安全旁路，而长度为 4 且非泛称的“罗森店长”放行进入融合匹配。

## 2. 数据库原子事务去重逻辑与 CLI 集成

- [ ] 2.1 新增模块 `src/services/db/dedup_service.py` 并编写 `DeduplicationService`，在单一 SQL 原子事务中实现基于 `[city, name_slug, date_window (与 O(1) 通道完全对齐的 ±7天)]` 规则的存量冗余超级节点智能合并算法。
- [ ] 2.2 实现 `cosplay_events` 日程记录的级联 `UPDATE` 重定向绑定。
- [ ] 2.3 实现别名表级联重定向及 `UNIQUE(alias_name, city)` 约束冲突捕获，输出含源-宿 ID 且带有别名详情的 `[Spatial Rectification Audit]` 可观测审计日志，并安全删除 Loser 别名冲突行以避开 SQLite 主键死锁。
- [ ] 2.4 对 `normalized_events` 中 Loser 节点的 `DELETE` 清理，全部使用 `try-except sqlite3.IntegrityError` 进行健壮防御，防范外键冲突物理崩溃。
- [ ] 2.5 在 `src/main.py` 中挂载 `deduplicate` CLI 控制台命令，提供面向用户的命令行一键去重入口。

## 3. 测试契约调整与回归验证

- [ ] 3.1 修改 `tests/test_niche_events.py` 中的 `test_fusion_bypass_for_niche_events` 单元测试，将断言 `assert event_id_1 != event_id_2` 反转修改为相同 ID 断言（因为“Nikke罗森一日店长”已放行融合），并同步更新测试文件中的陈旧注释以防逻辑冲突。
- [ ] 3.2 编写专门的存量去重集成测试，验证重定向完整性、Audit 审计日志捕获以及外键删除保护。
- [ ] 3.3 运行全量 `pytest tests/` 自动化测试套件确保 100% 绿色回归通过。
