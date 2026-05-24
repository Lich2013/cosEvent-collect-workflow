import os
from pathlib import Path
import yaml

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
            except Exception as e:
                print(f"\x1b[1;31m[Warning] 读取配置文件 settings.yaml 失败，使用系统默认配置: {e}\x1b[0m")

        # 确保 runtime 文件夹及日志目录存在
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        logs_dir = self.PROJECT_ROOT / "runtime" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

# 单例配置
settings = Settings()
