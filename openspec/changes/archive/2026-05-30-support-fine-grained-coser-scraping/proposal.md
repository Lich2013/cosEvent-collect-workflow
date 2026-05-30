## Why

当前系统的微博、B站、小红书博文抓取任务采用全局无状态批处理设计（调用 `scrape` 命令行时无条件并发抓取所有已激活的 Coser 的所有平台动态）。
这导致在本地日常调试、二次编辑对齐测试或单点网络排查时，开发人员必须启动全量长轮询，不仅耗时较长、产生大量冗余的 Playwright 无头浏览器冷启动，还会消耗不必要的第三方 LLM 凭证与 API 配额资源。
通过引入针对特定 Coser 姓名（`--name`）以及特定平台（`--platform`）的细粒度过滤抓取能力，能极大缩短调试周期，实现精准的单点博文同步与增量分析。

## What Changes

- **新增 `scrape` 细粒度过滤选项**：升级终端命令行，在 `uv run python src/main.py scrape` 命令中新增可选参数 `--name`（指定 Coser 昵称）和 `--platform`（指定平台：`weibo`、`bilibili`、`xhs`、`all`）。
- **同步工作流与调度逻辑重构**：修改 `WorkflowOrchestrator.run_scrape` 的业务逻辑，支持接收可选的过滤姓名与过滤平台，在捞取数据库名单和派发抓取任务时进行条件精细化筛选，仅对满足条件的名单和平台启动 Scraper 交互。
- **向下兼容性保障**：若未指定任何过滤参数，系统必须默认维持原有的全量批处理抓取行为，确保生产定时任务或无参数调用无损平滑运行。

## Capabilities

### New Capabilities
<!-- 无新增的业务领域能力，仅对现有抓取行为进行升级 -->

### Modified Capabilities
- `content-scraping`: 升级抓取命令行与调度内核，增加通过指定 Coser 姓名与特定社交平台进行单点/多源细粒度抓取及增量更新的能力。

## Impact

- `src/main.py`：升级 `scrape` 命令定义，新增 `--name` 与 `--platform` Click 参数。
- `src/services/workflow_orchestrator.py`：重构 `run_scrape` 方法，在数据加载与爬取任务派发循环中引入名称与平台过滤。
- `tests/test_cosevent.py`：新增测试覆盖单点抓取的调度与过滤。
