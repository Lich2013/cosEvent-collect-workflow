import os
import sys
import click
import asyncio
import logging
import json
import datetime
from pathlib import Path
from tabulate import tabulate
from dotenv import load_dotenv

# 自动从项目根目录的 .env 文件加载环境变量
load_dotenv()

# 绝对寻址项目根目录以确保运行安全
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.models.db_models import init_db
from src.services.db_service import DBService
from src.services.export_service import ExportService
from src.tools.weibo_scraper import WeiboScraper
from src.tools.bilibili_scraper import BilibiliScraper
from src.tools.xhs_scraper import XhsScraper

# 全局变量记录 Langfuse 追踪可用性
LANGFUSE_ACTIVE = False

from src.utils.logger import log_event, setup_local_logging

def init_observability():
    """自检并初始化本地 Langfuse 追踪器"""
    global LANGFUSE_ACTIVE
    try:
        from langfuse import Langfuse
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
        
        # 将本地配置注入环境变量
        os.environ["LANGFUSE_HOST"] = settings.langfuse_host
        
        # 执行连通性自检
        lf = Langfuse()
        if lf.auth_check():
            # 自检成功，激活 OpenAI Agents 全局追踪插桩
            OpenAIAgentsInstrumentor().instrument()
            LANGFUSE_ACTIVE = True
            click.secho("✅ [Observability] 成功连接到本地 Langfuse 服务 (http://localhost:3000)，智能体追踪已启用！", fg="green")
        else:
            click.secho("⚠️ [Observability Warning] 本地 Langfuse 服务连接失败，系统已自动降级为本地日志审计模式！", fg="yellow")
            setup_local_logging()
    except Exception as e:
        click.secho(f"⚠️ [Observability Warning] 链路追踪检测异常: {e}。系统已友好降级为本地日志审计模式！", fg="yellow")
        setup_local_logging()

@click.group()
def cli():
    """Cosplay 活动收集提炼工作流 CLI 工具"""
    pass

@cli.command("init-db")
def init_db_command():
    """手动初始化 SQLite 数据库表结构"""
    init_db()

@cli.group("coser")
def coser():
    """Coser 追踪名单管理子命令 (CRUD)"""
    pass

@coser.command("add")
@click.option("--name", required=True, help="Coser 姓名/昵称")
@click.option("--weibo", default=None, help="微博 UID")
@click.option("--bili", default=None, help="B站 UID")
@click.option("--xhs", default=None, help="小红书 UID")
def add_coser(name, weibo, bili, xhs):
    """添加一个新的 Coser 到数据库"""
    init_db()
    if DBService.add_coser(name, weibo, bili, xhs):
        click.secho(f"✓ 成功注册 Coser [{name}] 并绑定 UID 凭证！", fg="green", bold=True)
    else:
        click.secho(f"✗ 注册 Coser [{name}] 失败，可能已存在同名记录。", fg="red", bold=True)

@coser.command("list")
def list_cosers():
    """查询并以表格形式输出所有追踪的 Coser"""
    init_db()
    cosers = DBService.list_cosers()
    if not cosers:
        click.echo("当前没有追踪任何 Coser，请使用 'coser add' 命令添加。")
        return
        
    table_data = []
    for c in cosers:
        status_str = click.style("启用", fg="green") if c["is_active"] == 1 else click.style("禁用", fg="red")
        table_data.append([
            c["id"],
            c["name"],
            c["weibo_uid"] or "-",
            c["bilibili_uid"] or "-",
            c["xhs_uid"] or "-",
            status_str,
            c["created_at"]
        ])
        
    headers = ["ID", "Coser 昵称", "微博 UID", "B站 UID", "小红书 UID", "状态", "创建时间"]
    click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))

@coser.command("update")
@click.option("--name", required=True, help="需要修改的 Coser 姓名/昵称")
@click.option("--weibo", default=None, help="更新后的微博 UID")
@click.option("--bili", default=None, help="更新后的B站 UID")
@click.option("--xhs", default=None, help="更新后的小红书 UID")
@click.option("--active", type=click.Choice(["0", "1"]), default=None, help="是否启用追踪：0-禁用, 1-启用")
def update_coser(name, weibo, bili, xhs, active):
    """修改指定 Coser 的平台 UID 或启用状态"""
    init_db()
    is_active = int(active) if active is not None else None
    
    if DBService.update_coser(name, weibo, bili, xhs, is_active):
        click.secho(f"✓ 成功更新 Coser [{name}] 的配置！", fg="green", bold=True)
    else:
        click.secho(f"✗ 更新 Coser [{name}] 失败，未找到该记录或没有有效的更新参数。", fg="red", bold=True)

@coser.command("delete")
@click.option("--name", required=True, help="需要删除的 Coser 姓名/昵称")
@click.confirmation_option(prompt="警告！确定要删除该 Coser 吗？这将级联物理删除其所有已存博文和提炼事件！")
def delete_coser(name):
    """从数据库中物理删除指定的 Coser 记录"""
    init_db()
    if DBService.delete_coser(name):
        click.secho(f"✓ 成功删除 Coser [{name}] 及其所有的级联数据！", fg="green", bold=True)
    else:
        click.secho(f"✗ 删除 Coser [{name}] 失败，未找到该记录。", fg="red", bold=True)

