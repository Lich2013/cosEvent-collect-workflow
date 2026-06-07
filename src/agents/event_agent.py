import os
import datetime
import logging
import json
import asyncio
import re
from pathlib import Path
from pydantic import ValidationError
from agents import Agent, Runner, RunConfig
from src.models.schemas import FinalOutput, TriageOutput, CandidateVerifyOutput
from src.config import settings
from src.utils.llm_factory import registry_model_provider
from src.utils.templates import render_instruction_template
from src.utils.logger import log_event

def get_rendered_instructions(template_name: str = "event_analysis.jinja2") -> str:
    """动态读取并使用 Jinja2 模板渲染 System Prompt，注入当前系统参考时间"""
    return render_instruction_template(template_name)

class AgentPipeline:
    """
    智能体分析提取流水线 (Pipeline Pattern)：
    将多模型共识裁决 (Consensus) 及单模型直接提取 (Single) 流程对象化封装，增强可读性与可测试性。
    """
    def __init__(self):
        self.run_cfg = RunConfig(model_provider=registry_model_provider)

    async def run_consensus_pipeline(self, content: str, url: str, published_at: str | None, input_text: str) -> list:
        """多模型共识裁决与首轮预检分流流水线"""
        # 1. 快速分流过滤 (Triage Filter)
        triage_prov = settings.analysis_pipeline.get("triage_provider", "openai")
        triage_mod = settings.analysis_pipeline.get("triage_model", "gpt-4o-mini")
        triage_model_spec = f"{triage_prov}/{triage_mod}"
        
        triage_agent = Agent(
            name="triage_analyzer",
            instructions="你是一个 Cosplay 活动初筛专家。请评估博文内容，判断博主是否发布了未来的漫展计划、一日店长（罗森店长等）、摄影会、受邀到店模特、签售出行、排班表或快闪计划。必须严格遵循规定的 Pydantic 强契约输出。",
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
                run_config=self.run_cfg
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
                run_config=self.run_cfg
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
                    run_config=self.run_cfg
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
        return []

    async def run_single_pipeline(self, content: str, url: str, published_at: str | None, input_text: str) -> list:
        """单模型分析直接提取流水线"""
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
                
                result = await Runner.run(agent, feedback_prompt, run_config=self.run_cfg)
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

    pipeline = AgentPipeline()
    if mode == "consensus":
        return await pipeline.run_consensus_pipeline(content, url, published_at, input_text)
    else:
        return await pipeline.run_single_pipeline(content, url, published_at, input_text)

async def analyze_candidate_posts(candidate_name: str, posts: list[dict]) -> dict:
    """
    使用 CandidateVerifyAgent 评估候选人最近的博文，判断是否为活跃 Coser。
    """
    # 获取默认或配置的模型提供商与模型名
    prov = settings.analysis_pipeline.get("triage_provider", "openai")
    mod = settings.analysis_pipeline.get("triage_model", "gpt-4o-mini")
    model_spec = f"{prov}/{mod}"
    
    verify_agent = Agent(
        name="candidate_verify_agent",
        instructions="你是一个二次元 Cosplay 专家审查员。根据用户提供的博主姓名及最近博文列表，进行客观评估，判断该博主是否是一个真实的、活跃的 Coser。必须严格遵循规定的 Pydantic 强契约输出。",
        output_type=CandidateVerifyOutput,
        model=model_spec
    )
    
    # 渲染输入模板
    input_prompt = render_instruction_template(
        "candidate_verify.jinja2",
        candidate_name=candidate_name,
        posts=posts
    )
    
    run_cfg = RunConfig(model_provider=registry_model_provider)
    
    max_retries = 3
    feedback_prompt = input_prompt
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"\x1b[1;34m[Agent] 启动候选人 [{candidate_name}] 文本核验分析 (尝试 {attempt}/{max_retries})...\x1b[0m")
            res = await Runner.run(
                verify_agent,
                feedback_prompt,
                run_config=run_cfg
            )
            final_data = res.final_output
            if final_data and hasattr(final_data, "is_active_coser"):
                return final_data.model_dump()
            else:
                raise ValueError("核验智能体未成功返回结构化的 CandidateVerifyOutput 实例")
        except (ValidationError, Exception) as e:
            err_msg = f"核验智能体在第 {attempt} 次核验时发生异常: {e}"
            print(f"\x1b[1;33m[Agent Warning] {err_msg}\x1b[0m")
            log_event("WARNING", "candidate_verify_agent", err_msg, str(e))
            if attempt == max_retries:
                err_final = f"已达最大重试上限，候选人 [{candidate_name}] 核验失败，将向上传播异常以保持其 pending 状态。"
                print(f"\x1b[1;31m[Agent ERROR] {err_final}\x1b[0m")
                log_event("ERROR", "candidate_verify_agent", err_final, str(e))
                raise e
            
            feedback_prompt = f"{input_prompt}\n\n⚠️ 【系统反馈：你上一次提取未通过 Pydantic 强校验，报错如下。请绝对依据错误修正输出格式】\n{str(e)}"
