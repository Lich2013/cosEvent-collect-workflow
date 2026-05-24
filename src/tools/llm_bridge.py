import os
import re
import json
import httpx
from openai import AsyncOpenAI
from agents import ModelProvider, OpenAIChatCompletionsModel
from src.config import settings

class DeepSeekTransport(httpx.AsyncBaseTransport):
    """
    自定义 HTTP 拦截传输层，为 DeepSeek-OpenAI API 提供透明适配。
    """
    def __init__(self):
        self._transport = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._rewrite_request(request)
        return await self._transport.handle_async_request(request)

    def _rewrite_request(self, request: httpx.Request) -> None:
        # 为 DeepSeek 请求打上客户端标识
        request.headers["X-Deepseek-Client"] = "cliche"

        if request.method != "POST":
            return

        content = getattr(request, "_content", None)
        if not content:
            return

        if not request.headers.get("content-type", "").startswith("application/json"):
            return

        try:
            payload = json.loads(content)
            response_format = payload.get("response_format")
            if (
                isinstance(response_format, dict)
                and response_format.get("type") == "json_schema"
            ):
                schema_text = json.dumps(
                    response_format.get("json_schema", {}),
                    ensure_ascii=True,
                    indent=2,
                )
                messages = payload.get("messages")
                if isinstance(messages, list):
                    for message in reversed(messages):
                        if (
                            isinstance(message, dict)
                            and message.get("role") == "system"
                            and isinstance(message.get("content"), str)
                        ):
                            message["content"] = (
                                f"{message['content']}\n\nJSON Schema for output:\n{schema_text}\n"
                                f"Output must conform to the above JSON schema. Do NOT wrap the output in any final_output outer field."
                            )
                            break
                    else:
                        # 如果没有 system 角色消息，退而求其次拼接追加到最后一条消息
                        if messages:
                            last_msg = messages[-1]
                            if isinstance(last_msg, dict) and isinstance(last_msg.get("content"), str):
                                last_msg["content"] = (
                                    f"{last_msg['content']}\n\nJSON Schema for output:\n{schema_text}\n"
                                    f"Output must conform to the above JSON schema. Do NOT wrap the output in any final_output outer field."
                                )

                payload["response_format"] = {"type": "json_object"}
                new_content = json.dumps(payload, ensure_ascii=True).encode("utf-8")
                request._content = new_content
                request.stream = httpx.ByteStream(new_content)
                request.headers["Content-Length"] = str(len(new_content))
        except Exception as e:
            import logging
            logging.warning(f"[DeepSeekTransport] 请求改写异常，触发熔断降级回退: {e}")

    async def aclose(self):
        await self._transport.aclose()


class LLMClientRegistry:
    """LLM 客户端连接池注册表"""
    def __init__(self, configs: dict):
        self.configs = configs or {}
        self.clients = {}

    def get_client(self, provider_name: str) -> AsyncOpenAI:
        """根据提供商名称懒加载获取对应的 AsyncOpenAI 客户端连接"""
        if provider_name not in self.clients:
            cfg = self.configs.get(provider_name, {})
            base_url = cfg.get("base_url")
            raw_key = cfg.get("api_key", "")
            
            # 解析 "${DEEPSEEK_API_KEY}" 格式的环境变量插值
            api_key = self._resolve_env_var(raw_key)
            if not api_key:
                # 尝试大写回退兜底，例如: DEEPSEEK_API_KEY
                api_key = os.environ.get(f"{provider_name.upper()}_API_KEY")
            
            kwargs = {}
            if base_url:
                kwargs["base_url"] = base_url
            if api_key:
                kwargs["api_key"] = api_key
            
            # 如果是 DeepSeek 供应商（前缀匹配）或显式配置需要降级的供应商，挂载定制的 HTTP 拦截传输层以进行 json_schema 降级
            if provider_name.startswith("deepseek") or cfg.get("needs_json_schema_downgrade", False):
                kwargs["http_client"] = httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout=600, connect=5.0),
                    transport=DeepSeekTransport()
                )
            
            # 实例化 OpenAI Async 客户端
            self.clients[provider_name] = AsyncOpenAI(**kwargs)
            
        return self.clients[provider_name]

    def _resolve_env_var(self, val: str) -> str:
        """解析类似 ${VAR_NAME} 的环境变量字符串"""
        if not val or not isinstance(val, str):
            return val
        match = re.match(r"^\$\{(.*)\}$", val)
        if match:
            env_name = match.group(1)
            return os.environ.get(env_name, "")
        return val

class RegistryModelProvider(ModelProvider):
    """自定义 ModelProvider，支持根据 spec 前缀动态路由到不同的供应商端点与模型"""
    def __init__(self, registry: LLMClientRegistry, default_provider: str = "openai"):
        self.registry = registry
        self.default_provider = default_provider

    def get_model(self, model_spec: str | None) -> OpenAIChatCompletionsModel:
        """
        根据指定的模型前缀标识符获取对应的模型实例。
        - 传入 `None`: 使用默认 provider 及其配置的默认模型名
        - 传入 "gpt-4o-mini" (无前缀): 视为使用默认 provider 的该模型
        - 传入 "deepseek/deepseek-chat" (带前缀): 解析为对应的提供商及大模型
        """
        provider = self.default_provider
        model_name = model_spec

        if model_spec and "/" in model_spec:
            provider, model_name = model_spec.split("/", 1)
        elif model_spec is None:
            # 采用默认供应商的默认模型名
            cfg = self.registry.configs.get(provider, {})
            model_name = cfg.get("default_model", "gpt-4o-mini")

        # 获取底层 AsyncOpenAI 客户端
        client = self.registry.get_client(provider)
        
        # 实例化官方 Agents SDK 的 Chat Completions 包装器模型
        return OpenAIChatCompletionsModel(
            model=model_name,
            openai_client=client
        )
