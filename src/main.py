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
from src.services.db.coser_repository import CoserRepository
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
    # 前置校验名字相似度与平台 UID 占用冲突，并将警报输出到 stderr
    warnings = CoserRepository.check_coser_duplicates(name, weibo, bili, xhs, check_name_similarity=True)
    for warning in warnings:
        click.secho(warning, fg="yellow", bold=True, err=True)

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
    
    # 前置校验平台 UID 占用冲突（排除自身，不校验名字相似度），并将警报输出到 stderr
    warnings = CoserRepository.check_coser_duplicates(name, weibo, bili, xhs, exclude_name=name, check_name_similarity=False)
    for warning in warnings:
        click.secho(warning, fg="yellow", bold=True, err=True)

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

@coser.command("sync-bili")
@click.option("--limit", default=10, type=int, help="本次同步最大爬行/更新名额限制，默认 10")
@click.option("--dry-run", is_flag=True, help="仅进行检索和评分比对，不实际修改数据库")
def sync_bili_command(limit, dry_run):
    """[Sync Bili UID] 智能自动检索并启发式绑定活跃 Coser 的 B站 UID"""
    init_db()
    
    # 1. 捞取所有活跃且缺失 B站 UID 的 Cosers
    cosers = DBService.get_active_cosers_without_bilibili()
    if not cosers:
        click.secho("当前数据库中没有缺失 B站 UID 的活跃 Coser，无需同步！", fg="green", bold=True)
        return
        
    sync_limit = min(limit, len(cosers))
    click.secho(f"发现 {len(cosers)} 位活跃 Coser 缺失 B站 UID，本次同步上限设定为: {sync_limit} 位", fg="cyan", bold=True)
    
    # 批量提取要搜索的 Coser 名字列表
    keywords = [coser["name"] for coser in cosers[:sync_limit]]
    
    from src.tools.bilibili_scraper import BilibiliScraper
    from src.services.bili_uid_matcher import BiliUidMatcher
    
    scraper = BilibiliScraper()
    report = []
    
    try:
        # 2. 仅启动一次浏览器会话，执行批量拦截检索 (复用 Session，极大减少冷启动)
        results_map = asyncio.run(scraper.search_bilibili_users_batch(keywords))
        
        # 3. 循环处理各个 Coser 的打分匹配与入库
        for coser in cosers[:sync_limit]:
            name = coser["name"]
            old_uid = coser["bilibili_uid"]
            
            candidates = results_map.get(name, [])
            
            # 启发式打分优选 (已包含 Bio 交叉验证与冷启动免检通道)
            res = BiliUidMatcher.match_coser(name, candidates)
            best_match = res["best_match"]
            score = res["score"]
            candidates_list = res["candidates"]
            
            if best_match:
                new_uid = best_match["mid"]
                click.secho(f"✓ [{name}] -> 匹配成功: {best_match['uname']} (UID: {new_uid}) | 得分: {score:.1f}", fg="green")
                
                if dry_run:
                    report.append({
                        "name": name,
                        "status": "dry_run",
                        "old_uid": old_uid,
                        "new_uid": new_uid,
                        "score": score,
                        "candidates_count": len(candidates_list)
                    })
                else:
                    if DBService.update_coser(name, bilibili_uid=new_uid):
                        report.append({
                            "name": name,
                            "status": "success",
                            "old_uid": old_uid,
                            "new_uid": new_uid,
                            "score": score,
                            "candidates_count": len(candidates_list)
                        })
                    else:
                        report.append({
                            "name": name,
                            "status": "error",
                            "old_uid": old_uid,
                            "new_uid": None,
                            "score": 0.0,
                            "candidates_count": len(candidates_list)
                        })
            else:
                click.secho(f"✗ [{name}] -> 未检索到满足置信度门槛的匹配者。", fg="yellow")
                report.append({
                    "name": name,
                    "status": "no_match",
                    "old_uid": old_uid,
                    "new_uid": None,
                    "score": 0.0,
                    "candidates_count": len(candidates_list)
                })
    except Exception as e:
        click.secho(f"✗ 同步批处理发生异常: {e}", fg="red")
        for name in keywords:
            report.append({
                "name": name,
                "status": "error",
                "old_uid": "-",
                "new_uid": None,
                "score": 0.0,
                "candidates_count": 0
            })
            
    # 4. 渲染精美的表格同步报告
    TerminalRenderer.render_sync_bili_report(report)

@coser.command("list-candidates")
@click.option("--status", default="pending", type=click.Choice(["pending", "approved", "ignored"]), help="按状态过滤候选人列表，默认 pending")
def list_candidates_command(status):
    """[Coser Candidates] 查看自动发现的 Coser 候选记录"""
    init_db()
    candidates = DBService.list_candidates(status)
    click.echo(f"\n--- {status.upper()} Coser 候选人列表 (共 {len(candidates)} 人) ---")
    TerminalRenderer.render_candidates_table(candidates)