async def _async_scrape(limit):
    """异步爬行内部具体实现逻辑"""
    cosers = DBService.list_cosers(only_active=True)
    if not cosers:
        click.secho("[Scraper] 没有处于启用状态的 Coser 名单，自动跳过。", fg="yellow")
        return 0, {
            "weibo": {"success": 0, "total": 0},
            "bilibili": {"success": 0, "total": 0},
            "xhs": {"success": 0, "total": 0}
        }, 0
        
    weibo_sc = WeiboScraper()
    bili_sc = BilibiliScraper()
    xhs_sc = XhsScraper()
    
    total_cosers = len(cosers)
    success_platforms = {
        "weibo": {"success": 0, "total": 0},
        "bilibili": {"success": 0, "total": 0},
        "xhs": {"success": 0, "total": 0}
    }
    total_inserted = 0
    
    for c in cosers:
        # 微博抓取
        if c["weibo_uid"]:
            success_platforms["weibo"]["total"] += 1
            try:
                posts = await weibo_sc.fetch_weibo_posts(c["weibo_uid"], limit)
                if posts:
                    ins = DBService.save_raw_posts(c["id"], "weibo", posts)
                    total_inserted += ins
                success_platforms["weibo"]["success"] += 1
            except Exception as e:
                click.secho(f"✗ [Scraper ERROR] Coser [{c['name']}] 微博爬取失败: {e}", fg="red")
                log_event("ERROR", "scraper_weibo", f"Coser [{c['name']}] 微博爬取失败: {e}", str(e))
        
        # B站抓取
        if c["bilibili_uid"]:
            success_platforms["bilibili"]["total"] += 1
            try:
                posts = await bili_sc.fetch_bilibili_posts(c["bilibili_uid"], limit)
                if posts:
                    ins = DBService.save_raw_posts(c["id"], "bilibili", posts)
                    total_inserted += ins
                success_platforms["bilibili"]["success"] += 1
            except Exception as e:
                click.secho(f"✗ [Scraper ERROR] Coser [{c['name']}] B站爬取失败: {e}", fg="red")
                log_event("ERROR", "scraper_bilibili", f"Coser [{c['name']}] B站爬取失败: {e}", str(e))
                
        # 小红书抓取
        if c["xhs_uid"]:
            success_platforms["xhs"]["total"] += 1
            try:
                posts = await xhs_sc.fetch_xhs_posts(c["xhs_uid"], limit)
                if posts:
                    ins = DBService.save_raw_posts(c["id"], "xhs", posts)
                    total_inserted += ins
                success_platforms["xhs"]["success"] += 1
            except Exception as e:
                click.secho(f"✗ [Scraper ERROR] Coser [{c['name']}] 小红书爬取失败: {e}", fg="red")
                log_event("ERROR", "scraper_xhs", f"Coser [{c['name']}] 小红书爬取失败: {e}", str(e))
                
    return total_cosers, success_platforms, total_inserted

@cli.command("scrape")
@click.option("--limit", default=None, type=int, help="单一平台单次最大爬取条数 (覆盖默认配置)")
def scrape_command(limit):
    """[Scrape Phase] 异步去重抓取活跃 Coser 博文动态"""
    init_db()
    lim = limit or settings.default_limit
    total_cosers, success_platforms, total_inserted = asyncio.run(_async_scrape(lim))
    click.echo("\n" + "=" * 40)
    click.secho("[Scraper 爬取单步完成]", fg="yellow", bold=True)
    click.echo(f"- 活跃 Coser 数量: {total_cosers} 人")
    click.echo(f"- 博文去重新增入库数: {total_inserted} 条")
    click.echo("=" * 40 + "\n")

async def _async_analyze(confidence_threshold):
    """异步分析提炼内部具体实现逻辑"""
    from src.agents.event_agent import analyze_post_with_retry
    
    pending_posts = DBService.get_unanalyzed_posts()
    if not pending_posts:
        click.secho("[Analyzer] 没有发现未分析的增量博文，自动跳过。", fg="yellow")
        return 0, 0, 0
        
    total_posts = len(pending_posts)
    success_events_count = 0
    analyzed_count = 0
    
    for p in pending_posts:
        try:
            # 1. 大模型增量提炼
            events = await analyze_post_with_retry(p["content"], p["post_url"] or "", p["published_at"])
            
            # 2. 事务原子性写入 (内部会自动注入真实的 coser_name 冗余缓存)
            if DBService.save_extracted_events_transactional(p["id"], events, confidence_threshold):
                # 过滤出置信度合规的并累计
                filtered_events = [e for e in events if float(e.get("confidence", 1.0)) >= confidence_threshold]
                success_events_count += len(filtered_events)
                analyzed_count += 1
            else:
                err_msg = f"博文 ID {p['id']} 事务原子性入库失败！已自动回滚。"
                click.secho(f"✗ [Analyzer ERROR] {err_msg}", fg="red")
                log_event("ERROR", "analyzer_transaction", err_msg)
        except Exception as e:
            err_msg = f"提炼博文 ID {p['id']} 时发生异常: {e}"
            click.secho(f"✗ [Analyzer ERROR] {err_msg}", fg="red")
            log_event("ERROR", "analyzer_analyze", err_msg, str(e))
            
    return total_posts, success_events_count, analyzed_count

