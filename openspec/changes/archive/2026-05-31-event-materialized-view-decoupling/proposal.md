## Why

当前系统采用“原地增量修改”与“物理级联删除”的架构来维护超级归一化节点。这种设计存在严重的数据破坏性：一旦对既存日程进行重定向或去重，就会永久破坏原始爬取日程的完整性，无法在保留原始排班文案的同时进行无损回溯。此外，频繁的原地增量合并也容易在并发写入时霸占 SQLite 写锁，导致前台读取看板发生死锁或崩溃。

## What Changes

- **只读日程事实表（Fact Table）**：将 `cosplay_events` 改造为只读的事实表，永久保留最初解析的原始地名、时间与文案，不再在分析或去重时执行破坏性的 `UPDATE` 或 `DELETE`。
- **冷热数据滑动窗口分区**：将日程划分为冷历史数据与热活跃数据。仅对最近 30 天内（或未知时间且博文发布在 30 天内）的热日程在 Python 内存中运行 gated 融合聚类，已举办完毕的历史“冷数据”物化关系则做永久冻结保护。
- **确定性哈希 ID 展示视图**：创建专门的物化呈现表 `final_exhibition_view`，使用 `MD5(city + name_slug + event_type + date_bucket)` 计算出的确定性哈希值作为超级节点的持久主键，物理规避因重建导致的 ID 抖动，保障前台路由及外部引用的稳定性。
- **批处理单次物化重建**：将物化呈现表的重建从增量触发剥离，改为在主任务链 `process` 完全结束时（或通过 CLI 定时任务）一次性异步/单次执行，杜绝 SQLite 锁竞争。
- **归并轨迹审计日志**：输出 `runtime/logs/materialize_audit.json`，完整记录聚类与重定向合并的可观测轨迹，避免黑盒化。

## Capabilities

### New Capabilities
- `event-materialized-view`: 智能二次元活动物理物化呈现与冷热滑动窗口去重。

### Modified Capabilities
<!-- 无修改的已有 Capability 需求合约 -->

## Impact

- **Affected Code**: `src/services/fusion_service.py` (剥离增量原地合并), `src/main.py` (挂载一键物化重建指令), `src/services/workflow_orchestrator.py` (在主任务链结束时触发重建)
- **New Code**: `src/services/db/materialize_service.py` (新增冷热物化重建服务层)
- **Dependencies**: sqlite3, hashlib, click
