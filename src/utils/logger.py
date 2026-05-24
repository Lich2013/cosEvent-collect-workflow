import logging
import datetime
import json
from src.config import settings

def log_event(level: str, component: str, message: str, exception: str = None):
    """全局结构化 JSON 日志记录函数，保障系统行为可观测性并降级落盘"""
    logger = logging.getLogger("cosevent")
    if logger.handlers:
        log_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "level": level,
            "component": component,
            "message": message
        }
        if exception:
            log_data["exception"] = exception
        logger.info(json.dumps(log_data, ensure_ascii=False))

def setup_local_logging():
    """全局统一的本地 JSON 结构化格式日志落盘配置"""
    log_file = settings.PROJECT_ROOT / "runtime" / "logs" / "cosevent.json.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("cosevent")
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