@coser.command("approve-candidate")
@click.option("--id", "candidate_id", type=int, required=True, help="要批准导入正式库的候选人 ID")
def approve_candidate_command(candidate_id):
    """[Coser Candidates] 批准候选人导入正式库"""
    init_db()
    if DBService.approve_candidate(candidate_id):
        click.secho(f"✓ 成功批准候选人 ID [{candidate_id}] 并导入正式 Coser 列表！", fg="green", bold=True)
    else:
        click.secho(f"✗ 批准候选人 ID [{candidate_id}] 失败，请检查 ID 是否正确且状态是否为 pending。", fg="red", bold=True)

@coser.command("reject-candidate")
@click.option("--id", "candidate_id", type=int, required=True, help="要忽略/拒绝的候选人 ID")
def reject_candidate_command(candidate_id):
    """[Coser Candidates] 忽略/拒绝候选人"""
    init_db()
    if DBService.reject_candidate(candidate_id):
        click.secho(f"✓ 成功忽略候选人 ID [{candidate_id}]！", fg="yellow", bold=True)
    else:
        click.secho(f"✗ 忽略候选人 ID [{candidate_id}] 失败，请检查 ID 是否正确且状态是否为 pending。", fg="red", bold=True)

@coser.command("discover")
@click.option("--limit", default=15, type=int, help="本次最多检索/验证新候选人的名额上限，默认 15")
def discover_command(limit):
    """[Coser Candidates] 手动触发对现有未处理/所有已分析博文进行 Coser 提及提取与自动发现"""
    init_db()
    click.secho("⏳ 正在拉取最近博文进行 @提及 提取分析...", fg="cyan")
    
    from src.models.db_models import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT content, post_url, coser_id, platform FROM raw_posts ORDER BY id DESC LIMIT 100;")
        rows = cursor.fetchall()
        posts = [{"content": r[0], "post_url": r[1], "coser_id": r[2], "platform": r[3]} for r in rows]
    finally:
        cursor.close()
        conn.close()
        
    if not posts:
        click.secho("没有在数据库中找到任何博文记录，无法进行发现分析。", fg="yellow")
        return
        
    from src.services.discovery_service import DiscoveryService
    discovered_count = asyncio.run(DiscoveryService.discover_candidates_from_posts(posts, limit))
    click.secho(f"\n✓ 自动发现任务结束。本轮共成功录入 {discovered_count} 个 pending 新候选人！", fg="green", bold=True)

@cli.command("scrape")
@click.option("--limit", default=None, type=int, help="单一平台单次最大爬取条数 (覆盖默认配置)")
@click.option("--name", default=None, help="仅更新指定姓名/昵称的 Coser 动态")
@click.option("--platform", type=click.Choice(["weibo", "bilibili", "xhs", "all"]), default="all", help="仅更新指定平台的数据（默认 all）")
@click.option("--batch-size", default=30, type=int, help="每次调度最大 Coser 数量限制，默认 30")
def scrape_command(limit, name, platform, batch_size):
    """[Scrape Phase] 异步去重抓取活跃 Coser 博文动态"""
    init_db()
    lim = limit or settings.default_limit
    total_cosers, success_platforms, total_inserted = asyncio.run(
        WorkflowOrchestrator.run_scrape(lim, coser_name=name, platform=platform, batch_size=batch_size)
    )
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

async def _async_process(limit, confidence_threshold, batch_size=None):
    """主工作流定时调度串联逻辑，爬虫出错不阻断分析"""
    click.echo("\n" + "=" * 40)
    click.secho("🤖 步骤 1/2: 正在启动异步去重新增爬取任务...", fg="yellow", bold=True)
    click.echo("=" * 40)
    total_cosers, success_platforms, total_inserted = 0, {"weibo": {"success": 0, "total": 0}, "bilibili": {"success": 0, "total": 0}, "xhs": {"success": 0, "total": 0}}, 0
    try:
        total_cosers, success_platforms, total_inserted = await WorkflowOrchestrator.run_scrape(limit, batch_size=batch_size)
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
        
    click.echo("\n" + "=" * 40)
    click.secho("🤖 步骤 3/3: 正在启动物化呈现视图滑动窗口重建...", fg="cyan", bold=True)
    click.echo("=" * 40)
    materialize_stats = None
    try:
        from src.services.db.materialize_service import MaterializeService
        materialize_stats = MaterializeService.rebuild_view()
    except Exception as e:
        click.secho(f"✗ 物化展示表重建遭遇严重崩溃异常: {e}", fg="red")
        
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
    
    if materialize_stats:
        click.secho("[Materializer 物化摘要]:", fg="cyan", bold=True)
        click.echo(f"- 历史已冻结展示节点数: {materialize_stats['frozen_nodes']} 个")
        click.echo(f"- 活跃日程聚类群组数: {materialize_stats['new_clusters']} 个")
        click.echo(f"- 写入/更新超级展示节点数: {materialize_stats['new_normalized_nodes']} 个")
        click.echo(f"- 本轮新增冻结展示节点数: {materialize_stats['newly_frozen_nodes']} 个")
    
    status_tracing = click.style("正常激活 (Local Langfuse)", fg="green") if is_langfuse_active() else click.style("已降级为本地日志审计", fg="yellow")
    click.echo(f"[Langfuse 追踪状态]: {status_tracing}")
    click.echo("=" * 40 + "\n")

