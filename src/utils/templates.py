from jinja2 import Template
from src.config import settings
from src.utils.time import beijing_today_str

def render_instruction_template(template_name: str, **kwargs) -> str:
    """
    统一读取并使用 Jinja2 模板渲染 System Prompt，自动注入北京参考时间 (current_date)。
    支持通过 kwargs 传入额外的渲染上下文变量。
    """
    template_path = settings.PROJECT_ROOT / "config" / "templates" / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Jinja2 模板不存在: {template_path}")
        
    with open(template_path, "r", encoding="utf-8") as f:
        template_str = f.read()
        
    template = Template(template_str)
    
    context = {"current_date": beijing_today_str(), **kwargs}
    return template.render(**context)
