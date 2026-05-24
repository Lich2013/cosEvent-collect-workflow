## Context

当前项目在多模型共识裁决流水线中，通过 `src/tools/llm_bridge.py` 动态加载和初始化不同的 LLM 客户端连接。
`openai-agents` SDK 要求输出强契约结构化对象（即 `output_type=TriageOutput` 和 `output_type=FinalOutput`），在向底层 API 发起请求时会固定携带 `"response_format": {"type": "json_schema"}`。

然而，DeepSeek 官方 API 目前并不原生支持 `"type": "json_schema"` 这一参数，导致使用 DeepSeek 模型作为分流预检（Triage）或提取器（Extractors）时，接口会直接返回 400 错误。

为了使项目能够全面支持 DeepSeek 的强契约结构化提取，我们将在底层挂载自定义传输拦截层，将 `json_schema` 拦截并降级为 `json_object`（JSON Mode），实现平滑兼容。

## Goals / Non-Goals

**Goals:**
- **完美适配 DeepSeek 结构化输出**：使得 `deepseek-v4-flash` 和 `deepseek-v4-pro` 可以被用作 `triage_model` 或并行的 `extractors`，且接口调用 100% 成功。
- **无侵入设计**：不修改业务层（`src/agents/event_agent.py`）、数据契约定义（`src/models/schemas.py`）以及官方 SDK（`openai-agents`）的代码。
- **动态 Schema 注入**：自动提取 outbound 请求中的 `json_schema` 结构体，将其完美转换并追加注入到发送给 API 的 system 消息（或 user 消息）中，确保模型生成的 JSON 结构完全符合 Pydantic 模型。
- **高测试覆盖率**：通过完备的 Mock 单元测试覆盖传输层拦截重写逻辑，保障其稳定性。

**Non-Goals:**
- **不对非 DeepSeek 供应商做干预**：例如 OpenAI 客户端将不受任何干扰，继续使用其原生的 `json_schema` 强校验能力。
- **不重构或更改已有的共识分析业务逻辑**：该设计纯粹集中在底层客户端网络适配层。

## Decisions

### 核心决策一：继承 `httpx.AsyncBaseTransport` 实现 `DeepSeekTransport` 拦截重写
- **Rationale**: `openai.AsyncOpenAI` 实例化时允许传入自定义的 `http_client`（其中支持自定义 `transport`）。通过定义自定义传输层并重写 `handle_async_request` 方法，我们可以在 HTTP 请求真正发往服务器之前，对入参进行透明重写。
- **方案比对**:
  - *方案 A（在业务层动态提取并修改 payload）*: 侵入性太强，且由于 `openai-agents` 在底层自动组装 `response_format` 并发包，业务层几乎无法控制其最终输出的 JSON 结构。
  - *方案 B（通过 HTTP Transport 拦截重写，推荐）*: 干净利落，符合 AOP（面向切面编程）思想，底层网络通信层面做转换，完全解耦。

### 核心决策二：降级为 `json_object` 并在 system/user Prompt 追加 Schema 文本
- **DeepSeek 官方兼容模式**：DeepSeek 官方原生支持 `json_object` 格式。当启用该格式时，必须且 SHALL 在 system/user 提示词中明确指示输出为合规的 JSON 对象，且给出完整的 JSON Schema 作为参考约束。
- **注入逻辑**：
  1. 截获并解析 outgoing JSON 字符串；
  2. 若 `response_format.type == "json_schema"`，提取其 `json_schema` 并格式化为带缩进的可读文本；
  3. 将 `payload["response_format"]` 强行重置为 `{"type": "json_object"}`；
  4. 遍历 `messages` 列表，优先寻找最后一个 `role == "system"` 的消息，并在其末尾追加：
     `"\n\nJSON Schema for output:\n{schema_text}\nOutput must conform to the above JSON schema. Do NOT wrap the output in any final_output outer field."`；
     若无 system 消息，则降级追加到 `messages[-1]` 中；
  5. 重新计算请求体的 `Content-Length` 并更新。

## Risks / Trade-offs

- **[Risk] JSON 生成不规范或幻觉** → **Mitigation**: 降级为 JSON Mode 后，大模型端将没有原生的 json_schema 物理约束阻断。但由于 `DeepSeek-V4` 的指令遵循能力极强，结合重写的 Schema 说明提示词、智能体层已有的 **3 次纠错重试机制**（`analyze_post_with_retry`），Pydantic 校验异常将被优雅捕捉并自我纠正，因此解析通过率极高。
- **[Risk] `Content-Length` 错误引发服务器拒绝服务** → **Mitigation**: 重写 payload 后必须重新使用 `len(new_content)` 计算并显式改写 `request.headers["Content-Length"]`，同时更新 `request.stream = httpx.ByteStream(new_content)`。
