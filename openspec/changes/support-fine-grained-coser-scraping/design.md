## Context

当前系统的 `scrape` 命令设计为定时全量批处理作业流（调用 `WorkflowOrchestrator.run_scrape` 抓取所有 `only_active=True` 的 Coser，且并发执行 `weibo`、`bilibili`、`xhs` 的拉取）。
对于开发者和维护人员，这种无状态的全量批处理缺少针对单点 Coser 或单点平台的调试能力。一旦希望调试某个特定 Coser（例如测试 B 站的物理版本更新判定），就不得不执行整个系统的长轮询抓取，等待多个无用平台的 Playwright 实例化和加载超时，效率低下且浪费 API 额度。
因此，我们需要在 `scrape` 命令行及工作流编排内核中，引入细粒度参数过滤。

## Goals / Non-Goals

**Goals:**
- **精细化参数注入**：在 `scrape` 命令行上提供可选的 `--name`（Coser 姓名昵称）与 `--platform`（平台类型精筛）参数。
- **高效的调度过滤**：重构 `WorkflowOrchestrator.run_scrape`，支持将参数传递至调度循环中，智能裁剪需要启动抓取的名单和具体平台类型，杜绝未指定平台的 Scraper 实例冷启动和网页超时等待。
- **平滑向下兼容**：在没有任何过滤参数传入时，系统必须无损回退到原有的全量批处理工作流状态。
- **异常容错处理**：若传入不存在的 Coser 姓名，系统能够打印黄色警告并安全返回 `(0, {}, 0)`，不发生任何程序崩溃。

**Non-Goals:**
- 重构 `analyze` 或 `process` 命令的参数接口（分析阶段天生基于已入库的 `is_analyzed=0` 博文增量处理，已实现高度解耦，无需在此阶段做单人过滤）。
- 修改现有的底层数据库表 Schema 结构。

## Decisions

### 1. 命令行参数的 Click 映射
- **决策**：在 `src/main.py` 的 `scrape_command` 中使用 Click 注解扩展参数接口：
  - `@click.option("--name", default=None, help="仅更新指定姓名/昵称的 Coser 动态")`
  - `@click.option("--platform", type=click.Choice(["weibo", "bilibili", "xhs", "all"]), default="all", help="仅更新指定平台的数据（默认 all）")`
- **透传机制**：通过 `asyncio.run(WorkflowOrchestrator.run_scrape(lim, coser_name=name, platform=platform))` 完成调度透传。

### 2. 编排内核的条件裁减与精细匹配
- **决策**：对 `WorkflowOrchestrator.run_scrape` 进行逻辑重构：
  - **姓名过滤**：捞取全部活跃 Coser 列表后，若指定了 `coser_name`，在内存中进行列表推导匹配（若 `name` 匹配，则仅保留该 Coser 记录）；若过滤后的列表为空，打印 `[Warning] 未找到处于激活状态且名为 [...] 的 Coser` 并优雅熔断返回空数据。
  - **平台过滤**：在抓取大循环中引入平台类型匹配。只有当 `platform in ("weibo", "all")` 时才执行微博 Scraper 请求，同理适用于 `bilibili` 与 `xhs`。
- **实现对比**：
  - *方案一（在数据库 SQL 层增加 WHERE 条件）*：需要修改 `CoserRepository` 底层接口和 Facade，容易破坏单元测试的兼容性。
  - *方案二（在内存中进行列表推导与裁剪，Facade 接口保持默认可选）*：底层数据库读取契约 100% 保持稳定，纯应用层完成裁剪，开发及测试成本低，极为优雅。
  - *最终选择*：采用**方案二**。

### 3. 数据契约的容错与状态返回
- **决策**：即使只抓取一个 Coser，`run_scrape` 依然返回相同的元组契约 `tuple[int, dict, int]`。这保证了 `TerminalRenderer` 等终端表格报告输出机制在零改动的前提下完全自适应展现。

## Risks / Trade-offs

- **[Risk 1] 传入了拼写错误的姓名导致列表为空**
  - **Mitigation**：系统将输出黄色警告信息 `Coser [...] 未找到或处于禁用状态`，随后返回空字典和计数，不会发生 SQL 查询异常或 Null 指针崩溃。
- **[Risk 2] 平台过滤导致 statistics 报告中其他平台数据丢失**
  - **Mitigation**：由于 `TerminalRenderer` 使用字典的 `success` 和 `total` 项呈现成功比率，系统在平台过滤时自动将未抓取的平台 total 标记为 `0`，避免了报告中的计算污染。
