## Context

本项目旨在建立一个自动化的 Cosplay 活动集中收集与分析系统。当前的活动数据高度分散在微博、B站、小红书等平台，且反爬机制严格、Cookie 寿命短。在技术选型上，本项目采用 `python3` 和 `uv` 进行依赖环境托管，使用官方的 `openai-agents` 作为智能体开发库，并利用 `sqlite3` 作为本地轻量数据库存储结构化数据。本项目还需要支持本地部署的 Langfuse 进行全链路追踪自检，以及 CLI 的 Coser CRUD 管理和 CSV 一键导出。

## Goals / Non-Goals

**Goals:**
- 实现 Coser 列表的 SQLite 本地持久化，并通过外键及唯一约束建立严密的“Coser -> 原始博文 -> 提炼活动”的一对多数据链。
- 提供 Click CLI 的 Coser 增删改查（CRUD）操作接口。
- 基于 Playwright Headless 模式自动维护微博、B站、小红书的登录态。用户通过安全的静态 `.json` 文件提供初始种子 Cookies，系统将其导入并自动同步最新的会话状态（Cookies + LocalStorage）在本地的 `runtime/{platform}/state.json` 中。
- 保证爬取数据的严格去重。原始博文表 `raw_posts` 通过唯一联合索引 `UNIQUE(platform, post_id)` 保证入库自动去重。
- 引入官方原生 `openai-agents` 库，设计格式化输出 `event_agent`，动态加载 Jinja2 模板，增量式提取未分析博文并提炼为 Cosplay 活动结构化数据，保存至 SQLite，并支持置信度阈值动态配置。
- 实现本地自托管 Langfuse 服务的启动自检。如连通，对 OpenAI Agent 进行自动插桩追踪；如不连通，友好降级且不阻断程序继续执行。
- 保护敏感文件不被提交。确保 `runtime/` 和种子 `cookies/*.json` 自动在 `.gitignore` 中被屏蔽。

**Non-Goals:**
- 不支持云端分布式爬行或多节点任务分发（仅单机工作流）。
- 不支持微博、B站、小红书之外的其他社交平台（如抖音、Twitter等）。
- 不包含任何图形用户界面 (GUI / Web UI)，仅提供纯命令行 CLI 界面。

## Decisions

### 1. 登录会话维护决策：静态 JSON 种子 + 本地 `state.json` 持久化 + Git 屏蔽
- **决策**：用户需在 `config/cookies/{platform}_cookies.json` 中以静态 JSON 格式提供初始 Cookie。首次运行后，Playwright 以 Headless 模式冷启动，加载该 JSON，进入页面获取完整 session 状态，保存到本地 `runtime/{platform}/state.json`。后续运行直接以 `storage_state` 加载并自动回写续期该 JSON。
- **安全保障**：所有敏感会话和包含凭据的文件（`runtime/` 和 `config/cookies/*.json`，排除 `.example.json`）必须强行加入项目的 `.gitignore`，防止误提交泄漏。

### 2. 数据库设计决策：严密关联表结构定义 + 原生 SQL 事务
- **决策**：采用 Python 内置的 `sqlite3` 模块开发，利用原生 SQL 语句直接操作数据。建立 `cosers`（Coser 管理表）、`raw_posts`（博文表，外键关联 `cosers`）、`cosplay_events`（活动分析提取表，外键关联 `raw_posts`）三张表。
- **具体 Schema 定义**：

#### A. `cosers` 表
```sql
CREATE TABLE IF NOT EXISTS cosers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    weibo_uid TEXT,
    bilibili_uid TEXT,
    xhs_uid TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### B. `raw_posts` 表
```sql
CREATE TABLE IF NOT EXISTS raw_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coser_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    post_id TEXT NOT NULL,
    content TEXT NOT NULL,
    post_url TEXT,
    is_analyzed INTEGER DEFAULT 0,
    scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(coser_id) REFERENCES cosers(id) ON DELETE CASCADE,
    UNIQUE(platform, post_id)
);
```

#### C. `cosplay_events` 表
```sql
CREATE TABLE IF NOT EXISTS cosplay_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_post_id INTEGER NOT NULL,
    coser_name TEXT NOT NULL,
    event_name TEXT NOT NULL,
    event_date TEXT NOT NULL,
    event_place TEXT NOT NULL,
    event_description TEXT,
    confidence REAL DEFAULT 1.0,
    source_url TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(raw_post_id) REFERENCES raw_posts(id) ON DELETE CASCADE
);
```

### 3. 配置与环境决策：`config/settings.yaml` 规格定义
为了避免各种超时时间、爬取条数、置信度阈值和追踪路径硬编码，系统引入 `config/settings.yaml`。其格式规范如下：
```yaml
# 本地 SQLite 路径
db_path: "runtime/cosevent.db"

