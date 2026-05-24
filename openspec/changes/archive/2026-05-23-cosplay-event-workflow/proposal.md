## Why

目前漫展和 Cosplay 相关的活动宣传分散在微博、B站、小红书等各大社交平台，由不同的 Coser 或主办方独立发布，缺少一个集中式的浏览和追踪渠道。为了方便 ACG 爱好者能够一站式浏览和参与这些活动，需要开发一个能够从主流平台（微博、B站、小红书）自动收集、去重、LLM 智能提取并格式化导出 Cosplay 活动的集中化工作流系统。

## What Changes

本变更引入以下新功能与改进：
- **Coser 列表的 SQLite 持久化与 CLI 管理**：用本地 SQLite 存储 Coser 名单，并提供 Click 命令行（CRUD）入口进行增删改查。
- **Playwright 原生会话持久化与爬取引擎**：实现基于 Playwright 的原生爬虫工具，使用用户提供的种子 Cookies 初始化，并自动将更新后的完整会话状态（Cookies + LocalStorage）维护在本地 `runtime/{platform}/state.json` 中，以 Headless 无头模式抓取微博、B站、小红书的用户博文/动态，通过联合索引 `UNIQUE(platform, post_id)` 实现入库自动去重。
- **基于 OpenAI Agents SDK 的结构化提取智能体**：采用官方原生范式设计 `event_agent`，动态加载 Jinja2 prompt 模板，并通过 Pydantic `output_type=FinalOutput` 严格限制输出格式，具备 3 次错误重试与降级机制。
- **本地 Langfuse 链路追踪集成**：在 CLI 启动时自检本地 Langfuse 服务连通性，自动对 OpenAI Agent 进行插桩，实时上报 token 消耗、工具调用及思维链至本地 Langfuse 平台。
- **一键无乱码 CSV 导出**：支持通过 `cosevent export` 一键将格式化的活动列表导出为 UTF-8 BOM 编码的 CSV 文件，供用户离线浏览。

## Capabilities

### New Capabilities
- `coser-management`: 管理需要追踪的 Coser 列表，支持 SQLite 增删改查。
- `content-scraping`: 基于 Playwright 的会话持久化多平台（微博、B站、小红书）博文/动态爬虫工具。
- `event-extraction`: 使用 OpenAI Agents SDK 和 Jinja2 模板动态分析博文内容并进行 Pydantic 结构化数据提取的智能体。
- `data-export`: 支持一键导出格式化活动数据为无乱码 CSV 文件。
- `observability-tracing`: 本地 Langfuse 连通性检测与智能体全链路自动插桩追踪。

### Modified Capabilities
<!-- 本次为全新项目，无 Modified Capabilities -->

## Impact

- **系统依赖**：引入 `openai-agents`、`playwright`、`langfuse`、`click`、`jinja2` 等 Python 核心依赖。
- **本地环境**：本地需要运行 SQLite 以及自托管的 Langfuse 服务 (`http://localhost:3000`)。
- **数据结构**：在本地 `runtime/cosevent.db` 中建立 `cosers`、`raw_posts` 和 `cosplay_events` 三张核心表。
