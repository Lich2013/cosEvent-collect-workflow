# Cosplay 活动分析收集系统 (cosEvent-workflow)

本项目是一个工程化的、基于 AI 智能体 (Agent) 与网页数据拦截 (Ajax Interception) 技术实现的 **Cosplay 活动信息集中收集与分析提炼系统**。它能够全自动、无头 (Headless) 爬取指定 Coser 在微博、B站、小红书的最新动态，利用多大模型共识裁决机制进行增量智能提炼，识别并格式化活动时间、地点与详情，淘汰高危物理删除并全面引入软状态机流转控制，最终支持一键无乱码导出 CSV 报表。

---

## 🏗️ 系统整体架构与数据流

本项目遵循 **“异步解耦、多级版本控制、软状态机对齐、强契约校验”** 的企业级工程化设计，其核心数据流生命周期图解如下：

```
┌────────────────────────────────────────────────────────────────────────┐
│                        cosEvent-workflow 数据流                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│   Coser CRUD 管理 (CLI) ──▶ SQLite `cosers` 列表表                      │
│                                      │                                 │
│                                      ▼ [读取活跃 UID]                  │
│                     Playwright Scraper 引擎 (Headless)                 │
│                 ┌────────────────────┴────────────────────┐            │
│                 ▼                                         ▼            │
│         [无本地 state.json]                      [存在本地 state.json]  │
│         加载种子 JSON Cookie,                    直接以 storage_state   │
│         冷启动并自动生成 state.json               无缝还原会话, 爬取完回写     │
│                 └────────────────────┬────────────────────┘            │
│                                      ▼                                 │
│      [数据采集端 - 高精版本化处理]                                     │
│      - 微博: 提取 edit_count 拼接 #v 后缀;                               │
│              异步拉取 editHistory API 物理编辑时间以防年份相对日期倒流     │
│      - B站/小红书: 写入层自动对比 content, 内容发生改变则自动合成          │
│                    递增 edit_count 并生成 #v 后缀记录                     │
│                                      │                                 │
│                                      ▼                                 │
│                             SQLite `raw_posts` 表                      │
│                        (UNIQUE 联合去重, is_analyzed=0)                 │
│                                      │                                 │
│                                      ▼ [增量分析拉取]                   │
│          Multi-LLM 智能共识裁决流水线 (Consensus Pipeline)             │
│      - 首轮 Triage 预检分流: has_event=False 直接截断退出，将博文标记已分析│
│      - 多模型并行提取 (Parallel Extract): Concurrently 并发调取 API    │
│      - 降级旁路裁判 (Judge Bypass): 提取结果为空或仅单侧成功时，自动旁路   │
│      - 金牌裁判仲裁 (Judge Agent): 高推理大模型执行模糊去重与场馆合并     │
│                                      │                                 │
│                                      ▼                                 │
│          核心原子型 SQLite 数据库事务写入层                            │
│      - 时区硬对齐: 强行对齐为东八区北京时间 (Asia/Shanghai)             │
│      - 软状态机管理 (Soft State Machine):                              │
│        * 历史已发生日程: 冷冻保护, 状态保持 '未开始' 且绝对不覆盖          │
│        * 既存先前版本的未来有效日程: 级联批量更新为 '已取消'             │
│        * 最新版未来有效日程: 执行增量 Upsert 合并, 默认 '未开始'         │
│        * 消失在最新分析中的日程: 软注销更新为 '已取消' (取代物理删除)   │
│      - 对应 raw_posts.is_analyzed 原子的更新为 1                       │
│                                      │                                 │
│                                      ▼                                 │
│             一键 Excel 双击无乱码 CSV 导出 (过滤 '已取消')              │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```


---

## 🛠️ 技术底座与核心选型

- **虚拟环境及包托管**：`Python 3.12+` / `uv`（极速包解析与隔离管理）
- **智能体引擎**：`openai-agents` (OpenAI 官方 Agents SDK)
- **网页爬虫**：`playwright` 异步接口监听（通过 `expect_response` 直接拦截网络接口）
- **本地存储**：`sqlite3` 原生轻量数据库（配合原生 SQL 事务处理）
- **可观测性**：`langfuse` + `openinference-instrumentation-openai-agents` 自动插桩注册

---

## 📂 项目关键目录结构

```text
cosEvent-workflow/
├── config/                  # 配置与种子凭证
│   ├── settings.yaml        # 全局参数配置文件 (限爬数、置信度阈值等)
│   ├── cookies/             # 初始种子 JSON Cookie 存放目录 (Git 忽略)
│   │   ├── weibo_cookies.json
│   │   ├── bilibili_cookies.json
│   │   └── xhs_cookies.json
│   └── templates/           # 智能体 Prompts Jinja2 模板
│       └── event_analysis.jinja2
├── runtime/                 # 运行期持久化及状态文件 (Git 忽略)
│   ├── cosevent.db          # SQLite 本地单文件数据库
│   ├── logs/                # 本地 JSON 日志
│   │   └── cosevent.json.log
│   ├── weibo/state.json     # 自动维护的微博 Session
│   ├── bilibili/state.json  # 自动维护的B站 Session
│   └── xhs/state.json       # 自动维护的小红书 Session
├── src/                     # 源代码目录
│   ├── main.py              # click CLI 入口 (Click 命令编排)
│   ├── config.py            # yaml 配置解析模块
│   ├── agents/              # OpenAI Agents 智能体类
│   ├── tools/               # Playwright 原生爬虫与会话自检
│   ├── models/              # SQLite 物理建表与 Pydantic 契约
│   └── services/            # 原生 SQL 事务及 CSV 导出服务
├── AGENTS.md                # Agent 编码与运行规范 (核心开发规约)
└── pyproject.toml           # 依赖打包配置文件
```

