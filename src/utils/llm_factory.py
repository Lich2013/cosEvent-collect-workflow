from src.config import settings
from src.tools.llm_bridge import LLMClientRegistry, RegistryModelProvider

# 全局唯一实例化连接池和 Provider，最大化复用连接池性能并简化组件代码
llm_registry = LLMClientRegistry(settings.llm_providers)
registry_model_provider = RegistryModelProvider(llm_registry)
