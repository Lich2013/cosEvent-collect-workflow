## Why

现有的日程系统是以 Coser 个人视角为中心分散存储和展现的。这使得二次元用户、动漫摄影师等无法快速获取以“漫展活动（Event-centric）”为超级节点的大聚合视角情报（例如“CP30 共有哪些 Coser 在哪天去，出什么角色，在哪个摊位”），也无法纯粹查询“在哪个城市哪一天有什么漫展”的时空排期日历。本变更旨在通过反向推导活跃 Coser 的排班数据，实现漫展超级节点的自动归一化与时空区间融合，提供漫展集结情报看板与漫展日历排期。

## What Changes

- **数据库层架构演进**：新增 `normalized_events` 物理表，用于存储归一化后的标准漫展超级节点（包含指纹、标准名称、城市、融合举办日期区间）；在 `cosplay_events` 表中新增 `normalized_event_id` 外键关联，支持一对多级联关联，并维护原子性事务。
- **时空融合引擎 (Temporal Fusion Engine)**：引入基于 Python 标准库 `difflib.SequenceMatcher` 与城市粗筛的启发式聚类算法，自动计算同城多名 Coser 同一时间窗口内模糊漫展名称（如 CP30 与 Comicup30）的相似度，并自动融合日期区间边界（Outer Bounding），生成指纹唯一的漫展超级节点。
- **漫展集结命令行看板 (By-Event Summary)**：扩展 CLI 命令行工具，提供 `cosevent summary --by-event` 命令，以漫展为第一层级优雅呈现已集结 Coser 人数、参展名单、摊位、扮演角色与具体参展日期。
- **漫展排期日历命令行与导出 (Event Calendar)**：新增 CLI `cosevent calendar` 子命令，提供以时间轴 + 城市为维度的全国/特定城市漫展展讯看板；同时扩展 `export` 服务，支持一键导出包含高美观度表格的 Markdown 日历看板 (`--view calendar`)。

## Capabilities

### New Capabilities
- `event-centric-aggregation`: 漫展维度的时空聚类、多源信息归一化整合与超级节点映射能力。
- `event-calendar-view`: 纯粹漫展视角的时间轴展讯日历看板呈现能力，支持多城市、未来/全量范围精细筛选。

### Modified Capabilities
- `data-export`: 扩展导出能力，新增 `calendar` 视图模式，支持以 Markdown 表格的形式格式化输出纯漫展展讯。

## Impact

- **存储层 (`src/models/db_models.py`, `src/services/db_service.py`)**：
  - 新增 `normalized_events` 建表物理逻辑。
  - 在 `cosplay_events` 表中安全增加外键关联。
  - 增强数据录入事务，在 AI 日程提炼保存时自动触发时空归一化与融合判定，确保原子性。
- **展现与导出层 (`src/services/export_service.py`, `src/main.py`)**：
  - 新增 `cosevent calendar` 命令。
  - 升级 `cosevent summary` 支持 `--by-event` 视图。
  - 升级 `cosevent export` 支持 `--view calendar` 并输出 Markdown 排期表。
- **兼容性**：完全向后兼容，不改变原有的 Coser 管理、独立爬行与独立分析的单体数据流。
