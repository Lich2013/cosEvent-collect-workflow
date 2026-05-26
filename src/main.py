import os
import sys
import click
import asyncio
from pathlib import Path

# 绝对寻址项目根目录以确保运行安全
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
# 自动从项目根目录的 .env 文件加载环境变量
load_dotenv()

from src.config import settings
from src.models.db_models import init_db
from src.services.db_service import DBService
from src.services.export_service import ExportService
from src.services.workflow_orchestrator import WorkflowOrchestrator
from src.views.terminal_renderer import TerminalRenderer
from src.utils.observability import init_observability, is_langfuse_active

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
    TerminalRenderer.render_cosers_table(cosers)

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

@cli.command("scrape")
@click.option("--limit", default=None, type=int, help="单一平台单次最大爬取条数 (覆盖默认配置)")
def scrape_command(limit):
    """[Scrape Phase] 异步去重抓取活跃 Coser 博文动态"""
    init_db()
    lim = limit or settings.default_limit
    total_cosers, success_platforms, total_inserted = asyncio.run(WorkflowOrchestrator.run_scrape(lim))
    click.echo("\n" + "=" * 40)
    click.secho("[Scraper 爬取单步完成]", fg="yellow", bold=True)
    click.echo(f"- 活跃 Coser 数量: {total_cosers} 人")
    click.echo(f"- 博文去重新增入库数: {total_inserted} 条")
    click.echo("=" * 40 + "\n")

@cli.command("analyze")
@click.option("--confidence-threshold", default=None, type=float, help="过滤基准置信度 (覆盖默认配置)")
def analyze_command(confidence_threshold):
    """[Analyze Phase] 增量式分析未处理博文并原子性提炼活动入库"""
    init_db()
    threshold = confidence_threshold if confidence_threshold is not None else settings.analyze_confidence_threshold
    total_posts, success_events_count, analyzed_count = asyncio.run(WorkflowOrchestrator.run_analyze(threshold))
    click.echo("\n" + "=" * 40)
    click.secho("[Analyzer 分析单步完成]", fg="blue", bold=True)
    click.echo(f"- 本次分析增量博文: {total_posts} 条")
    click.echo(f"- 成功提炼 Cosplay 活动: {success_events_count} 个")
    click.echo(f"- 成功回写状态博文数: {analyzed_count} 条")
    click.echo("=" * 40 + "\n")

async def _async_process(limit, confidence_threshold):
    """主工作流定时调度串联逻辑，爬虫出错不阻断分析"""
    click.echo("\n" + "=" * 40)
    click.secho("🤖 步骤 1/2: 正在启动异步去重新增爬取任务...", fg="yellow", bold=True)
    click.echo("=" * 40)
    total_cosers, success_platforms, total_inserted = 0, {"weibo": {"success": 0, "total": 0}, "bilibili": {"success": 0, "total": 0}, "xhs": {"success": 0, "total": 0}}, 0
    try:
        total_cosers, success_platforms, total_inserted = await WorkflowOrchestrator.run_scrape(limit)
    except Exception as e:
        click.secho(f"✗ 爬行阶段遭遇严重阻断异常: {e}", fg="red")
        
    click.echo("\n" + "=" * 40)
    click.secho("🤖 步骤 2/2: 正在启动 AI 增量活动提炼分析任务...", fg="blue", bold=True)
    click.echo("=" * 40)
    total_posts, success_events_count, analyzed_count = 0, 0, 0
    try:
        total_posts, success_events_count, analyzed_count = await WorkflowOrchestrator.run_analyze(confidence_threshold)
    except Exception as e:
        click.secho(f"✗ 智能体提炼阶段遭遇严重阻断异常: {e}", fg="red")
        
    # 输出四色总结报告
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
    
    status_tracing = click.style("正常激活 (Local Langfuse)", fg="green") if is_langfuse_active() else click.style("已降级为本地日志审计", fg="yellow")
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

@cli.command("summary")
@click.option("--by-event", is_flag=True, help="按漫展超级节点展现集结详情看板")
@click.option("--confidence-threshold", default=0.0, type=float, help="置信度精筛阈值")
@click.option("--type", "event_type", default=None, type=click.Choice(['漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售']), help="按活动类型进行精细筛选看板")
def summary_command(by_event, confidence_threshold, event_type):
    """[Dashboard] 展示 Cosplay 日程看板（支持按 Coser 或超级漫展聚合）"""
    init_db()
    if by_event:
        events = DBService.get_event_centric_summary(confidence_threshold, event_type=event_type)
        TerminalRenderer.render_event_centric_summary(events)
    else:
        events = DBService.get_all_events(confidence_threshold, scope="all", event_type=event_type)
        TerminalRenderer.render_coser_centric_summary(events)

@cli.command("calendar")
@click.option("--city", default=None, help="指定过滤的城市，例如 --city 上海")
@click.option("--scope", default="future", type=click.Choice(["future", "all"]), help="时间过滤范围 (future: 未来及未知, all: 全量历史+未来)")
@click.option("--type", "event_type", default="漫展", type=click.Choice(['漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售']), help="活动类型精筛，默认仅展示'漫展'")
def calendar_command(city, scope, event_type):
    """[Calendar] 纯漫展视角时间轴日历展单"""
    init_db()
    events = DBService.get_normalized_events(city=city, scope=scope, event_type=event_type)
    TerminalRenderer.render_calendar(events, city=city, event_type=event_type)

@cli.command("export")
@click.option("--output", default=None, help="导出文件路径。如果不指定，则默认直接输出至终端标准输出 (stdout)")
@click.option("--confidence-threshold", default=0.0, type=float, help="二次过滤置信度精筛阈值")
@click.option("--scope", default="future", type=click.Choice(["future", "all"]), help="导出活动的时间范围 (future: 仅未来及未知活动, all: 全量历史+未来活动)")
@click.option("--format", "fmt", default=None, type=click.Choice(["csv", "txt"]), help="导出格式 (csv: Excel表格, txt: 纯文本报表)。若不指定则根据输出路径后缀自动智能推理")
@click.option("--view", default="default", type=click.Choice(["default", "calendar"]), help="选择导出视图 (default: Coser排班日程表, calendar: 智能融合后的超级漫展时间轴排期日历)")
@click.option("--type", "event_type", default=None, type=click.Choice(['漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售']), help="按活动类型精筛导出")
def export_command(output, confidence_threshold, scope, fmt, view, event_type):
    """一键导出提炼 of Cosplay 活动为 Excel CSV 或纯文本/Markdown"""
    init_db()
    count = ExportService.export_events(
        output_path=output,
        confidence_threshold=confidence_threshold,
        scope=scope,
        fmt=fmt,
        view=view,
        event_type=event_type
    )
    if output:
        click.secho(f"✓ 成功过滤并导出 {count} 条 Cosplay 活动数据至 {output}！", fg="green", bold=True)
    else:
        click.secho(f"✓ 成功过滤并输出 {count} 条 Cosplay 活动数据至标准输出！", err=True, fg="green", bold=True)

def main():
    init_observability()
    cli()

if __name__ == "__main__":
    main()