---

## 🚀 快速启动与使用指南

### 1. 安装依赖环境
使用 `uv` 快速拉起项目虚拟环境并同步依赖：
```bash
# 激活并安装依赖
uv sync
```

### 2. 配置环境变量与种子 JSON
复制并配置 `.env` 环境变量：
```bash
cp .env.example .env
# 编辑 .env 文件，填入：
# OPENAI_API_KEY, OPENAI_API_BASE
# LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST (默认为 http://localhost:3000)
```

> ⚠️ **安全警示**：为了防止 API Key 随 Git 泄露，请务必在 `config/settings.yaml` 中使用 `api_key: "${ENV_VAR}"` 环境变量占位符语法，并将真实的密钥配置在 `.env` 或系统环境变量中！请勿将明文 API Key 直接写入 YAML 配置文件中！

并在 `config/cookies/` 目录下放置您账号的种子 Cookie 文件。为了提供极佳的使用体验，系统已实现**双模自适应兼容**：
- **单行原始字符串（推荐）**：你只需直接从浏览器开发者工具（DevTools）网络请求头（Headers）中复制整行原始 Cookie 文本（例如 `"SUB=xxx; _s_tentry=yyy"` 或纯文本 `SUB=xxx; _s_tentry=yyy`）粘贴进文件即可。系统在载入时会自动在后台完成字符分割并匹配域名。
- **标准 JSON 字典数组**：可继续兼容由 Cookie 导出插件生成的原生 Playwright 格式列表。

### 3. CLI 命令行使用说明

#### 🔹 Coser 列表管理 (CRUD)
```bash
# 1. 注册新的 Coser
uv run python src/main.py coser add --name "Coser昵称" --weibo "9125039159" --bili "476566835"

# 2. 查看当前 Coser 列表及各平台 UID 绑定状态
uv run python src/main.py coser list

# 3. 追加绑定各平台 UID 或禁用/启用状态
# 提示：未指定的选项会保持原有数据不变；若想解绑某个平台，传入空字符串即可 (如 --xhs "")
uv run python src/main.py coser update --name "Coser昵称" --bili "476566835" --active 1

# 4. 删除 Coser
uv run python src/main.py coser delete --name "Coser昵称"
```

#### 🔹 执行数据采集与分析提炼
本系统在物理和逻辑上支持完全的爬行与分析解耦：
```bash
# 1. 独立爬行任务 (拉取所有 active Coser 博文，存入数据库并 UNIQUE 去重)
# 支持通过 --limit 限制单平台拉取数 (默认 10)
uv run python src/main.py scrape --limit 10

# 2. 独立分析任务 (增量拉取未处理博文，大模型分析，事务原子级录入 events 并标记状态)
# 支持通过 --confidence-threshold 过滤基准置信度 (默认 0.3)
uv run python src/main.py analyze --confidence-threshold 0.3

# 3. 统一调度进程 (依次顺序调用以上两者，完成闭环，输出漂亮的四色总结报告)
uv run python src/main.py process
```

#### 🔹 多格式与多范围精细过滤导出 (Export)
```bash
# 1. 默认快捷导出 (仅导出“未来及未知”有效日程，直接打印到标准输出 stdout 纯文本预览)
uv run python src/main.py export

# 2. 导出全量日程至美化纯文本文件
uv run python src/main.py export --output ./agenda.txt --scope all

# 3. 导出“未来及未知”日程至无乱码 Excel CSV 文件 (置信度精筛 0.8)
uv run python src/main.py export --output ./results.csv --confidence-threshold 0.8 --scope future

# 4. 支持 Shell 标准管道流重定向
uv run python src/main.py export --scope future > upcoming_events.txt
```
* **时间范围筛选 (`--scope`)**：支持 `future`（默认，仅未来及日期未知的潜在日程）与 `all`（全量历史与未来日程）。
* **自适应格式智能推理 (`--format` 或后缀)**：支持 `csv` 与 `txt`。若省略，系统会根据 `--output` 后缀自动识别为 CSV 表格（`utf-8-sig` 编码防乱码）或纯文本日程表；当不提供 `--output` 时，默认以优雅文本格式在终端控制台进行打印。
* **重定向友好**：当直接输出到控制台时，系统将提示语输出到 `stderr`，以防污染你的 Shell 重定向文件内容。
