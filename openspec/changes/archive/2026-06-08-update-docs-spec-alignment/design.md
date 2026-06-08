## Context

当前项目中已经实现并上线了诸多功能，如 B站 gRPC 凭证自愈刷新、三态状态机、小众活动的闸门化隔离融合、候选人的自动化提取核验以及冷热数据物化重建视图。然而，主项目文档 `README.md` 与智能体开发手册 `AGENTS.md` 对部分细节依然停留在前期旧方案的定义中（例如 `README.md` 将物化表重构写成了“运行 offline 聚类”；`AGENTS.md` 中缺失 `CosEvent` 模型的 `event_type` 字段，以及裁判/核验智能体等定义）。本项目文档需要整体升级与现有代码实现（Specification）完全对齐。

## Goals / Non-Goals

**Goals:**
*   更新 `AGENTS.md`，对齐最新的智能体 Pydantic 结构、重试隔离、事务锁以及候选人核验判定与冷却流转细节。
*   更新 `README.md`，对齐系统整体架构中的 Bio 推文合成、超时自愈、gRPC 自动刷新、智能旁路闸门、时空纠偏以及读写分离下的物化滑动冷分区与 MD5 指纹 ID；更新 CLI 帮助指南。

**Non-Goals:**
*   绝对不修改或添加任何功能性 Python 业务代码或 SQL DDL 执行流。
*   不对系统任何已通过的 unit tests 带来回归变化。

## Decisions

### 1. 更新 AGENTS.md 结构
*   **决策**：扩充并同步 Pydantic BaseModel 示例。新增 `CandidateVerifyOutput` 与 `FusionJudgeOutput`，并在 `CosEvent` 模型中显式加入 `event_type`。
*   **理由**：使后续的 Agent 开发或大模型代码编辑时，能根据 `AGENTS.md` 直接构造完好的 Schema，杜绝遗漏 `event_type` 导致大模型产生类型校验崩溃。
*   **备选**：不放入具体代码。但考虑到智能体通常需要精准契约对齐，直接给出代码块能极大地降低幻觉率。

### 2. 更新 README.md 系统整体数据流与 CLI 细节
*   **决策**：以合并的文字段落对系统流程图和对应的小节做原地替换与修正，同时补充 `export --view calendar`、`sync-bili` 的秒级 WAF 降级、`discover` 核验等关键功能的用法。
*   **理由**：目前 README 中的流程与当前行为不符（如仍然残留 "100% 旁路"、"offline 聚类" 等误导概念），需要尽快纠偏。

## Risks / Trade-offs

*   **风险：文档行数膨胀导致可读性下降**
    *   *缓解措施*：保持描述的简练与概括，用最精简的技术名词将 Specifications 中的核心要求（Requirements）提炼呈现在主 README 和开发规范中，避免冗余的代码粘贴。
