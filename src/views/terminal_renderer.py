import click
import re
from tabulate import tabulate

class TerminalRenderer:
    """
    终端展现层 (View)：
    专门处理控制台表格对齐、高亮多色看板拼接、日历分组计算以及所有终端输出打印。
    """

    @staticmethod
    def render_cosers_table(cosers: list[dict]):
        """渲染 Coser 全量表格列表"""
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

    @staticmethod
    def render_event_centric_summary(events: list[dict]):
        """以超级漫展节点为维度的看板输出"""
        if not events:
            click.secho("当前没有任何已集结的超级漫展日程数据！", fg="yellow")
            return
    @staticmethod
    def _style_date(date_str: str) -> str:
        """当日程日期为推算时间时，在控制台进行等宽彩显拼接"""
        if not date_str:
            return ""
        if "(推算自超级节点)" in date_str:
            raw_date = date_str.replace(" (推算自超级节点)", "")
            return click.style(raw_date, fg="cyan") + click.style(" (推算自超级节点)", fg="magenta", dim=True)
        return date_str

    @staticmethod
    def render_event_centric_summary(events: list[dict]):
        """以超级漫展节点为维度的看板输出"""
        if not events:
            click.secho("当前没有任何已集结的超级漫展日程数据！", fg="yellow")
            return
        
        click.echo("\n" + "=" * 70)
        click.secho("🔥 【超级漫展集结看板】 | 📍 二次元时空聚合中心", fg="cyan", bold=True)
        click.echo("=" * 70)
        
        for ev in events:
            click.secho(f"\n======================================================================", fg="blue")
            click.secho(f"🔥 【{ev['standard_name']}】 | 📍 {ev['city']} | 📅 {ev['start_date']} 至 {ev['end_date']}", fg="white", bold=True)
            click.secho(f"======================================================================", fg="blue")
            click.secho(f"👥 已集结 Coser 人数: {len(ev['cosers'])} 位\n", fg="yellow")
            
            for cos in ev['cosers']:
                desc = cos['event_description'] or "暂无日程详情"
                click.echo(f"  🌟 [Coser] {cos['coser_name']}")
                click.echo(f"     ├─ 参展日期: {TerminalRenderer._style_date(cos['event_date'])}")
                click.echo(f"     ├─ 扮演角色/摊位: {desc}")
                click.echo(f"     └─ 提取置信度: {cos['confidence']:.2f}")
        click.echo("\n" + "=" * 70 + "\n")

    @staticmethod
    def render_coser_centric_summary(events: list[dict]):
        """以 Coser 为维度的排班日程看板输出"""
        if not events:
            click.secho("当前没有任何有效日程数据！", fg="yellow")
            return
        
        coser_map = {}
        for ev in events:
            cname = ev["coser_name"]
            if cname not in coser_map:
                coser_map[cname] = []
            coser_map[cname].append(ev)
            
        click.echo("\n" + "=" * 70)
        click.secho("👥 【Coser 排班日程看板】", fg="cyan", bold=True)
        click.echo("=" * 70)
        for cname, ev_list in coser_map.items():
            click.secho(f"\n👤 [Coser] {cname} (已提炼日程数: {len(ev_list)} 个)", fg="yellow", bold=True)
            for ev in ev_list:
                desc = ev['event_description'] or "暂无日程详情"
                click.echo(f"  ├─ 📅 {TerminalRenderer._style_date(ev['event_date'])} | 📍 {ev['event_place']}")
                click.echo(f"  │  活动名称: {ev['event_name']}")
                click.echo(f"  │  日程详情: {desc}")
                click.echo(f"  └─ 置信度: {ev['confidence']:.2f}")
        click.echo("\n" + "=" * 70 + "\n")

    @staticmethod
    def render_calendar(events: list[dict], city: str = None, event_type: str = "漫展"):
        """以时间轴日历分类的分组看板输出"""
        if not events:
            click.secho("未查询到符合条件的超级漫展排期数据！", fg="yellow")
            return
        
        monthly_map = {}
        for ev in events:
            start_date = ev["start_date"]
            month_key = "其他（未知档期）"
            if start_date and re.match(r"^\d{4}-\d{2}-\d{2}$", start_date):
                parts = start_date[:7].split("-")
                month_key = f"{parts[0]}年{parts[1]}月"
            
            if month_key not in monthly_map:
                monthly_map[month_key] = []
            monthly_map[month_key].append(ev)
            
        click.echo("\n" + "=" * 70)
        city_title = f" [{city}] " if city else " "
        type_title = event_type or "漫展"
        click.secho(f"📅 【二次元{city_title}{type_title}展讯日历看板】", fg="green", bold=True)
        click.echo("=" * 70)
        
        keys = list(monthly_map.keys())
        keys.sort(key=lambda x: (x == "其他（未知档期）", x))
        
        for month in keys:
            click.secho(f"\n⏳ 【{month}】", fg="cyan", bold=True)
            for ev in monthly_map[month]:
                date_str = ev['start_date']
                if ev['start_date'] != ev['end_date'] and ev['end_date'] != '未知':
                    date_str = f"{ev['start_date']} 至 {ev['end_date']}"
                
                # 等宽彩显拼接支持 (若含有推算标记)
                if "(推算自超级节点)" in date_str:
                    raw_date = date_str.replace(" (推算自超级节点)", "")
                    date_style = click.style(raw_date.ljust(22), fg="cyan") + click.style(" (推算自超级节点)", fg="magenta", dim=True)
                else:
                    date_style = date_str.ljust(22)
                    
                click.echo(f"  📍 {ev['city'].ljust(4)} | 📅 {date_style} | 🎪 {ev['standard_name']}")
                click.echo(f"     └─ 👥 已集结 {ev['coser_count']} 位 Coser 嘉宾")
        click.echo("\n" + "=" * 70 + "\n")

    @staticmethod
    def render_sync_bili_report(report: list[dict]):
        """渲染 B站 UID 智能同步四色彩显结果报告"""
        if not report:
            click.secho("没有执行任何 Coser 的 B站 UID 同步动作。", fg="yellow")
            return
            
        table_data = []
        for item in report:
            status = item["status"]
            if status == "success":
                status_str = click.style("成功绑定", fg="green")
            elif status == "dry_run":
                status_str = click.style("匹配成功 (预览)", fg="cyan")
            elif status == "no_match":
                status_str = click.style("未找到高信度匹配", fg="yellow")
            else:
                status_str = click.style("同步失败", fg="red")
                
            table_data.append([
                item["name"],
                item["old_uid"] or "-",
                item["new_uid"] or "-",
                f"{item['score']:.1f}" if item["score"] > 0 else "-",
                f"{item['candidates_count']} 个",
                status_str
            ])
            
        headers = ["Coser 昵称", "原 B站 UID", "新 B站 UID", "匹配得分", "候选人数", "同步状态"]
        click.echo("\n" + "=" * 75)
        click.secho("⚡ 【Coser B站 UID 智能自动同步报告】", fg="cyan", bold=True)
        click.echo("=" * 75)
        click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))
        click.echo("")
