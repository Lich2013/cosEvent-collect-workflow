def validate_status(status_val: str):
    """验证活动状态是否在硬枚举值域内"""
    assert status_val in ('未开始', '已结束', '已取消'), f"Status '{status_val}' is invalid!"

def validate_type(type_val: str):
    """验证活动分类是否在硬枚举值域内"""
    assert type_val in ('漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售'), f"Event Type '{type_val}' is invalid!"
