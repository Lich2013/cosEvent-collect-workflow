## 1. 数据库表结构初始化与冷热解耦迁移

- [ ] 1.1 在 `src/models/db_models.py` 中设计并初始化三表解耦结构：将 `cosplay_events` 改造为只读事实表，并在 `init_db()` 中物理新增 `event_mappings` 映射关系表与 `final_exhibition_view` 物化呈现展示表。
- [ ] 1.2 为物化表中的主键配置 `id VARCHAR(32) PRIMARY KEY` 以容纳确定性哈希 ID。

## 2. 滑动窗口分区与确定性指纹聚类算法实现

- [ ] 2.1 新建服务模块 `src/services/db/materialize_service.py` 并编写确定性 MD5 指纹 ID 计算函数：`generate_deterministic_id(city: str, name_slug: str, event_type: str, date_bucket: str) -> str`。
- [ ] 2.2 实现冷热滑动窗口过滤策略：以 `T_cold = 今天 - 30天` 为交界线，实现对有具体日期日程的整展级冷冻（`is_frozen = 1`）判定。
- [ ] 2.3 实现对 `"未知"` 日期日程的逻辑冷冻判定（当关联博文的发布日期 `published_at` 早于 30 天之前时冷冻）。
- [ ] 2.4 编写内存聚类算法：仅对热数据日程运行 Gated 融合聚类，并在 `BEGIN IMMEDIATE` 事务强锁中清空热区物化行并批量 `INSERT` 重写新行，同时维护 `event_mappings` 指向。
- [ ] 2.5 实现将每次聚类归并决策树链路输出到 `runtime/logs/materialize_audit.json` 的轨迹审计逻辑。

## 3. 分析流程剥离与主链定时批重建集成

- [ ] 3.1 重构 `src/services/fusion_service.py`，物理剥离分析（`analyze`）阶段的原地增量修改和超级节点改写行为，使提取出的日程以只读状态存入事实表。
- [ ] 3.2 在 `src/main.py` 中注册 `materialize` CLI 重建命令，提供手动维护入口。
- [ ] 3.3 在 `src/services/workflow_orchestrator.py` 的主命令 `process` 定时调度最末尾，级联挂载 `MaterializeService.rebuild_view()` 的单次批重建调用。

## 4. 单元与集成测试回归验证

- [ ] 4.1 在 `tests/` 中编写针对冷热滑动窗口隔离、确定性哈希 ID、冷冻未知日程以及 CLI 重建的专用集成测试。
- [ ] 4.2 运行全量 `pytest tests/` 自动化回归测试套件确保 100% 绿色通过。
