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
        s = s.replace("bw", "bilibiliworld").replace("cp", "comicup")
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
        
        # ======================================================================
        # 【入口 O(1) 字典匹配与时间窗口秒配、时空纠偏级联处理】
        # ======================================================================
        name_slug = EventFusionService._clean_name(event_name_cleaned)
        
        # 1. 搜集候选节点 (本城 和 未知)
        fps = [f"{city_cleaned.lower()}_{name_slug}"]
        if city_cleaned != "未知":
            fps.append(f"未知_{name_slug}")
            
        placeholders = ",".join(["?"] * len(fps))
        cursor.execute(
            f"""
            SELECT id, event_fingerprint, standard_name, city, start_date, end_date
            FROM normalized_events
            WHERE event_type = '漫展' AND (event_fingerprint IN ({placeholders}) OR (city IN (?, '未知') AND standard_name = ?));
            """,
            (*fps, city_cleaned, event_name_cleaned)
        )
        candidates = cursor.fetchall()
        
        # 2. 搜集别名表候选节点 (本城 和 未知)
        alias_cities = [city_cleaned]
        if city_cleaned != "未知":
            alias_cities.append("未知")
        alias_placeholders = ",".join(["?"] * len(alias_cities))
        cursor.execute(
            f"""
            SELECT ne.id, ne.event_fingerprint, ne.standard_name, ne.city, ne.start_date, ne.end_date
            FROM event_aliases ea
            JOIN normalized_events ne ON ea.normalized_event_id = ne.id
            WHERE ea.alias_name = ? AND ea.city IN ({alias_placeholders}) AND ne.event_type = '漫展';
            """,
            (name_slug, *alias_cities)
        )
        alias_candidates = cursor.fetchall()
        
        # 合并去重
        candidate_map = {}
        for row in candidates + alias_candidates:
            candidate_map[row[0]] = row
            
        # 3. 7天时间窗口校验
        current_dt = None
        if event_date and re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
            try:
                current_dt = datetime.datetime.strptime(event_date, "%Y-%m-%d").date()
            except Exception:
                current_dt = None
                
        concrete_nodes = []
        unknown_nodes = []
        
        for c_id, fp, std_name, c_city, s_date, e_date in candidate_map.values():
            time_overlap = False
            if current_dt is None:
                # 待匹配日程时间为“未知”，只允许合并至同为“未知”时间的超级节点，或当前/未来年份的超级节点，防止坍塌到历史往届年份中
                if not s_date or s_date == "未知":
                    time_overlap = True
                else:
                    try:
                        node_year = int(s_date.split("-")[0])
                        current_year = datetime.datetime.now().year
                        if node_year >= current_year:
                            time_overlap = True
                    except Exception:
                        time_overlap = True
            else:
                # 待匹配日程具有具体时间，允许匹配“未知”时间节点，或与相差7天之内的具体节点秒配
                if not s_date or s_date == "未知" or not e_date or e_date == "未知":
                    time_overlap = True
                else:
                    try:
                        node_start = datetime.datetime.strptime(s_date, "%Y-%m-%d").date()
                        node_end = datetime.datetime.strptime(e_date, "%Y-%m-%d").date()
                        if (node_start - datetime.timedelta(days=7)) <= current_dt <= (node_end + datetime.timedelta(days=7)):
                            time_overlap = True
                    except Exception:
                        time_overlap = True
            
            if time_overlap:
                if c_city == city_cleaned:
                    concrete_nodes.append((c_id, fp, std_name, c_city, s_date, e_date))
                elif c_city == "未知":
                    unknown_nodes.append((c_id, fp, std_name, c_city, s_date, e_date))
                    
        # 4. 纠偏决策流
        if city_cleaned == "未知":
            if unknown_nodes:
                print(f"\x1b[1;32m[Fusion Engine O(1)] 快速匹配成功 (未知城市): '{event_name_cleaned}' ──▶ '{unknown_nodes[0][2]}' (ID: {unknown_nodes[0][0]})\x1b[0m")
                return unknown_nodes[0][0]
        else:
            if concrete_nodes:
                concrete_id = concrete_nodes[0][0]
                print(f"\x1b[1;32m[Fusion Engine O(1)] 快速匹配成功 (本城): '{event_name_cleaned}' ──▶ '{concrete_nodes[0][2]}' (ID: {concrete_id})\x1b[0m")
                
                # Task 3.3: 既存本城具体节点，级联重定向并清理无引用的“未知”城市节点
                if unknown_nodes:
                    import sqlite3 as sqlite_err
                    for unk_node in unknown_nodes:
                        unk_id = unk_node[0]
                        cursor.execute("UPDATE cosplay_events SET normalized_event_id = ? WHERE normalized_event_id = ?;", (concrete_id, unk_id))
                        try:
                            cursor.execute("DELETE FROM normalized_events WHERE id = ?;", (unk_id,))
                        except sqlite_err.IntegrityError as e:
                            print(f"\x1b[1;33m[Spatial Rectification Warning] 级联删除未知节点 ID {unk_id} 时触发外键约束冲突，已自动跳过删除以确保数据库完整性: {e}\x1b[0m")
                        print(f"\x1b[1;33m[Spatial Rectification] 检测到既存具体城市节点 (ID: {concrete_id})，级联重定向未知节点 (ID: {unk_id}) 的日程并物理合并该悬挂未知节点。\x1b[0m")
                
                return concrete_id
                
            elif unknown_nodes:
                # Task 3.2: 本城节点不存在，就地物理升级“未知”节点
                unk_id = unknown_nodes[0][0]
                target_fingerprint = f"{city_cleaned.lower()}_{name_slug}"
                
                cursor.execute(
                    "UPDATE normalized_events SET city = ?, event_fingerprint = ? WHERE id = ?;",
                    (city_cleaned, target_fingerprint, unk_id)
                )
                
                # 级联更新别名表城市，避免 UNIQUE(alias_name, city) 冲突，并在合并重复别名时输出可观测审计日志
                cursor.execute("SELECT id, alias_name, normalized_event_id FROM event_aliases WHERE normalized_event_id = ?;", (unk_id,))
                alias_rows = cursor.fetchall()
                for alias_db_id, alias_name, _ in alias_rows:
                    cursor.execute(
                        "SELECT id, normalized_event_id FROM event_aliases WHERE alias_name = ? AND city = ? AND id != ?;",
                        (alias_name, city_cleaned, alias_db_id)
                    )
                    existing_alias = cursor.fetchone()
                    if existing_alias:
                        target_node_id = existing_alias[1]
                        print(f"\x1b[1;33m[Spatial Rectification Audit] 别名 '{alias_name}' 在城市 '{city_cleaned}' 中已存在，指向超级节点 ID {target_node_id}。正在合并清理未知节点的重复别名行 (ID: {alias_db_id})。\x1b[0m")
                        cursor.execute("DELETE FROM event_aliases WHERE id = ?;", (alias_db_id,))
                    else:
                        cursor.execute("UPDATE event_aliases SET city = ? WHERE id = ?;", (city_cleaned, alias_db_id))
                        
                print(f"\x1b[1;32m[Spatial Rectification] 成功将“未知”城市节点 (ID: {unk_id}) 就地物理升级为具体城市 '{city_cleaned}'，更新指纹为 '{target_fingerprint}'。\x1b[0m")
                return unk_id

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
            if current_dt is None:
                # 待匹配日程时间为“未知”，只允许合并至同为“未知”时间的既存节点，或当前/未来年份的超级节点，防止坍塌到历史往届年份中
                if not start_date or start_date == "未知":
                    time_overlap = True
                else:
                    try:
                        node_year = int(start_date.split("-")[0])
                        current_year = datetime.datetime.now().year
                        if node_year >= current_year:
                            time_overlap = True
                    except Exception:
                        time_overlap = True
            else:
                # 待匹配日程有具体时间，可匹配未知时间节点或在3天时间窗口内的具体节点
                if not start_date or start_date == "未知" or not end_date or end_date == "未知":
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
                
            # 分支 2：0.2 <= R < 0.75 进入存疑区
            elif 0.2 <= ratio < 0.75:
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
