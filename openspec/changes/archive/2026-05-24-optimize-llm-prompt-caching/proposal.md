## Why

由于系统在进行博文分析和终审仲裁时，大模型的 System Prompt 与 User Prompt 没有进行严格的“静动分离”（Static-Dynamic Segregation），导致大模型服务商（特别是 DeepSeek 与 OpenAI）的 Prompt Caching 自动前缀缓存机制无法达到最高命中率。
在 User Prompt 的头部夹杂静态前缀，或在尾部添加静态后缀，都会导致缓存的前缀匹配在进入 User Prompt 时立即失效或产生不必要的 Token 消耗。通过实施彻底的静动分离重构，可以显著提升 Prompt 缓存命中率，从而大幅缩短模型响应延时（Latency）并降低 API 调用费用（Cost）。

## What Changes

- **重构 Extractor 提示词的静动边界**：将原本位于 Extractor 智能体 `User` 消息头部的静态引导文案（例如 *"请提取这篇博文中的未来 Cosplay 活动计划..."*）彻底从代码组装逻辑中移除，合并归入 `event_analysis.jinja2` 静态系统模板中。
- **重构 Judge 提示词的静动边界**：将原本位于 Judge 智能体 `User` 消息尾部的静态裁决指令（例如 *"请绝对依据终审与模糊合并去重准则..."*）彻底从代码组装逻辑中移除，合并归入 `event_consensus_judge.jinja2` 静态系统模板中。
- **净化 User Prompt 输入**：使所有的 `User` 消息均转为**纯净的动态变量体**（仅包含博文正文、原帖链接、发布日期以及模型候选结果 JSON），确保缓存边界在 `System` 消息末尾（包含 JSON Schema）精准对齐，从而达到 100% 的静态 System + Schema 缓存重用率。
- **更新测试用例断言**：修改 `tests/test_cosevent.py` 中对应的单元测试，使其完美对齐优化后的提示词格式与拼接规范。

## Capabilities

### New Capabilities
<!-- 无新增 Capability -->

### Modified Capabilities
- `event-extraction`: 优化智能体与裁判提示词（Prompts）的组装机制，严格贯彻“静动分离”原则以大幅提升大模型在提取和裁决阶段的 Prompt Caching 缓存命中率。

## Impact

- **受影响代码**：`src/agents/event_agent.py` (智能体组装与拼装逻辑)
- **受影响模板**：`config/templates/event_analysis.jinja2` 与 `config/templates/event_consensus_judge.jinja2`
- **受影响测试**：`tests/test_cosevent.py` (相关 User Prompt 生成的单元测试断言)
