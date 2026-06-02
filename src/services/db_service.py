import datetime
from src.services.db.coser_repository import CoserRepository
from src.services.db.event_repository import EventRepository
from src.services.db.query_service import QueryService

class DBService:
    """
    数据存储门面类 (Facade Pattern)：
    完全对齐系统既往的公共 API 契约，保证外部调用者（包含单元测试）在零修改的前提下稳定工作。
    具体底层存取职责被物理拆解分流至职责单一的子仓储和查询服务中。
    """

    # ==============================================================================
    # 1. Coser 基础实体 CRUD 委托
    # ==============================================================================
    @staticmethod
    def add_coser(name: str, weibo_uid: str = None, bilibili_uid: str = None, xhs_uid: str = None) -> bool:
        return CoserRepository.add_coser(name, weibo_uid, bilibili_uid, xhs_uid)

    @staticmethod
    def list_cosers(only_active: bool = False) -> list[dict]:
        return CoserRepository.list_cosers(only_active)

    @staticmethod
    def get_active_cosers_without_bilibili() -> list[dict]:
        return CoserRepository.get_active_cosers_without_bilibili()

    @staticmethod
    def update_coser(name: str, weibo_uid: str = None, bilibili_uid: str = None, xhs_uid: str = None, is_active: int = None) -> bool:
        return CoserRepository.update_coser(name, weibo_uid, bilibili_uid, xhs_uid, is_active)

    @staticmethod
    def delete_coser(name: str) -> bool:
        return CoserRepository.delete_coser(name)

    # ==============================================================================
    # 2. 原始博文保存与冲突版本控制委托 (归于 CoserRepository)
    # ==============================================================================
    @staticmethod
    def save_raw_posts(coser_id: int, platform: str, posts: list[dict]) -> int:
        return CoserRepository.save_raw_posts(coser_id, platform, posts)

    @staticmethod
    def get_unanalyzed_posts() -> list[dict]:
        return CoserRepository.get_unanalyzed_posts()

    # ==============================================================================
    # 3. 提炼活动原子事务合并入库委托
    # ==============================================================================
    @staticmethod
    def save_extracted_events_transactional(raw_post_id: int, events: list[dict], confidence_threshold: float) -> bool:
        return EventRepository.save_extracted_events_transactional(raw_post_id, events, confidence_threshold)

    @staticmethod
    def mark_post_analysis_failed(raw_post_id: int) -> bool:
        return EventRepository.mark_post_analysis_failed(raw_post_id)

    # ==============================================================================
    # 4. 只读聚合看板及时间轴日历查询委托 (读写分离 CQRS)
    # ==============================================================================
    @staticmethod
    def get_all_events(confidence_threshold: float = 0.0, scope: str = "all", event_type: str = None, city: str = None) -> list[dict]:
        return QueryService.get_all_events(confidence_threshold, scope, event_type, city)

    @staticmethod
    def get_event_centric_summary(confidence_threshold: float = 0.0, event_type: str = None, city: str = None) -> list[dict]:
        return QueryService.get_event_centric_summary(confidence_threshold, event_type, city)

    @staticmethod
    def get_normalized_events(city: str = None, scope: str = "future", event_type: str = "漫展") -> list[dict]:
        return QueryService.get_normalized_events(city, scope, event_type)
