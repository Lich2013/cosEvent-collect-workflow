## Why

置顶或汇总微博（Pinned Posts）常被 Coser 多次二次编辑修改以更新其最新的 Cosplay 线下行程排班表。
由于微博官方 Ajax API 不提供稳定的最后编辑时间字段，原系统锁死首次创建时间 `created_at`。这在跨年编辑的场景下，会导致 LLM 语义相对日期解析原点出错（如 2025 年编辑的 2024 年博文，提取 `10.6` 会错判为 `2024-10-06` 从而被系统判定过期过滤），产生提取数据丢失；同时，为处理 Coser 撤销或改期行程而进行的“物理级联删除”存在高危性与数据盲区（无法留存取消痕迹）。
因此，本提案引入“博文版本历史追溯（Append-only Suffix Versioning）”与“日程软状态机管理（Soft State Machine）”双重企业级加固升级，在规避物理删除风险的同时，实现极高的业务可追溯性与数据完整性。

## What Changes

- **微博博文后缀版本化存储**：在 `weibo_scraper.py` 中，当监测到微博 `edit_count > 0` 时，动态为 `post_id` 追加版本号后缀（如 `5039129502#v1`），在 `db_service.py` 中作为全新记录 `INSERT` 写入数据库，无损保留每一版正文历史。
- **编辑时间动态重锚 (Re-anchoring)**：对于编辑版的博文，在爬行拦截后，强制将其 `published_at`（发布时间锚点）校准为当前抓取时间，保证 LLM 相对时间推理年份与时间的物理精准。
- **日程软状态机升级 (Soft State Machine)**：在本地 SQLite 的 `cosplay_events` 表中新增 `status`（状态）字段（文本型，默认值 `'未开始'`），包含：`'未开始'` (未来有效行程)、`'已结束'` (历史过期日程)、`'已取消'` (软删除废弃日程)。
- **精细化软状态流转与比对**：在保存最新版的活动列表时，在事务中开启状态转移比对。锁定属于该微博所有历史版本的“未发生未来日程”，直接 `UPDATE` 其 `status = '已取消'`（软删除），对已经发生过的历史日程继续执行冷冻保护，杜绝任何高危物理删除。
- **BOM CSV 导出精细化过滤**：调整 CSV 导出 SQL 查询逻辑，自动在查询阶段过滤剔除 `'已取消'` 状态的行程，仅导出高保真的有效行程。
- **单元测试断言升级**：更新 `test_cosevent.py`，新增版本后缀生成、时间重锚对齐、软状态机更新事务隔离及 CSV 导出状态过滤的完备断言。

## Capabilities

### New Capabilities
<!-- 无新增 Capability -->

### Modified Capabilities
- `content-scraping`: 微博爬取模块支持二次编辑感知、`post_id` 后缀版本控制与 `published_at` 编辑时间重置。
- `event-extraction`: 智能体提炼与入库流程全面升级为软状态机管理，淘汰高危物理删除，支持多版本未来日程级联软状态转移，并适配 CSV 导出过滤。

## Impact

- **受影响数据库结构**：`src/models/db_models.py` (在线热升级，为 `cosplay_events` 新增 `status` 列)
- **受影响爬虫文件**：`src/tools/weibo_scraper.py` (版本后缀拼接与重锚发布时间)
- **受影响服务层**：`src/services/db_service.py` (状态机转移算法逻辑实现、导出 SQL 查询过滤)
- **受影响导出层**：`src/services/export_service.py`
- **受影响测试文件**：`tests/test_cosevent.py` (增加全量软状态机与版本控制单元测试)
