## 1. 核心网络通信重写与拦截层实现

- [x] 1.1 在 `src/tools/llm_bridge.py` 中引入 `httpx` 和 `json`
- [x] 1.2 在 `src/tools/llm_bridge.py` 中定义继承自 `httpx.AsyncBaseTransport` 的 `DeepSeekTransport` 拦截重写类，实现 `handle_async_request` 拦截逻辑
- [x] 1.3 在 `DeepSeekTransport` 中编写 `_rewrite_request` 请求重构，截获并重写 application/json 且含有 json_schema 格式的 payload，降级为 json_object，并将格式化的 Schema 字符串动态追加拼接注入到 system (或最后一个 user) 提示词尾部，同时重新注入正确的 Content-Length 及 http 流
- [x] 1.4 修改 `LLMClientRegistry.get_client` 中大模型客户端懒加载初始化的逻辑，当 `provider_name == "deepseek"` 时，实例化 `AsyncOpenAI` 并传入配置了 `DeepSeekTransport` 的 `http_client` 实例

## 2. 单元测试与拦截重写行为校验

- [x] 2.1 在 `tests/test_cosevent.py` 中，编写对 `DeepSeekTransport` 的单元测试。构造包含 json_schema 格式的 mock `httpx.Request` 对象，直接调用 `_rewrite_request` 拦截重写函数并断言降级后的请求体、注入到 system 消息尾部的 Schema 文本及 Content-Length 完全符合预期
- [x] 2.2 在 `tests/test_cosevent.py` 中，编写对 `LLMClientRegistry` 的验证用例，断言 `provider == "deepseek"` 时所生成的客户端成功挂载了自定义的传输层实例
- [x] 2.3 运行本地单元回归测试，确保包含新增测试在内的 17 个用例（15 + 2）全部完美 PASS 通过
