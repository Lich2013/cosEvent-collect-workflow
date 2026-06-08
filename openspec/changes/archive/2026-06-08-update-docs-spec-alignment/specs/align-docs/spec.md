## ADDED Requirements

### Requirement: 核心指南与智能体规范文档对齐
系统的主项目文档 `README.md` 与智能体开发规范 `AGENTS.md` 必须在逻辑与文本层面上，与 `openspec/specs/` 目录下既存的全量功能规格说明书（Specifications）保持绝对对齐。

#### Scenario: 开发者成功在文档中查阅到最新的系统行为定义
- **WHEN** 开发者查阅 `README.md` 或 `AGENTS.md`
- **THEN** 文档中展现的内容（包括三态状态机状态隔离、gRPC 自动刷新与 Ticket 缓存自愈、个人简介虚拟推文合成、智能旁路闸门逻辑、滑动冷热物化重建分区、确定性哈希主键及候选人自动分类和冷却流转机制）与实际系统行为及 spec.md 描述无任何冲突或滞后
