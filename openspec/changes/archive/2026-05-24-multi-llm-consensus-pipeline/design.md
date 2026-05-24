## Context

当前系统的 Cosplay 活动提取引擎由单一大语言模型（隐式依靠全局环境变量 `OPENAI_API_KEY`）驱动，代码中没有指定具体模型名称和 API 端点。这种设计存在两个主要痛点：
1. **难以灵活切换供应商**：不支持国内优秀的低成本模型（如 DeepSeek）或本地自托管模型（如 Ollama）。
2. **单点幻觉与歧义风险**：博文中往往包含极高噪的口语化表达（如“芙芙 CP30 摊位 D31 面基”、“下周六去国展”），单一模型容易误判时间、把角色混淆为漫展、或者在缺少具体场馆时凭空捏造（幻觉）。

本设计将引入**多模型并行提取与终审裁决（Consensus Pipeline）**。核心机制是通过配置化系统，在运行时动态路由多个 OpenAI 兼容客户端，并行拉取低成本提取模型（如 DeepSeek + GPT-4o-mini）的活动草稿，并由独立的高智商裁判模型进行去重、合并与强类型 Pydantic 规整输出。

---

## Goals / Non-Goals

**Goals:**
1. **灵活的配置化多 LLM 路由**：支持在 `settings.yaml` 中注册多个大模型供应商端点和密钥，并在智能体运行时动态分发路由。
2. **Triage 预检分流过滤与强契约保障**：设计基于 Pydantic 的首轮分流机制，以极低成本识别并快速过滤不含活动的日常博文，并利用 SDK 自动纠错能力确保高可靠响应，节省 80% 以上的 API 账单费用。
3. **高精度共识仲裁与模糊合并**：利用裁判智能体（Judge Agent）对比、比对、合并多方候选活动，取要素最具体、描述最精确的记录，最终通过 `FinalOutput` 校验。
4. **强健的单侧 API 降级与裁判旁路 (Judge Bypass)**：实现并行提取中的容错，任何一侧 API 异常时，系统自动降级且智能跳过裁判仲裁（直接返回结果以节省 Token），确保高可用性。
5. **遵循 DRY 原则的日志结构重构**：将零散的 `log_event` 函数统一抽取为公共模块。

**Non-Goals:**
1. **支持非 OpenAI 兼容的特有 API 协议**：本次设计仅支持标准的 OpenAI 兼容 API。
2. **长对话记忆与会话历史保留**：共识分析为无状态的单轮增量提取，无需在 Agent 运行周期之间保留多轮交互上下文。

---

## Decisions

### 决策 1: 声明式多模型及流水线 YAML 配置结构
- **决策内容**：在 `config/settings.yaml` 中增加层级式的提供商定义 `llm_providers` 及流水线控制 `analysis_pipeline`。
- **Rationale (合理性)**：将模型选择、端点与 Key 从代码和全局环境变量中抽离，提升系统的部署适应性，支持随时添加新的国内镜像源或本地模型。

### 决策 2: 缓存型动态 ModelProvider 适配器 (`RegistryModelProvider`)
- **决策内容**：封装 `LLMClientRegistry` 管理不同供应商的 `AsyncOpenAI` 连接实例。通过继承官方原生 SDK 的 `ModelProvider` 类，实现 `RegistryModelProvider`，其重写 `get_model(model_spec)`，从而使不同的 Agent 实例在同一个提取任务中动态路由到不同的供应商端点与 Key。

### 决策 3: "Triage-First" Pydantic 强类型预检机制
- **决策内容**：定义轻量级 `TriageOutput` 契约结构，显式包含 `has_event` (bool) 和 `candidate_events` (list[str])。Triage 智能体声明 `output_type=TriageOutput`，直接享受 SDK 的 3 次格式纠错和自动重试，规避任何脆弱的纯文本正则/模糊匹配。首轮预检若确认无活动计划，外部事务控制流原子的将博文标记为 `is_analyzed = 1` 并终止后续调用。
- **Rationale (合理性)**：在真实的爬虫数据中，包含漫展活动的信息不到 10%。Triage-First 能用最低的价格和最快的速度对海量日常微博进行快速初筛，并且用 Pydantic 规整结果，极大提升了边界情况下的稳定性。

### 决策 4: 终审裁判模糊活动要素合并 (Fuzzy Merging Prompt)
- **决策内容**：编写独立的 `config/templates/event_consensus_judge.jinja2` 裁判专有模板。在其中提供 Few-Shot 样本，教导裁判大模型如何做“时间/场馆重叠检测”，并把分散提取的描述进行字段合并，选择字数最全、内容最具体的要素。

### 决策 5: 单侧降级之裁判旁路优化 (Judge Bypass)
- **决策内容**：当提取器 A 因超时/限流异常崩溃但提取器 B 提取成功时，系统自动旁路（Bypass）裁判大模型，跳过仲裁，直接将存活提取器的活动列表作为最终输出。
- **Rationale (合理性)**：由于仅有一侧成功，不存在不同供应商的数据对比，调用裁判只能是“纯文本直传格式化”，造成了双重 Token 消耗。直接返回提取结果是极佳的性能与成本折中方案。

### 决策 6: 日志功能重构 (Centralized Logger Module)
- **决策内容**：废除各个模块中重复复制的 `log_event` 和 `setup_local_logging` 函数，将其全量整合至核心通用模块 `src/utils/logger.py` 中，供 CLI 入口、数据库服务、爬虫基类和 Agent 统一导入引用。

---

## Risks / Trade-offs

### 1. [Risk] 国内 API 端点（如 DeepSeek）在高并发时易发生 503 超频限流或请求超时
- **Mitigation (缓解措施)**：
  - 并行执行时采用 `return_exceptions=True` 收集协程结果。
  - 实现单侧 API 抖动的黄色警告并**优雅降级**。如果一侧报错但另一侧成功，触发“裁判旁路模式”；如果全崩，才触发 3 次自动重试，3 次后若彻底失败则优雅回滚本条博文。

### 2. [Risk] 并行 LLM 调用带来的总体时延 (Latency) 变长
- **Mitigation (缓解措施)**：
  - 使用 `asyncio.gather` 并行执行提取，使网络请求时间重叠。
  - 由于快速预检分流（Triage）过滤掉了 90% 的博文，整个 CLI 分析任务的**总体运行耗时**非但不会增加，反而会因为规避了大量无效博文的复杂提取和审判，大幅缩短总运行时间。

### 3. [Risk] settings.yaml 包含明文 API Key 的泄漏风险
- **Mitigation (缓解措施)**：
  - 在 `README.md` 中增加加粗显式警示，引导用户优先使用 `${ENV_VAR}` 占位符进行外部环境变量插值，而非直接在 yaml 中填写明文密码。
