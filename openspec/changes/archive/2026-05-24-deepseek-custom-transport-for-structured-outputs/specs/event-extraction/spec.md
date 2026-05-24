## MODIFIED Requirements

### Requirement: 多大模型供应商与端点动态注册
系统必须在 `config/settings.yaml` 中支持 `llm_providers` 配置块。配置块中允许注册多个独立的 LLM 供应商（如 `openai`、`deepseek`、`local_ollama` 等），且每个供应商必须包含：
- `base_url` (str): 该提供商的 OpenAI 兼容 API 端点
- `api_key` (str): 该提供商的 API 密钥（需支持类似 `${ENV_VAR}` 的环境变量占位符解析）
- `default_model` (str): 该提供商的默认模型名称

系统在初始化阶段必须加载这些供应商，并利用 `openai.AsyncOpenAI` 实例化为不同的客户端连接。系统必须实现自定义的 `ModelProvider`，使得 Agent 在执行 `Runner.run` 时，可以通过 `RunConfig(model_provider=...)` 动态分发路由到正确的端点、凭证和模型名。

同时，针对 **DeepSeek** 供应商，系统**必须且 SHALL** 在初始化客户端连接时集成自定义的 HTTP 拦截传输层（`DeepSeekTransport`），以拦截和拦截其发送的所有请求。如果请求头中为 application/json 且请求体含有 `"response_format": {"type": "json_schema"}`，拦截层**必须且 SHALL**：
1. 提取出 `json_schema` 定义并序列化为 JSON 字符串；
2. 找到请求消息列表中最后一条 `system`（或 `user`）角色的消息，将其 `content` 动态拼接追加结构化 Schema 约束提示词；
3. 将请求体中的 `response_format` 强制降级重写为 `"response_format": {"type": "json_object"}` (即 JSON Mode)；
4. 重新计算并注入正确的 `Content-Length` 并发往 DeepSeek 官方 API，确保 Pydantic 强契约输出能够完美适配 DeepSeek 并防范 400 崩溃。

#### Scenario: 动态分发路由到指定的大模型端点
- **WHEN** 智能体在 `settings.yaml` 中配置了 DeepSeek 端点并使用模型名 "deepseek/deepseek-chat" 执行提取时
- **THEN** 智能体框架使用配置 of DeepSeek 密钥和 Base URL 发送异步 HTTP 请求，成功获取结果

#### Scenario: DeepSeek 供应商客户端初始化并成功挂载自定义拦截器重写请求
- **WHEN** 智能体框架懒加载实例化 `provider = "deepseek"` 的大模型客户端，且最终智能体发起声明了 `output_type`（要求 json_schema）的结构化提取请求时
- **THEN** 底层通信由自定义的 `DeepSeekTransport` 拦截拦截，成功将请求参数中的 `json_schema` 格式降级转换为 `json_object` 并将 Schema 追加序列化附加到 system 消息尾部，DeepSeek 接口返回合法 JSON 响应