@cli.command("analyze")
@click.option("--confidence-threshold", default=None, type=float, help="过滤基准置信度 (覆盖默认配置)")
def analyze_command(confidence_threshold):
    """[Analyze Phase] 增量式分析未处理博文并原子性提炼活动入库"""
    init_db()
    threshold = confidence_threshold if confidence_threshold is not None else settings.analyze_confidence_threshold
    total_posts, success_events_count, analyzed_count = asyncio.run(_async_analyze(threshold))
    click.echo("\n" + "=" * 40)
    click.secho("[Analyzer 分析单步完成]", fg="blue", bold=True)
    click.echo(f"- 本次分析增量博文: {total_posts} 条")
    click.echo(f"- 成功提炼 Cosplay 活动: {success_events_count} 个")
    click.echo(f"- 成功回写状态博文数: {analyzed_count} 条")
    click.echo("=" * 40 + "\n")

async def _async_process(limit, confidence_threshold):
    """主工作流定时调度串联逻辑，爬虫出错不阻断分析"""
    # 步骤 1/2: Scrape 异步去重抓取 (不阻断步骤 2)
    click.echo("\n" + "=" * 40)
    click.secho("🤖 步骤 1/2: 正在启动异步去重新增爬取任务...", fg="yellow", bold=True)
    click.echo("=" * 40)
    total_cosers, success_platforms, total_inserted = 0, {"weibo": 0, "bilibili": 0, "xhs": 0}, 0
    try:
        total_cosers, success_platforms, total_inserted = await _async_scrape(limit)
    except Exception as e:
        click.secho(f"✗ 爬行阶段遭遇严重阻断异常: {e}", fg="red")
        
    # 步骤 2/2: Analyze 增量活动分析提炼
    click.echo("\n" + "=" * 40)
    click.secho("🤖 步骤 2/2: 正在启动 AI 增量活动提炼分析任务...", fg="blue", bold=True)
    click.echo("=" * 40)
    total_posts, success_events_count, analyzed_count = 0, 0, 0
    try:
        total_posts, success_events_count, analyzed_count = await _async_analyze(confidence_threshold)
    except Exception as e:
        click.secho(f"✗ 智能体提炼阶段遭遇严重阻断异常: {e}", fg="red")
        
    # 3. 输出漂亮的四色总结报告
    click.echo("\n" + "=" * 40)
    click.secho("cosevent process 执行报告", fg="cyan", bold=True)
    click.echo("=" * 40)
    click.secho("[Scraper 爬取摘要]:", fg="yellow", bold=True)
    click.echo(f"- 活跃 Coser 数量: {total_cosers} 人")
    click.echo(f"- 爬行成功平台数: 微博({success_platforms['weibo']['success']}/{success_platforms['weibo']['total']}), B站({success_platforms['bilibili']['success']}/{success_platforms['bilibili']['total']}), 小红书({success_platforms['xhs']['success']}/{success_platforms['xhs']['total']})")
    click.echo(f"- 新增博文入库数: {total_inserted} 条")
    
    click.secho("[Analyzer 分析摘要]:", fg="blue", bold=True)
    click.echo(f"- 本次分析增量博文: {total_posts} 条")
    click.echo(f"- 成功提取 Cosplay 活动: {success_events_count} 个 (置信度 >= {confidence_threshold})")
    click.echo(f"- 标注已分析博文: {analyzed_count} 条")
    
    status_tracing = click.style("正常激活 (Local Langfuse)", fg="green") if LANGFUSE_ACTIVE else click.style("已降级为本地日志审计", fg="yellow")
    click.echo(f"[Langfuse 追踪状态]: {status_tracing}")
    click.echo("=" * 40 + "\n")

@cli.command("process")
@click.option("--limit", default=None, type=int, help="单一平台最大爬取条数")
@click.option("--confidence-threshold", default=None, type=float, help="过滤基准置信度")
def process_command(limit, confidence_threshold):
    """[Process master] 依次调度 scrape 和 analyze，提供完备报告"""
    init_db()
    lim = limit or settings.default_limit
    threshold = confidence_threshold if confidence_threshold is not None else settings.analyze_confidence_threshold
    asyncio.run(_async_process(lim, threshold))

@cli.command("export")
@click.option("--output", required=True, help="CSV 导出文件路径")
@click.option("--confidence-threshold", default=0.0, type=float, help="二次过滤置信度精筛阈值")
def export_command(output, confidence_threshold):
    """一键无乱码导出提炼的 Cosplay 活动为 Excel CSV"""
    init_db()
    count = ExportService.export_events_to_csv(output, confidence_threshold)
    click.secho(f"✓ 成功过滤并导出 {count} 条 Cosplay 活动数据至 {output}！", fg="green", bold=True)

def main():
    init_observability()
    cli()

if __name__ == "__main__":
    main()
