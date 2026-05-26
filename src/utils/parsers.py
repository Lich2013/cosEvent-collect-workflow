import re

def parse_city(place_str: str) -> str:
    """
    智能城市解析器：
    从具体的漫展地点字符串中，使用正则模式识别并提取城市名称（如：'上海世博展览馆' -> '上海'）。
    如果无法识别，默认兜底返回 '未知'。
    """
    if not place_str:
        return "未知"
    m = re.search(r"([\u4e00-\u9fa5]{2,3}?(?:市|州|盟|地区|区))", place_str)
    if m:
        return m.group(1)
    m_simple = re.match(r"^([\u4e00-\u9fa5]{2,4})", place_str)
    if m_simple:
        return m_simple.group(1)
    return "未知"
