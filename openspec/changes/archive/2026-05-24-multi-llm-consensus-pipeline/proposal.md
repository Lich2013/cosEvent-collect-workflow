## Why

当前系统的二次元与 Cosplay 活动提取模块严重依赖于全局单一的 OpenAI LLM 引擎（隐式读取 `OPENAI_API_KEY` 及默认的 GPT 模型），缺乏动态切换大模型供应商（如切换为 DeepSeek 或本地自托管大模型）的灵活性。

此外，单一模型在处理微博、小红书等高噪杂乱的社交网络动态时，极易产生语义理解歧义或时间、场馆等关键要素的幻觉。为了实现高精度的商业级活动信息提炼，有必要引入**多模型并行提取与交叉比对（Multi-LLM Consensus/Cross-Verification）**的智能体流水线。这不仅能消除单一模型的偏见，还可以通过低成本模型分流结合高智商模型审判（Triage + Consensus）的设计，在大幅提高准确率的同时极佳地控制 Token 费用。

## What Changes

本次变更主要包含以下核心功能扩展：
1. **多 LLM 供应商动态注册与配置**：在 `config/settings.yaml` 中新增 `llm_providers` 配置，支持对 OpenAI、DeepSeek 等多个平台指定独立的 `base_url`、`api_key` 和默认模型名。
2. **多模型共识分析流水线 (Consensus Pipeline)**：
   - **单/多模态无缝切换**：支持通过 `analysis_pipeline.mode` 灵活切换 `single`（单模型快速）与 `consensus`（多模型共识）运行模式。
   - **快速分流过滤 (Triage Filter)**：在共识模式下，首轮先由一个低成本模型对博文做快速预检。若未提取出任何活动候选，则立即判定无活动并跳过后续大模型调用，避免 90% 日常博文造成的 Token 浪费。
   - **多模型并行提取**：若首轮分流认为可能包含漫展，系统将启动两个不同的模型（如 OpenAI + DeepSeek）并行提取活动候选。
   - **金牌裁判智能仲裁**：将两方的提取候选提交给第三方高智能裁判模型（如 GPT-4o），裁判根据原博文纠偏、去重并做要素最优的模糊合并（Fuzzy Merging），最终输出严格符合强类型约束的 Pydantic 数据。
3. **API 故障优雅降级**：当其中一个 LLM 接口发生抖动或故障时，智能体能自动捕捉异常，优雅地降级为单模型提取或友好报错，保障主 CLI 定时进程不受单侧故障阻断。

## Capabilities

### New Capabilities
*(本次变更为现有能力的演进与升级，无全新能力引入)*

### Modified Capabilities
- `event-extraction`: 变更提取模块的行为，从单模型固定提取升级为：支持 `config/settings.yaml` 灵活的多端点配置；支持多模型共识（Consensus）与快速分流（Triage）流水线；支持高精度裁判进行模糊活动去重与合并；在多模型调用中支持单侧 API 抖动的优雅降级。

## Impact

1. **配置文件**：`config/settings.yaml` 将新增 `llm_providers` 和 `analysis_pipeline` 相关的详细配置项，并同步更新 `settings.yaml.example` 模板。
2. **核心代码**：
   - `src/config.py`：新增对多模型提供商及流水线参数的读取。
   - `src/agents/event_agent.py`：重构 `analyze_post_with_retry`，引入 `LLMClientRegistry`、`RegistryModelProvider`、快速分流、并行提取和裁判仲裁的核心流控制。
   - `config/templates/`：新增 `event_consensus_judge.jinja2` 裁判专用的 Jinja2 提示词模板。
3. **外部依赖**：需要确保 `pyproject.toml` 中的 `openai-agents` 正常支持 `ModelProvider` 机制（目前配置的版本 `>=0.6.6` 已支持）。