@cli.command("process")
@click.option("--limit", default=None, type=int, help="单一平台最大爬取条数")
@click.option("--confidence-threshold", default=None, type=float, help="过滤基准置信度")
@click.option("--batch-size", default=30, type=int, help="每次调度最大 Coser 数量限制，默认 30")
def process_command(limit, confidence_threshold, batch_size):
    """[Process master] 依次调度 scrape 和 analyze，提供完备报告"""
    init_db()
    lim = limit or settings.default_limit
    threshold = confidence_threshold if confidence_threshold is not None else settings.analyze_confidence_threshold
    asyncio.run(_async_process(lim, threshold, batch_size=batch_size))

@cli.command("summary")
@click.option("--by-event", is_flag=True, help="按漫展超级节点展现集结详情看板")
@click.option("--confidence-threshold", default=0.0, type=float, help="置信度精筛阈值")
@click.option("--type", "event_type", default=None, type=click.Choice(['漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售']), help="按活动类型进行精细筛选看板")
@click.option("--city", default=None, help="按地级市进行日程精筛选看板，例如 --city 上海")
def summary_command(by_event, confidence_threshold, event_type, city):
    """[Dashboard] 展示 Cosplay 日程看板（支持按 Coser 或超级漫展聚合）"""
    init_db()
    if by_event:
        events = DBService.get_event_centric_summary(confidence_threshold, event_type=event_type, city=city)
        TerminalRenderer.render_event_centric_summary(events)
    else:
        events = DBService.get_all_events(confidence_threshold, scope="all", event_type=event_type, city=city)
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


@cli.command("deduplicate")
def deduplicate_command():
    """[Deduplicate] 一键物理去重并合并冗余的超级活动节点"""
    init_db()
    click.secho("⏳ 正在启动数据库存量超级节点一键式去重任务...", fg="cyan", bold=True)
    from src.services.db.dedup_service import DeduplicationService
    try:
        stats = DeduplicationService.deduplicate_database()
        click.secho("✓ 数据库存量超级节点去重合并成功完成！", fg="green", bold=True)
        click.echo(f"- 处理重复组数: {stats['processed_groups']}")
        click.echo(f"- 重定向日程数: {stats['merged_nodes']}")
        click.echo(f"- 别名重定向数: {stats['alias_redirects']}")
        click.echo(f"- 别名冲突合并数: {stats['alias_conflicts']}")
        click.echo(f"- 物理清理冗余节点数: {stats['deleted_nodes']}")
    except Exception as e:
        click.secho(f"✗ 数据库物理去重阶段遭遇严重崩溃异常: {e}", fg="red", bold=True)
        sys.exit(1)


@cli.command("materialize")
def materialize_command():
    """[Materialize] 一键重建与滑动冷热窗口去重的物化展示表"""
    init_db()
    click.secho("⏳ 正在启动物化呈现视图一键重建与滑动去重任务...", fg="cyan", bold=True)
    from src.services.db.materialize_service import MaterializeService
    try:
        stats = MaterializeService.rebuild_view()
        click.secho("✓ 物化展示表及滑动去重重建成功完成！", fg="green", bold=True)
        click.echo(f"- 历史已冻结展示节点数: {stats['frozen_nodes']}")
        click.echo(f"- 活跃待处理日程总数: {stats['active_schedules']}")
        click.echo(f"- 重定向至冻结节点日程数: {stats['mapped_to_frozen']}")
        click.echo(f"- 活跃日程聚类群组数: {stats['new_clusters']}")
        click.echo(f"- 写入/更新超级展示节点数: {stats['new_normalized_nodes']}")
        click.echo(f"- 本轮新增冻结展示节点数: {stats['newly_frozen_nodes']}")
    except Exception as e:
        click.secho(f"✗ 物化展示表重建遭遇严重崩溃异常: {e}", fg="red", bold=True)
        sys.exit(1)


def main():
    init_observability()
    cli()

if __name__ == "__main__":
    main()
