from pydantic import BaseModel, Field
from typing import List, Optional

class CosEvent(BaseModel):
    """单独一个 Cosplay 活动提炼模型"""
    event_name: str = Field(
        ..., 
        description="动漫展、签售会或快闪活动的主题名称。例如: CP30 动漫展, 广州萤火虫动漫游戏嘉年华"
    )
    event_date: str = Field(
        ..., 
        description="活动的具体日期，格式必须为 YYYY-MM-DD。若无法精确推断，则填写 '未知'"
    )
    event_place: str = Field(
        ..., 
        description="活动的省份、城市及具体场馆地点。例如: 上海国家会展中心, 广州保利世贸博览馆"
    )
    event_description: Optional[str] = Field(
        None, 
        description="该 Coser 在此活动中的具体行程安排、摊位信息或扮演的角色装扮计划。例如: 第一天出芙宁娜，位置在A15摊位"
    )
    confidence: float = Field(
        ..., 
        description="大模型对提取内容的确定性置信度评分，取值范围在 0.0 至 1.0 之间"
    )
    source_url: str = Field(
        ..., 
        description="提取该活动的原始博文源链接地址"
    )

class FinalOutput(BaseModel):
    """大模型提取智能体的强契约结构化最终返回模型"""
    event_list: List[CosEvent] = Field(
        ..., 
        description="智能体所提炼出的所有有效即将发生的活动列表"
    )

class TriageOutput(BaseModel):
    """大模型快速分流预检智能体的强契约模型"""
    has_event: bool = Field(
        ...,
        description="请严格判断博文中是否包含任何未来即将参加的漫展、嘉宾排班、签售、出行计划或快闪安排。只有包含明确活动意图的才返回 True，日常自拍、碎碎念、转发抽奖、已过期的活动一律返回 False。"
    )
    candidate_events: List[str] = Field(
        default=[],
        description="博文里提到的未来活动主题候选名称列表（如果 has_event 为 False 则为空列表）"
    )
