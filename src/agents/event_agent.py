import os
import datetime
import logging
import json
import asyncio
import re
from pathlib import Path
from jinja2 import Template
from pydantic import ValidationError
from agents import Agent, Runner, RunConfig
from src.models.schemas import FinalOutput, TriageOutput
from src.config import settings
from src.tools.llm_bridge import LLMClientRegistry, RegistryModelProvider

# 初始化全局连接池和 ModelProvider 适配器
llm_registry = LLMClientRegistry(settings.llm_providers)
registry_model_provider = RegistryModelProvider(llm_registry)

from src.utils.logger import log_event

def get_rendered_instructions(template_name: str = "event_analysis.jinja2") -> str:
    """动态读取并使用 Jinja2 模板渲染 System Prompt，注入当前系统参考时间"""
    template_path = settings.PROJECT_ROOT / "config" / "templates" / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Jinja2 模板不存在: {template_path}")
        
    with open(template_path, "r", encoding="utf-8") as f:
        template_str = f.read()
        
    template = Template(template_str)
    beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
    current_date = datetime.datetime.now(beijing_tz).strftime("%Y-%m-%d")
    return template.render(current_date=current_date)

async def analyze_post_with_retry(content: str, url: str, published_at: str | None = None) -> list:
    """
    使用官方原生 openai-agents SDK 执行提炼任务。
    支持 settings.yaml 配置的单模型提取 (single) 和多模型共识裁决 (consensus) 两种流水线。
    """
    mode = settings.analysis_pipeline.get("mode", "single")
    input_text = ""
    if published_at:
        input_text += f"博文发布时间:\n{published_at}\n\n"
    input_text += f"博文正文:\n{content}\n\n原帖链接:\n{url}"
    run_cfg = RunConfig(model_provider=registry_model_provider)

    # ==============================================================================
    # 模式一：多模型共识裁决与预检分流流水线 (Consensus Mode)
    # ==============================================================================
    if mode == "consensus":
        # 1. 快速分流过滤 (Triage Filter)
        triage_prov = settings.analysis_pipeline.get("triage_provider", "openai")
        triage_mod = settings.analysis_pipeline.get("triage_model", "gpt-4o-mini")
        triage_model_spec = f"{triage_prov}/{triage_mod}"
        
        triage_agent = Agent(
            name="triage_analyzer",
            instructions="你是一个 Cosplay 活动初筛专家。请评估博文内容，判断博主是否发布了未来的漫展计划、签售出行、排班表或快闪计划。必须严格遵循规定的 Pydantic 强契约输出。",
            output_type=TriageOutput,
            model=triage_model_spec
        )
        
        try:
            triage_input = f"博文正文: {content}"
            if published_at:
                triage_input = f"博文发布时间: {published_at}\n\n{triage_input}"
                
            triage_res = await Runner.run(
                triage_agent,
                triage_input,
                run_config=run_cfg
            )
            triage_data = triage_res.final_output
            
            if triage_data and not triage_data.has_event:
                print("\x1b[1;32m[Agent] [Triage Result] 首轮预检确认无漫展计划，终止后续 LLM 链路并安全退出！\x1b[0m")
                return []
        except Exception as triage_err:
            # 预检 API 异常时，做防崩溃友好降级，直接继续后面的共识分析
            err_msg = f"首轮预检（Triage）接口发生抖动: {triage_err}。系统已友好自动跳过并强制激活完整共识分析流程。"
            print(f"\x1b[1;33m[Agent Warning] {err_msg}\x1b[0m")
            log_event("WARNING", "triage_analyze", err_msg, str(triage_err))

        # 2. 并行候选提取 (Parallel Extraction)
        extractors = settings.analysis_pipeline.get("extractors", [])
        
        async def run_single_extractor(idx, ext_cfg):
            prov = ext_cfg.get("provider", "openai")
            mod = ext_cfg.get("model", "gpt-4o-mini")
            model_spec = f"{prov}/{mod}"
            
            extractor_agent = Agent(
                name=f"extractor_{prov}_{mod}",
                instructions=get_rendered_instructions(),
                output_type=FinalOutput,
                model=model_spec
            )
            res = await Runner.run(
                extractor_agent,
                input_text,
                run_config=run_cfg
            )
            return res.final_output

        # 并发获取各个模型的提取草稿，以 return_exceptions=True 实现高容错
        candidate_tasks = [run_single_extractor(i, cfg) for i, cfg in enumerate(extractors)]
        candidate_results = await asyncio.gather(*candidate_tasks, return_exceptions=True)
        
        valid_outputs = []
        for i, res in enumerate(candidate_results):
            prov = extractors[i].get("provider")
            mod = extractors[i].get("model")
            
            if isinstance(res, Exception):
                err_msg = f"提取器 {prov}/{mod} 执行失败: {res}"
                print(f"\x1b[1;33m[Agent Warning] {err_msg}\x1b[0m")
                log_event("WARNING", "extractor_parallel", err_msg, str(res))
            elif res and hasattr(res, "event_list"):
                serialized = [event.model_dump() for event in res.event_list]
                valid_outputs.append({
                    "provider": prov,
                    "model": mod,
                    "event_list": serialized
                })
        
        if not valid_outputs:
            # 所有提取器均因接口故障崩溃，抛出异常以激活 3 次重试或回滚
            raise ValueError("所有并行提取器皆运行失败，提取主任务异常。")
            
        # 统计并累加所有提取器提取到的候选活动总数
        total_extracted_candidates = sum(len(out["event_list"]) for out in valid_outputs)
        if total_extracted_candidates == 0:
            print("\x1b[1;32m[Agent] 所有存活的提取器提取的候选活动数皆为空，免除终审裁判二次仲裁，直接安全退出。\x1b[0m")
            return []
            
        if len(valid_outputs) == 1:
            # 单侧降级：若只有一个提取器存活，直接降级采用其结果，跳过裁判避免二次开销
            print("\x1b[1;33m[Agent Warning] 仅有一个提取器成功运行，系统已自动降级为单侧信任模式，免除裁判二次仲裁。\x1b[0m")
            return valid_outputs[0]["event_list"]

        # 3. 金牌裁判审判裁决 (Judge Arbitration)
        judge_cfg = settings.analysis_pipeline.get("judge", {})
        judge_prov = judge_cfg.get("provider", "openai")
        judge_mod = judge_cfg.get("model", "gpt-4o")
        judge_model_spec = f"{judge_prov}/{judge_mod}"
        
        judge_instructions = get_rendered_instructions("event_consensus_judge.jinja2")
        judge_agent = Agent(
            name="consensus_judge_agent",
            instructions=judge_instructions,
            output_type=FinalOutput,
            model=judge_model_spec
        )
        
        judge_prompt = f"【待分析原始博文】:\n{content}\n\n原贴链接: {url}\n"
        if published_at:
            judge_prompt += f"博文发布时间: {published_at}\n"
        judge_prompt += "\n【模型候选提取结果】:\n"
        for out in valid_outputs:
            slimmed_list = []
            for event in out["event_list"]:
                slimmed_list.append({
                    "name": event.get("event_name"),
                    "date": event.get("event_date"),
                    "place": event.get("event_place"),
                    "desc": event.get("event_description"),
                    "conf": event.get("confidence")
                })
            judge_prompt += f"\n>>> 提取器 {out['provider']}/{out['model']} 候选数据:\n"
            judge_prompt += json.dumps(slimmed_list, ensure_ascii=False, indent=2) + "\n"
        
        max_retries = 3
        feedback_prompt = judge_prompt
        
        for attempt in range(1, max_retries + 1):
            try:
                result = await Runner.run(
                    judge_agent,
                    feedback_prompt,
                    run_config=run_cfg
                )
                final_data = result.final_output
                if final_data and hasattr(final_data, "event_list"):
                    events = [event.model_dump() for event in final_data.event_list]
                    print(f"\x1b[1;32m[Agent] [Judge Success] 终审仲裁完成，输出 {len(events)} 个高精度漫展活动数据！\x1b[0m")
                    return events
                else:
                    raise ValueError("终审裁判未成功返回结构化的 FinalOutput 实例")
            except (ValidationError, Exception) as e:
                err_msg = f"终审裁判在第 {attempt} 次提炼时发生异常: {e}"
                print(f"\x1b[1;33m[Agent Warning] {err_msg}\x1b[0m")
                log_event("WARNING", "judge_analyze", err_msg, str(e))
                
                if attempt == max_retries:
                    # 裁判最终崩掉，做极致安全防崩溃：降级信任首个提取器的完好数据并返回
                    fallback_events = valid_outputs[0]["event_list"]
                    print("\x1b[1;33m[Agent Warning] 终审裁判多次纠错重试均失败，自动安全降级，采用首个提取器数据返回以对齐状态。\x1b[0m")
                    log_event("WARNING", "judge_fallback", "裁判重试触顶，降级信任提取器 1", str(e))
                    return fallback_events
                
                feedback_prompt = f"{judge_prompt}\n\n⚠️ 【系统反馈：你上一次提取未通过 Pydantic 强校验，报错如下。请绝对依据错误修正输出格式】\n{str(e)}"

    # ==============================================================================
    # 模式二：单模型提取模式 (Single Model Mode - 保持向下兼容)
    # ==============================================================================
    else:
        instructions = get_rendered_instructions()
        agent = Agent(
            name="cosplay_event_analyzer",
            instructions=instructions,
            output_type=FinalOutput
        )
        
        max_retries = 3
        feedback_prompt = input_text
        
        for attempt in range(1, max_retries + 1):
            try:
                print(f"\x1b[1;34m[Agent] 启动 AI 增量分析 (尝试 {attempt}/{max_retries})...\x1b[0m")
                
                # 指定单模型进行执行
                result = await Runner.run(agent, feedback_prompt, run_config=run_cfg)
                final_data = result.final_output
                if final_data and hasattr(final_data, "event_list"):
                    events = [event.model_dump() for event in final_data.event_list]
                    return events
                else:
                    raise ValueError("LLM 未成功返回结构化的 FinalOutput 实例")
                    
            except (ValidationError, Exception) as e:
                err_msg = f"智能体在第 {attempt} 次提炼时发生异常: {e}"
                print(f"\x1b[1;33m[Agent Warning] {err_msg}\x1b[0m")
                log_event("WARNING", "agent_analyze", err_msg, str(e))
                if attempt == max_retries:
                    err_final = "达最大重试上限，增量记录分析失败，将优雅跳过该博文。"
                    print(f"\x1b[1;31m[Agent ERROR] {err_final}\x1b[0m")
                    log_event("ERROR", "agent_analyze", err_final, str(e))
                    raise e
                feedback_prompt = f"{input_text}\n\n⚠️ 【系统反馈：你上一次提取未通过 Pydantic 强校验，报错如下。请绝对依据错误修正输出格式】\n{str(e)}"
                
    return []
