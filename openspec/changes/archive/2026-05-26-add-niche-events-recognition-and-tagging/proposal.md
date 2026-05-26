## Why

当前系统的 AI 分析与预检规则被局限于传统的大型漫展或常规签售，导致活跃 Coser 参加的一日店长（如主题店特邀店长）、小众摄影会/私设会以及受邀到店模特等具有高二次元面基价值的线下小众日程在 Triage（预检分流）中被误杀，或在 Extractor（提炼智能体）中因地标词根偏差被判定为日常推广而遭低置信度过滤。本变更旨在通过扩容智能体语义边界与引入活动分类打标机制，实现二次元小众线下日程的高精识别与分类看板检索。

## What Changes

- **Triage 与分析 Prompt 指令升级**：
  - 微调首轮 Triage 智能体的 `instructions` 语义描述，显式扩容一日店长、受邀到店和摄影会等小众类别。
  - 升级 `event_analysis.jinja2` 提取提示词模板，注入一日店长、到店特邀等小众活动的提炼准则与典型 Few-shot 样例，锁死置信度下限。
- **数据契约与物理表打标**：
  - 在 Pydantic 强契约模型 `CosEvent` 中扩展新增 `event_type` 属性，强制 Extractor 智能体自动对活动进行物理打标。
  - **物理建表演进**：升级 `cosplay_events` 数据表，物理新增 `event_type` 字段，并包含 `'漫展'`, `'一日店长'`, `'摄影会'`, `'受邀模特'`, `'快闪/签售'` 的 `CHECK` 值域硬核防御。
- **融合引擎自适应旁路 (Engine Bypass)**：
  - 在 `EventFusionService` 物理事务中，当日程为非漫展类型（`event_type != '漫展'`）时，**自动旁路时空聚类比对与 LLM 同盟裁判**，直接独立建超级节点或留空外键，绝对杜绝大型漫展时空指纹库污染与冗余 API 费用。
- **命令行看板与导出分类精筛**：
  - 升级 CLI `summary` 与 `calendar` 视图，支持按类别进行精细的分流展现。
  - 升级 `export` 服务，支持可选参数 `--type` 物理筛选导出。

## Capabilities

### New Capabilities
- `niche-events-tagging`: 二次元小众线下活动日程（一日店长、特邀到店、摄影会等）的智能提炼、置信度锁死与物理分类打标能力。

### Modified Capabilities
- `event-centric-aggregation`: 当日程判定为小众非漫展类型时，物理支持时空聚类及裁判智能体的智能旁路机制。
- `event-calendar-view`: CLI 看板支持按活动类型分组与参数精细化过滤展示。
- `data-export`: 数据导出支持分类精细筛选。

## Impact

- **物理存储层 (`src/models/db_models.py`, `src/models/schemas.py`, `src/services/db_service.py`)**：
  - `CosEvent` schema 增加 `event_type`。
  - `cosplay_events` 数据库建表与热升级检查增加带有 CHECK 约束的 `event_type` 字段。
  - 事务保存自动判断 `event_type` 以做融合引擎自适应旁路。
- **融合引擎层 (`src/services/fusion_service.py`)**：
  - `find_or_create_normalized_event` 第一步前置拦截：对于小众活动类型，不进行同城和日期重叠聚类，直接生成独立漫展超级节点，从源头切断死锁和污染。
- **看板与导出层 (`src/services/export_service.py`, `src/main.py`)**：
  - 各查询接口和 CLI 命令支持 `--type` 参数过滤。
