## Context

在数据分析和自动发现候选人流程中，从微博、B站、小红书等原始博文提取提及（@用户名）时，平台字段默认被写入为 "bilibili"，而遗失了原始的 "weibo" 或 "xhs" 信息。我们需要在保存和提取时将 platform 信息贯穿到 `coser_candidates` 数据表及整个验证匹配链路中。

## Goals / Non-Goals

**Goals:**
- 在提取/注册 Coser 候选人到 `coser_candidates` 表时，保存其提及的原始平台来源（weibo/bilibili/xhs）。
- 在候选人审核及更新对齐 UID 阶段，确保其来源平台字段不被篡改或覆写为 "bilibili"。

**Non-Goals:**
- 不涉及正式 `cosers` 表字段的修改。
- 不影响现有的 B站 启发式对齐打分算法及匹配逻辑。

## Decisions

### 1. 从 raw_posts 联动查询 platform 字段
- **方案**：修改 `main.py` 的 `discover` 命令行，在 `SELECT` 语句中加入 `platform`。
- **原因**：这能确保 `posts` 博文列表中每条记录拥有其关联平台的属性，为后文注册候选人提供底层字段。

### 2. 在注册及验证过程中将 platform 贯穿
- **方案**：在 `DiscoveryService.register_candidates_from_posts` 构造提及对象列表时保留平台。在 `DiscoveryService.verify_pending_candidates` 更新候选人信息时，通过 `SELECT` 查询保留并回传原本候选人的平台字段。
- **原因**：此设计无需改动 API 接口签名，直接利用已有的 `platform` 参数写入。

## Risks / Trade-offs

- **[Risk]** 旧的 pending 候选人在表中已被记为 `"bilibili"`。
- **[Mitigation]** 对存量的 pending 候选人，若有真实的 source_ref (Weibo URL)，后续可以通过一次性 SQL 修复（提取 source_ref 特征）或保持其原状，新数据将能完美保留真实平台。
