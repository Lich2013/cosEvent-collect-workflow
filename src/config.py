import os
# 优化 gRPC 与 Playwright 等多进程/Fork 场景下的兼容性，避免 ares_resolver 触发 check failed 导致崩溃 (GRPC Fork-safe)
os.environ["GRPC_DNS_RESOLVER"] = "native"
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "true"

import re
from pathlib import Path
import yaml
from dotenv import load_dotenv

# 确保加载环境变量
load_dotenv()

class Settings:
    def __init__(self):
        # 项目根目录绝对寻址
        self.PROJECT_ROOT = Path(__file__).resolve().parent.parent
        
        # 默认值
        self.db_path = str(self.PROJECT_ROOT / "runtime" / "cosevent.db")
        self.default_limit = 10
        self.page_load_timeout_seconds = 15
        self.analyze_confidence_threshold = 0.3
        self.langfuse_host = "http://localhost:3000"
        
        # Bilibili gRPC 凭证默认值
        self.bilibili_grpc_access_token = ""
        self.bilibili_grpc_refresh_token = ""
        self.bilibili_grpc_mid = 0
        self.bilibili_grpc_mobi_app = "android_hd"
        self.bilibili_grpc_device = "pad"
        self.bilibili_grpc_build = 1410100
        self.bilibili_grpc_ticket = ""
        self.bilibili_grpc_ticket_expires_at = 0
        
        # 动态自适应地级市列表
        self.custom_cities = []
        
        # 极简泛称黑名单默认值
        self.bypass_generic_names = ["签售", "一日店长", "店长", "摄影会", "受邀模特", "快闪", "签售会"]
        
        # 默认强弱特征词配置
        self.coser_keywords = {
            "strong": ["cosplay", "coser", "排班", "嘉宾", "发片"],
            "weak": [
                "cos", "二次元", "工作", "合作", "店长", "签售", "模特", 
                "写真", "博主", "次元", "主页", "摄影", "后期", "妆造", "画师"
            ]
        }
        
        # 默认多供应商及流水线配置
        self.llm_providers = {
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "${OPENAI_API_KEY}",
                "default_model": "gpt-4o-mini"
            }
        }
        self.analysis_pipeline = {
            "mode": "single",
            "triage_provider": "openai",
            "triage_model": "gpt-4o-mini",
            "extractors": [{"provider": "openai", "model": "gpt-4o-mini"}],
            "judge": {"provider": "openai", "model": "gpt-4o"}
        }

        # 尝试读取 config/settings.yaml 覆盖默认值
        config_path = self.PROJECT_ROOT / "config" / "settings.yaml"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data:
                        db_rel = data.get("db_path", "runtime/cosevent.db")
                        self.db_path = str(self.PROJECT_ROOT / db_rel)
                        self.default_limit = int(data.get("default_limit", self.default_limit))
                        self.page_load_timeout_seconds = int(data.get("page_load_timeout_seconds", self.page_load_timeout_seconds))
                        self.analyze_confidence_threshold = float(data.get("analyze_confidence_threshold", self.analyze_confidence_threshold))
                        self.langfuse_host = data.get("langfuse_host", self.langfuse_host)
                        self.llm_providers = data.get("llm_providers", self.llm_providers)
                        self.analysis_pipeline = data.get("analysis_pipeline", self.analysis_pipeline)
                        
                        self.custom_cities = data.get("custom_cities", [])
                        self.bypass_generic_names = data.get("bypass_generic_names", self.bypass_generic_names)
                        self.coser_keywords = data.get("coser_keywords", self.coser_keywords)
                        
                        bili_grpc = data.get("bilibili_grpc", {}) or {}
                        self.bilibili_grpc_access_token = bili_grpc.get("access_token", "")
                        self.bilibili_grpc_refresh_token = bili_grpc.get("refresh_token", "")
                        self.bilibili_grpc_mid = bili_grpc.get("mid", 0)
                        self.bilibili_grpc_mobi_app = bili_grpc.get("mobi_app", "android_hd")
                        self.bilibili_grpc_device = bili_grpc.get("device", "pad")
                        self.bilibili_grpc_build = bili_grpc.get("build", 1410100)
                        self.bilibili_grpc_ticket = bili_grpc.get("ticket", "")
                        self.bilibili_grpc_ticket_expires_at = bili_grpc.get("ticket_expires_at", 0)
            except Exception as e:
                print(f"\x1b[1;31m[Warning] 读取配置文件 settings.yaml 失败，使用系统默认配置: {e}\x1b[0m")

        # 解析环境变量插值与从环境直接读取兜底
        self.bilibili_grpc_access_token = self._resolve_env_var(self.bilibili_grpc_access_token)
        self.bilibili_grpc_refresh_token = self._resolve_env_var(self.bilibili_grpc_refresh_token)
        self.bilibili_grpc_mid = self._resolve_env_var(self.bilibili_grpc_mid)
        self.bilibili_grpc_mobi_app = self._resolve_env_var(self.bilibili_grpc_mobi_app)
        self.bilibili_grpc_device = self._resolve_env_var(self.bilibili_grpc_device)
        self.bilibili_grpc_build = self._resolve_env_var(self.bilibili_grpc_build)
        self.bilibili_grpc_ticket = self._resolve_env_var(self.bilibili_grpc_ticket)
        self.bilibili_grpc_ticket_expires_at = self._resolve_env_var(self.bilibili_grpc_ticket_expires_at)

        if not self.bilibili_grpc_access_token:
            self.bilibili_grpc_access_token = os.environ.get("BILIBILI_ACCESS_TOKEN", "")
        if not self.bilibili_grpc_refresh_token:
            self.bilibili_grpc_refresh_token = os.environ.get("BILIBILI_REFRESH_TOKEN", "")
        if not self.bilibili_grpc_ticket:
            self.bilibili_grpc_ticket = os.environ.get("BILIBILI_TICKET", "")
        
        # 处理 ticket_expires_at 过期时间解析
        expires_val = self.bilibili_grpc_ticket_expires_at
        if not expires_val:
            expires_val = os.environ.get("BILIBILI_TICKET_EXPIRES_AT", "0")
        try:
            self.bilibili_grpc_ticket_expires_at = int(expires_val)
        except (ValueError, TypeError):
            self.bilibili_grpc_ticket_expires_at = 0
        if not self.bilibili_grpc_mid:
            mid_env = os.environ.get("BILIBILI_MID", "0")
            if str(mid_env).isdigit():
                self.bilibili_grpc_mid = int(mid_env)
            else:
                self.bilibili_grpc_mid = 0
        else:
            try:
                self.bilibili_grpc_mid = int(self.bilibili_grpc_mid)
            except (ValueError, TypeError):
                self.bilibili_grpc_mid = 0

        if not self.bilibili_grpc_mobi_app:
            self.bilibili_grpc_mobi_app = os.environ.get("BILIBILI_MOBI_APP", "android_hd")
        if not self.bilibili_grpc_device:
            self.bilibili_grpc_device = os.environ.get("BILIBILI_DEVICE", "pad")
        if not self.bilibili_grpc_build:
            build_env = os.environ.get("BILIBILI_BUILD", "1410100")
            try:
                self.bilibili_grpc_build = int(build_env)
            except (ValueError, TypeError):
                self.bilibili_grpc_build = 1410100
        else:
            try:
                self.bilibili_grpc_build = int(self.bilibili_grpc_build)
            except (ValueError, TypeError):
                self.bilibili_grpc_build = 1410100

        # 确保 runtime 文件夹及日志目录存在
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        logs_dir = self.PROJECT_ROOT / "runtime" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_env_var(self, val) -> str:
        """解析类似 ${VAR_NAME} 的环境变量字符串"""
        if not val or not isinstance(val, str):
            return val
        match = re.match(r"^\$\{(.*)\}$", val)
        if match:
            env_name = match.group(1)
            return os.environ.get(env_name, "")
        return val

# 单例配置
settings = Settings()

