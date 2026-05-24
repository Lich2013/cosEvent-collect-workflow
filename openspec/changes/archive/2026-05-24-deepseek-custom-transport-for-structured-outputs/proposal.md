## Why

当前系统在共识分析模式（Consensus Mode）下支持配置多种大模型供应商，其中包括 DeepSeek（如 `deepseek-v4-flash` 和 `deepseek-v4-pro`）。然而，当 `openai-agents` (官方原生 SDK) 声明了 `output_type`（Pydantic 强契约强类型）时，SDK 会在底层发起 chat.completions 请求时携带 `"response_format": {"type": "json_schema"}`。

由于 DeepSeek 官方 API 目前并不原生支持 `"type": "json_schema"` 这一 response_format（仅支持普通的 `"type": "json_object"` 即 JSON Mode），导致所有使用 DeepSeek 进行预检分流（Triage）或活动并行提取（Extraction）的请求均会触发 `Error code: 400 - {'error': {'message': 'This response_format type is unavailable now'}}` 接口报错，彻底干碎了多模型混合流水线。

为了在不侵入业务层代码、不改动官方 SDK 核心逻辑的前提下，完美适配并点亮 DeepSeek 系列模型的结构化提取能力，我们必须在底层连接池注册表（LLMClientRegistry）中，为 DeepSeek 专用 AsyncOpenAI 客户端注入自定义 HTTP 拦截传输层（DeepSeekTransport），实现透明重写与平滑降级。

## What Changes

- **新增 `DeepSeekTransport` 拦截层**：实现继承自 `httpx.AsyncBaseTransport` 的自定义传输层，拦截并重写发送给 DeepSeek 接口的 POST 请求。
- **降级 json_schema 格式**：如果检测到请求体中携带 `"type": "json_schema"`，透明将其降级为 DeepSeek 官方支持的 `"type": "json_object"` (JSON Mode)。
- **动态注入提示词（Prompt Injection）**：在重写请求体时，将 json_schema 格式定义的约束以及 Pydantic 去外层包裹的指令，自动、动态拼接至请求消息列表的 `system`（或 `user`）提示词尾部，以约束模型的生成。
- **升级 `LLMClientRegistry` 懒加载客户端实例化**：在创建 `provider == "deepseek"` 的 `AsyncOpenAI` 客户端时，挂载 `DeepSeekTransport` 并配置合理的超时参数。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `event-extraction`: 升级大模型供应商注册与通信契约。在底层接入自定义 `DeepSeekTransport` 拦截重写机制，透明将 `json_schema` 强契约降级为 `json_object` 并注入提示词约束，解决 DeepSeek API 不支持 `json_schema` response_format 导致的 400 崩溃问题。

## Impact

- `src/tools/llm_bridge.py`: 核心修改文件。需要定义 `DeepSeekTransport` 并集成至 `LLMClientRegistry.get_client` 的懒加载实例化逻辑中。
- `config/settings.yaml`: 生产环境配置。可安全激活 `deepseek-v4-flash` 或 `deepseek-v4-pro` 作为快速分流预检（Triage）或并行提取（Extractors）模型。
- `tests/test_cosevent.py`: 需增加单元测试，验证自定义传输层对 `json_schema` 请求的改写逻辑、提示词追加逻辑以及降级功能是否如预期工作。
