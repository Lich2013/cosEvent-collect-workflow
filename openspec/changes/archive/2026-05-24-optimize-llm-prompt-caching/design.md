## Context

当前系统在运行增量 Cosplay 活动提取时，Extractor 和 Judge 智能体的 `User` 消息（User Prompt）中夹杂了静态文案。
根据大模型服务商（特别是 DeepSeek）的 Prompt Caching 自动前缀缓存原理，任何缓存在前缀匹配中断后均无法延续。
当前的设计在 `User` 消息头部夹杂静态动作描述（Extractor），或在 `User` 消息尾部添加合并原则（Judge），导致缓存前缀在进入 `User` 消息时直接中断，无法充分利用缓存块。因此，必须对提示词的静动边界进行重构，实行“静动彻底隔离”设计。

## Goals / Non-Goals

**Goals:**
- 将 Extractor 智能体 `User` 消息中的静态前缀说明物理剥离，合并移植到 `event_analysis.jinja2` 系统提示词模板中。
- 将 Judge 智能体 `User` 消息中的静态裁决尾缀物理剥离，合并移植到 `event_consensus_judge.jinja2` 系统提示词模板中。
- 实现 `User` 消息的“纯净化”，使其仅承载纯动态数据（博文内容、链接、时间、候选 JSON），完全消除静态与动态文本交织的问题。
- 调整单元测试 `tests/test_cosevent.py` 中的提示词拼接断言，确保优化后的重构不会破坏测试套件的运行。

**Non-Goals:**
- 不修改底层的 HTTP 自定义拦截传输层 `DeepSeekTransport` 的重写逻辑（它依然负责在请求被发出前动态注入 Schema 约束）。
- 不改变 Agent 之间的接口输入与输出强契约结构（`TriageOutput` 和 `FinalOutput` 保持不变）。
- 不涉及大模型供应商底层的切换逻辑。

## Decisions

### 决定 1：将动作与规则指令从 User Prompt 上移至 System Prompt 模板
- **决策内容**：将所有的提取诉求和裁决命令，统一整合到各自的 `Jinja2` 静态系统提示词模板中。
- **原由与收益**：
  - **最大化缓存**：由于 System Prompt 在 Chat 接口的 `messages` 数组中是排在首位（Token 0 开始）的消息，且在同一天内完全静态，大模型服务商能够对其进行完整的 KV 缓存块处理。
  - **极简 User 消息**：User 消息只用传递动态信息，结构极度清晰。
- **替代方案评估**：*保持在 User 消息中但移至最前面*。但这仍然无法在 User 消息内部建立起 1024 Token 的独立对齐缓存块，因为随后的博文正文完全动态，会直接打断缓存分块，因此该方案被否决。

### 决定 2：规范化静态模板的结构划分
- **决策内容**：在 `event_analysis.jinja2` 和 `event_consensus_judge.jinja2` 模板中，使用清晰的 Markdown 二级标题（如 `## 🔍 核心提取诉求与任务` 或 `## ⚖️ 终审仲裁与模糊合并准则`）来包裹合并进来的静态指令。
- **原由与收益**：确保将原本分散在代码中的引导词迁入模板后，大模型依然能够准确识别并高强度遵循相应的角色设定与提取准则，不降低解析精度。

## Risks / Trade-offs

- **[风险 1] 提示词结构重构导致大模型的指令遵循度下降**  
  * **缓解措施**：在系统提示词模板中使用清晰、带条理的 Markdown 层级进行整合，并在单元测试中进行完整覆盖验证。系统依然保留了 Pydantic 强类型输出校验和 3 次格式纠错重试机制，可自动自我纠正。
- **[风险 2] 单元测试断言与重构后的提示词不兼容导致红屏**  
  * **缓解措施**：在实施重构的同时，同步对 `tests/test_cosevent.py` 中的 `test_relative_date_parsing_with_published_at` 等涉及 `called_user_prompt` 拼接的断言进行重置与对齐更新，保证 19/19 个测试用例全部畅通。
