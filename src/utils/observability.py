import os
import click
from src.config import settings
from src.utils.logger import setup_local_logging

LANGFUSE_ACTIVE = False

def init_observability():
    """自检并初始化本地 Langfuse 追踪器"""
    global LANGFUSE_ACTIVE
    try:
        from langfuse import Langfuse
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
        
        # 将本地配置注入环境变量
        os.environ["LANGFUSE_HOST"] = settings.langfuse_host
        
        # 执行连通性自检
        lf = Langfuse()
        if lf.auth_check():
            # 自检成功，激活 OpenAI Agents 全局追踪插桩
            OpenAIAgentsInstrumentor().instrument()
            LANGFUSE_ACTIVE = True
            click.secho("✅ [Observability] 成功连接到本地 Langfuse 服务 (http://localhost:3000)，智能体追踪已启用！", fg="green")
        else:
            click.secho("⚠️ [Observability Warning] 本地 Langfuse 服务连接失败，系统已自动降级为本地日志审计模式！", fg="yellow")
            setup_local_logging()
    except Exception as e:
        click.secho(f"⚠️ [Observability Warning] 链路追踪检测异常: {e}。系统已友好降级为本地日志审计模式！", fg="yellow")
        setup_local_logging()

def is_langfuse_active() -> bool:
    """查询当前 Langfuse 链路追踪是否开启"""
    return LANGFUSE_ACTIVE
