import re

# 常见省份和自治区前缀模式 (将 "吉林省?" 改为 "吉林省"，防止无省字时误剥离吉林市)
PROVINCE_PATTERN = re.compile(
    r"^(?:内蒙古自治区|新疆维吾尔自治区|西藏自治区|宁夏回族自治区|广西壮族自治区|"
    r"内蒙古|新疆|西藏|宁夏|广西|浙江省?|安徽省?|福建省?|江西省?|山东省?|河南省?|"
    r"湖北省?|湖南省?|广东省?|海南省?|四川省?|贵州省?|云南省?|陕西省?|甘肃省?|青海省?|"
    r"台湾省?|辽宁省?|吉林省|黑龙江省?|河北省?|山西省?|江苏省?)"
)

# 全国主要展览城市字典（基础静态字典）
MAJOR_CITIES = [
    # 4字城市/特例
    "呼和浩特", "乌鲁木齐", "西双版纳", "秦皇岛", "哈尔滨", "石家庄", "张家口", 
    "神农架", "张家界", "吐鲁番", "攀枝花", "六盘水", "葫芦岛", "牡丹江", 
    "佳木斯", "马鞍山", "景德镇", "平顶山", "三门峡", "防城港",
    # 2字城市 (加入吉林市)
    "上海", "北京", "广州", "深圳", "杭州", "成都", "武汉", "南京", "重庆", 
    "西安", "厦门", "福州", "天津", "沈阳", "长春", "济南", "青岛", "潍坊", 
    "合肥", "长沙", "郑州", "南昌", "南宁", "昆明", "贵阳", "海口", "兰州", 
    "西宁", "银川", "拉萨", "大连", "宁波", "苏州", "无锡", "常州", "温州", 
    "绍兴", "嘉兴", "金华", "台州", "湖州", "舟山", "丽水", "衢州", "珠海", 
    "佛山", "东莞", "中山", "汕头", "江门", "湛江", "茂名", "防城", "惠州", 
    "梅州", "汕尾", "河源", "阳江", "清远", "潮州", "揭阳", "云浮", "韶关",
    "吉林"
]

# 动态载入配置中的自定义城市列表，合并并按长度降序排列
try:
    from src.config import settings
    dynamic_cities = getattr(settings, "custom_cities", []) or []
except Exception:
    dynamic_cities = []

MAJOR_CITIES_COMBINED = sorted(list(set(dynamic_cities + MAJOR_CITIES)), key=len, reverse=True)


def parse_city(place_str: str) -> str:
    """
    智能城市解析器：
    从具体的漫展地点字符串中，使用多级清洗提取并规范城市名称。
    1. 剥离省份前缀（如“浙江省”、“内蒙古自治区”）
    2. 匹配高频展览地级市字典强匹配
    3. 后缀正则智能剥离（市/区/县/州/盟/地区）
    4. 终极两字截取兜底（防分裂）
    """
    if not place_str:
        return "未知"
        
    place_str = place_str.strip()
    if not place_str or "未知" in place_str:
        return "未知"
        
    # 1. 剥离省份/自治区前缀
    cleaned_str = PROVINCE_PATTERN.sub("", place_str).strip()
    
    # 2. 匹配主要展览城市字典
    for city in MAJOR_CITIES_COMBINED:
        if cleaned_str.startswith(city):
            return city
            
    # 3. 后缀正则匹配截取（匹配 2 到 6 个汉字后紧跟行政后缀的模式）
    m_suffix = re.match(r"^([\u4e00-\u9fa5]{2,6}?)(?:市|州|盟|地区|区|县)", cleaned_str)
    if m_suffix:
        return m_suffix.group(1)
        
    # 4. 二字降级兜底截取
    m_fallback = re.match(r"^([\u4e00-\u9fa5]{2})", cleaned_str)
    if m_fallback:
        return m_fallback.group(1)
        
    return "未知"