# Scraper 参数
default_limit: 10
page_load_timeout_seconds: 15

# Agent 分析参数
# 数据库入库的基准置信度（低于此阈值的不入库）
analyze_confidence_threshold: 0.3

# Langfuse 本地路径
langfuse_host: "http://localhost:3000"
```

### 4. CLI 控制流决策：增量分析 + 事务原子性保证 + Coser昵称注入
- **决策**：
  - **`cosevent scrape` 逻辑**：查询所有 `is_active = 1` 的 Coser。针对每个 Coser 的每个平台，若 UID 为 `NULL` 或为空则优雅跳过；若不为空则以 `--limit N` (可配置项，默认 10) 爬取。
  - **`cosevent analyze` 逻辑**：只从数据库中增量读取 `is_analyzed = 0` 的博文记录交给大模型提取。提取成功后，将该博文的 `is_analyzed` 状态标记为 `1`。已标记为 `1` 的记录在后续分析中自动跳过。
  - **Coser昵称注入数据流**：`CosEvent` Pydantic 模型**绝对不**能从 LLM 端输出 `coser_name` 以免产生幻觉。在 `DBService` 执行 SQL 写入 `cosplay_events` 表时，必须由程序自动根据 `raw_posts.coser_id` 查询 `cosers.name` 并将其以参数形式注入到 `coser_name` 字段。
  - **事务原子性 (Atomicity)**：为了避免大模型提炼出多个活动时发生“部分入库、状态却标记为已分析”的数据丢失灾难，**`cosplay_events` 的多条活动插入与 `raw_posts` 的 `is_analyzed = 1` 更新状态，必须且 SHALL 统一包裹在同一个本地 SQL 事务 (`BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK`) 中**。

### 5. 主调度器执行决策：`cosevent process` 容错与执行 summary 格式
- **决策**：
  - **解耦容错**：`process` 依次异步调用 `scrape` 和 `analyze`。即便 `scrape` 遭遇大面积 Cookie 失效报错，`analyze` 命令**必须继续执行**以处理数据库中原有的存量未分析博文。
  - **执行 summary**：任务结束后，必须在控制台打印人性化且规格统一的四色报告总结，格式规范如下：
    ```text
    ========================================
    cosevent process 执行报告
    ========================================
    [Scraper 爬取摘要]:
    - 活跃 Coser 数量: 5 人
    - 爬行成功平台数: 微博(3/5), B站(4/5), 小红书(0/5)
    - 新增博文入库数: 12 条
    [Analyzer 分析摘要]:
    - 本次分析增量博文: 12 条
    - 成功提取 Cosplay 活动: 4 个 (置信度 >= 0.3)
    - 标注已分析博文: 12 条
    [Langfuse 追踪状态]: 正常激活 (或: 已降级为本地日志)
    ========================================
    ```

### 6. 链路追踪决策：本地 Langfuse + 自动插桩 + 日志降级
- **决策**：通过 `OpenAIAgentsInstrumentor().instrument()` 进行自动全局插桩，将 Tracing 数据发送至本地 `http://localhost:3000`。
- **降级机制**：若本地 Langfuse 不可用，`auth_check` 会友好地记录 `WARNING` 日志，禁用自动插桩追踪器，自动切换到本地结构化日志文件 `runtime/logs/cosevent.json.log` 中记录审计，保证本地完全闭环、不卡死。

## Risks / Trade-offs

- **[Risk] Cookie 过期或 `state.json` 文件损坏**
  - *Mitigation*：在 Scraper 中加入 `verify_session` 模块。如果 `state.json` 损坏/非法，自动**删除损坏文件**，打印警告日志并自动降级到种子 Cookie 重新生成会话；如果种子 Cookie 亦过期导致 API 拦截返回 401/403，爬虫会友好记录 `WARNING` 日志并跳过该平台，同时在控制台给予警告，提醒用户及时更新种子 JSON，避免程序卡死。
- **[Risk] 网络超时与浏览器崩溃阻断任务**
  - *Mitigation*：设置爬行页面 15s 严格超时。一旦超时或 Playwright 浏览器意外崩溃，系统将捕获异常并调用 Scraper 清理机制（优雅关闭及重启浏览器上下文），记录错误日志后**继续**执行下一个 Coser 的爬取，绝不阻断 CLI 整体运行。
- **[Risk] LLM 提取返回非法格式或置信度低下**
  - *Mitigation*：使用官方 OpenAI Agents SDK 原生重试规范（最多重试 3 次）。分析提取出的活动如果低于用户指定的 `--confidence-threshold` 阈值，则会在写入 `cosplay_events` 时被自动过滤或丢弃。
