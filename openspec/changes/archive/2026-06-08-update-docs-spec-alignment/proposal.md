## Why

随着系统各项能力的迭代与沉淀（如小众活动打标与闸门隔离、候选人智能体核验与状态流转、gRPC 凭证自愈刷新、物化呈现视图去重重构等），项目已积累了大量的具体 Specification（`.md` 规约文件）。然而，系统的主文档 `README.md` 与智能体编码规范 `AGENTS.md` 存在较多滞后与不匹配之处。为了保持文档一致性，降低新开发者及大语言模型智能体后续迭代的认知偏差，需要对这两个核心文档进行一次全面的规格对齐更新。

## What Changes

*   **更新 [AGENTS.md](file:///Users/lich/work/cosEvent-workflow/AGENTS.md)**：
    *   补充 `CosEvent` 中缺失的 `event_type` 值域校验。
    *   补齐 `FusionJudgeOutput` 与 `CandidateVerifyOutput` 的 Pydantic 强契约声明。
    *   增补 `event_consensus_judge.jinja2` 等 Jinja2 提示词模板列表。
    *   补充 `is_analyzed = 2` 的三态状态机硬熔断机制与 `BEGIN IMMEDIATE` 强事务锁规约。
    *   新增候选人自动核验流程下的智能体判定、置信度以及待定（`undetermined`）冷却状态流转机制。
*   **更新 [README.md](file:///Users/lich/work/cosEvent-workflow/README.md)**：
    *   在系统整体架构中补充个人主页简介（Bio）虚拟推文合成与合流机制。
    *   补充网页抓取超时自愈、浏览器特征伪装和 B站 gRPC 凭证自愈式刷新的逻辑。
    *   修正小众活动合并为智能旁路闸门（Gated Bypass），并补充时空纠偏升级与级联融合机制。
    *   修正物化视图重建逻辑（去除了 "offline 聚类" 表述，变更为按 `normalized_event_id` 分组及冷热滑动分区重建），并补充 `MD5` 确定性 ID 算法。
    *   在 CLI 部分更新 `export --view`、`sync-bili` 的 DOM 降级细节及 `Candidates` 核验流程的文字介绍。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- 无

## Impact

*   **影响文件**：
    *   `README.md`
    *   `AGENTS.md`
*   **受影响系统**：仅限项目级开发者指南与系统设计说明文档，对应用层 Python 源代码、数据库结构及单元测试行为无物理和运行期影响。
