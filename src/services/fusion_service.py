import os
import re
import difflib
import asyncio
import datetime
from pydantic import ValidationError
from src.config import settings
from src.models.db_models import get_db_connection
from src.models.schemas import FusionJudgeOutput
from src.utils.logger import log_event
from agents import Agent, Runner, RunConfig
from src.utils.llm_factory import registry_model_provider


class EventFusionService:
    @staticmethod
    def run_async_in_sync(coro):
        """
        极度健壮的同步包装器：
        在同步上下文中安全执行异步协程。如果当前线程的事件循环已在运行（如 Click 异步执行期间），
        则透明地将其分流至独立工作线程并拉起独立的全新事件循环运行，物理杜绝 'running event loop' 死锁。
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if loop.is_running():
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: asyncio.run(coro))
                return future.result()
        else:
            return loop.run_until_complete(coro)

    @staticmethod
    def get_rendered_instructions(template_name: str = "event_fusion_judge.jinja2") -> str:
        """读取并使用 Jinja2 模板渲染裁判提示词"""
        from src.utils.templates import render_instruction_template
        return render_instruction_template(template_name)

    @staticmethod
    async def run_fusion_judge_agent(name_a: str, name_b: str, city: str) -> bool:
        """
        调用官方原生 openai-agents 裁判智能体进行同盟判定。
        3次自动纠错重试，出现故障时旁路熔断返回 False。
        """
        run_cfg = RunConfig(model_provider=registry_model_provider)
        
        # 默认使用配置中的裁判模型
        judge_cfg = settings.analysis_pipeline.get("judge", {})
        judge_prov = judge_cfg.get("provider", "openai")
        judge_mod = judge_cfg.get("model", "gpt-4o-mini")
        model_spec = f"{judge_prov}/{judge_mod}"
        
        instructions = EventFusionService.get_rendered_instructions()
        agent = Agent(
            name="event_fusion_judge_agent",
            instructions=instructions,
            output_type=FusionJudgeOutput,
            model=model_spec
        )
        
        input_prompt = f"城市: {city}\n事件A: {name_a}\n事件B: {name_b}\n请判断这两个名称在相同城市和档期下，物理上是否为同一个二次元活动？"
        feedback_prompt = input_prompt
        max_retries = 3
        
        for attempt in range(1, max_retries + 1):
            try:
                print(f"\x1b[1;34m[Fusion Agent] 启动同义漫展判定 (尝试 {attempt}/{max_retries}): '{name_a}' vs '{name_b}'...\x1b[0m")
                result = await Runner.run(agent, feedback_prompt, run_config=run_cfg)
                final_data = result.final_output
                if final_data and hasattr(final_data, "is_same"):
                    print(f"\x1b[1;32m[Fusion Agent Success] 判定结果: {final_data.is_same} (置信度: {final_data.confidence}, 理由: {final_data.reason})\x1b[0m")
                    return final_data.is_same
                else:
                    raise ValueError("裁判未返回结构化的 FusionJudgeOutput 实例")
            except (ValidationError, Exception) as e:
                err_msg = f"融合裁判在第 {attempt} 次判定时发生异常: {e}"
                print(f"\x1b[1;33m[Fusion Agent Warning] {err_msg}\x1b[0m")
                log_event("WARNING", "fusion_judge", err_msg, str(e))
                if attempt == max_retries:
                    print("\x1b[1;31m[Fusion Agent ERROR] 达最大重试上限，同义裁判熔断，默认返回 False (判定为不同漫展)。\x1b[0m")
                    return False
                feedback_prompt = f"{input_prompt}\n\n⚠️ 【系统反馈：你上一次提取未通过 Pydantic 强校验，报错如下。请绝对依据错误修正输出格式】\n{str(e)}"
        
        return False

    @staticmethod
    def _clean_name(name: str) -> str:
        """对漫展名称做极简清洗，以便进行初步计算相似度"""
        if not name:
            return ""
        s = name.lower().strip()
        s = re.sub(r"[\s\-\_\,\.\!\?\#\&\*\/]", "", s)
        return s

    @staticmethod
    def find_or_create_normalized_event(cursor, raw_event_name: str, city: str, event_date: str, event_type: str = "漫展") -> int:
        """
        核心时空融合引擎算法（纯同步版本，保障极客级向后兼容）：
        在同一个数据库事务环境下，为一条新日程寻找或创建一个归一化超级漫展节点，返回其 ID。
        """
        # 1. 参数规范化清洗，确保无空数据溢出
        city_cleaned = city.strip() if city else "未知"
        event_name_cleaned = raw_event_name.strip()
        if not event_name_cleaned:
            event_name_cleaned = "未知漫展"
        
        name_slug = EventFusionService._clean_name(event_name_cleaned)
        now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

        # 解析当前日程的时间
        current_dt = None
        if event_date and re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
            try:
                current_dt = datetime.datetime.strptime(event_date, "%Y-%m-%d").date()
            except Exception:
                current_dt = None

        # 1.5 针对非漫展小众日程，直接 100% 旁路时空粗筛与裁判合并，直接生成独立的超级节点
        if event_type != "漫展":
            fingerprint = f"{city_cleaned.lower()}_{name_slug}"
            base_fingerprint = fingerprint
            counter = 1
            while True:
                cursor.execute("SELECT id FROM normalized_events WHERE event_fingerprint = ?;", (fingerprint,))
                if not cursor.fetchone():
                    break
                fingerprint = f"{base_fingerprint}_{counter}"
                counter += 1
                
            cursor.execute(
                """
                INSERT INTO normalized_events (event_fingerprint, standard_name, city, start_date, end_date, event_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (fingerprint, event_name_cleaned, city_cleaned, event_date if current_dt else None, event_date if current_dt else None, event_type, now_str)
            )
            new_id = cursor.lastrowid
            print(f"\x1b[1;32m[Fusion Engine Bypass] 成功旁路融合并为小众活动类型 '{event_type}' 创建超级节点 (ID: {new_id}): '{event_name_cleaned}' (📍 {city_cleaned})\x1b[0m")
            return new_id
        
        # 2. 查询同城的所有既存归一化节点
        cursor.execute(
            """
            SELECT id, event_fingerprint, standard_name, city, start_date, end_date FROM normalized_events
            WHERE city = ? AND event_type = '漫展';
            """,
            (city_cleaned,)
        )
        existing_nodes = cursor.fetchall()
        
        # 解析当前日程的时间
        current_dt = None
        if event_date and re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
            try:
                current_dt = datetime.datetime.strptime(event_date, "%Y-%m-%d").date()
            except Exception:
                current_dt = None
            
        matched_node_id = None
        
        # 3. 逐个进行时空匹配
        for node_id, fingerprint, standard_name, node_city, start_date, end_date in existing_nodes:
            # A. 时间窗口过滤
            time_overlap = False
            if not current_dt or not start_date or not end_date:
                time_overlap = True
            else:
                try:
                    node_start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
                    node_end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
                    if (node_start - datetime.timedelta(days=3)) <= current_dt <= (node_end + datetime.timedelta(days=3)):
                        time_overlap = True
                except Exception:
                    time_overlap = True
                    
            if not time_overlap:
                continue
                
            # B. 相似度比对
            cleaned_node_name = EventFusionService._clean_name(standard_name)
            ratio = difflib.SequenceMatcher(None, name_slug, cleaned_node_name).ratio()
            
            # 分支 1：R >= 0.75 认为同一漫展，直接归一化
            if ratio >= 0.75:
                print(f"\x1b[1;32m[Fusion Engine] 相似度匹配成功 (得分 {ratio:.2f}): '{event_name_cleaned}' ──▶ '{standard_name}' (ID: {node_id})\x1b[0m")
                matched_node_id = node_id
                break
                
            # 分支 2：0.5 <= R < 0.75 进入存疑区
            elif 0.5 <= ratio < 0.75:
                # 检查别名缓存表 (统一使用清洗后的纯净别名 Slug)
                cleaned_alias = EventFusionService._clean_name(event_name_cleaned)
                cursor.execute(
                    """
                    SELECT normalized_event_id FROM event_aliases
                    WHERE alias_name = ? AND city = ?;
                    """,
                    (cleaned_alias, city_cleaned)
                )
                alias_row = cursor.fetchone()
                if alias_row:
                    print(f"\x1b[1;32m[Fusion Engine] 命中古典别名缓存: '{event_name_cleaned}' ──▶ Standard ID: {alias_row[0]}\x1b[0m")
                    matched_node_id = alias_row[0]
                    break
                    
                # 别名未命中，自适应同步调用 LLM 裁判确权
                is_same = EventFusionService.run_async_in_sync(
                    EventFusionService.run_fusion_judge_agent(event_name_cleaned, standard_name, city_cleaned)
                )
                if is_same:
                    # 确认是同一个，写入别名缓存表 (同样统一使用清洗后的别名)
                    now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        """
                        INSERT INTO event_aliases (alias_name, city, normalized_event_id, created_at)
                        VALUES (?, ?, ?, ?);
                        """,
                        (cleaned_alias, city_cleaned, node_id, now_str)
                    )
                    print(f"\x1b[1;32m[Fusion Engine] 裁判认定一致并追加缓存: '{event_name_cleaned}' ──▶ '{standard_name}' (ID: {node_id})\x1b[0m")
                    matched_node_id = node_id
                    break

        now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        
        if matched_node_id is not None:
            return matched_node_id
        else:
            # 4. 全新漫展实体，独立建站
            fingerprint = f"{city_cleaned.lower()}_{name_slug}"
            base_fingerprint = fingerprint
            counter = 1
            while True:
                cursor.execute("SELECT id FROM normalized_events WHERE event_fingerprint = ?;", (fingerprint,))
                if not cursor.fetchone():
                    break
                fingerprint = f"{base_fingerprint}_{counter}"
                counter += 1
                
            cursor.execute(
                """
                INSERT INTO normalized_events (event_fingerprint, standard_name, city, start_date, end_date, event_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (fingerprint, event_name_cleaned, city_cleaned, event_date if current_dt else None, event_date if current_dt else None, event_type, now_str)
            )
            new_id = cursor.lastrowid
            print(f"\x1b[1;32m[Fusion Engine] 创建全新超级漫展节点 (ID: {new_id}): '{event_name_cleaned}' (📍 {city_cleaned})\x1b[0m")
            return new_id

    @staticmethod
    def update_event_bounding_box(cursor, normalized_event_id: int):
        """
        物理计算并更新超级 Event 节点的最宽举办日期区间 (start_date 和 end_date)
        """
        cursor.execute(
            """
            SELECT event_date FROM cosplay_events
            WHERE normalized_event_id = ? AND status != '已取消' AND event_date != '未知' AND event_date LIKE '____-__-__';
            """,
            (normalized_event_id,)
        )
        dates = [row[0] for row in cursor.fetchall()]
        if dates:
            min_date = min(dates)
            max_date = max(dates)
            cursor.execute(
                """
                UPDATE normalized_events
                SET start_date = ?, end_date = ?
                WHERE id = ?;
                """,
                (min_date, max_date, normalized_event_id)
            )
        else:
            # 脏数据防御性降级：全量未知时清空极值区间防止脏日期悬挂
            cursor.execute(
                """
                UPDATE normalized_events
                SET start_date = NULL, end_date = NULL
                WHERE id = ?;
                """,
                (normalized_event_id,)
            )
