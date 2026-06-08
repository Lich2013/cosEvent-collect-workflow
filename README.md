# Cosplay 活动分析收集系统 (cosEvent-workflow)

本项目是一个工程化的、基于 AI 智能体 (Agent) 与网页数据拦截 (Ajax Interception) 技术实现的 **Cosplay 活动信息集中收集、分析提炼与智能聚合系统**。它能够全自动、无头 (Headless) 爬取指定 Coser 在微博、B站、小红书的最新动态，利用多大模型共识裁决机制进行增量智能提炼，识别并格式化活动时间、地点与详情，通过时空聚类引擎自动将不同 Coser 的同场漫展归并为规范化超级节点，淘汰高危物理删除并全面引入软状态机流转控制，最终支持一键无乱码导出 CSV 报表与多维日历看板查询。

---

## 🏗️ 系统整体架构与数据流

本项目遵循 **"异步解耦、多级版本控制、软状态机对齐、时空智能聚合、强契约校验"** 的企业级工程化设计，其核心数据流生命周期图解如下：

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
│      [数据采集端 - 高精版本与自愈特征]                                 │
│      - 微博: 提取 edit_count 拼接 #v 后缀;                               │
│              异步拉取 editHistory API 物理编辑时间以防年份相对日期倒流     │
│      - B站: 双模自适应采集（gRPC优先+网页降级）。使用 gRPC 时由物理编辑时间│
│             进行高精版本化与事务去重，网页抓取时以内容变动驱动自适应合成    │
│      - 小红书: 写入层对比 content，内容发生改变则自动合成递增版本记录       │
│      - 个人简介 (Bio) 虚拟推文合成: 自动提取主页简介，封装为 `bio_{uid}`    │
│             虚拟动态注入分析流。在B站gRPC模式下自动通过 Card API 补爬。     │
│      - 超时与特征伪装自愈: Playwright 自动拦截超时并清除损坏 state.json,    │
│             降级以种子 Cookie 重建冷启动。配置 UA/Viewport 伪装避开 WAF。   │
│      - gRPC 凭证自愈式刷新: 自动拦截 -101 错误, 请求刷新 Token 并自动计算    │
│             客户端防爬签名, 成功后物理持久化回写重写覆写 `.env` 文件。      │
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
│      - 强锁包覆: 事务入口立即执行 `BEGIN IMMEDIATE` 强行锁表以防并发脏读    │
│      - 软状态机管理 (Soft State Machine):                              │
│        * 历史已发生日程: 冷冻保护, 状态保持 '未开始' 且绝对不覆盖          │
│        * 既存先前版本的未来有效日程: 级联批量更新为 '已取消'             │
│        * 最新版未来有效日程: 执行增量 Upsert 合并, 默认 '未开始'         │
│        * 消失在最新分析中的日程: 软注销更新为 '已取消' (取代物理删除)   │
│      - 三态状态机原子更新 (is_analyzed): 成功及空活动标记为 1; Pydantic  │
│        检验/断言/物理主键冲突等结构性失败回滚事务并独立标记为 2 隔离      │
│                                      │                                 │
│                                      ▼                                 │
│          智能时空聚类引擎 → `normalized_events` 超级节点              │
│      - 时空粗筛: 同城 + 日期差 ≤3 天进入比对                          │
│      - 双阈值融合: R≥0.75 直接合并; 0.5≤R<0.75 触发轻量 Judge 裁决   │
│        (裁决结果物理缓存别名表, 后续命中旁路裁判 Agent)                 │
│      - 智能旁路闸门 (Gated Bypass): 极简泛称（一日店长等）100% 旁路隔离；│
│        带品牌等专有名词的活动放行进入 O(1) 秒配与常规时空融合           │
│      - 时空纠偏升级: 处理具体城市日程时，自动将既存的 "未知" 城市同名   │
│        超级节点就地物理升级为该城市正式节点，执行级联重定向及别名合并   │
│      - start_date/end_date 自动包络融合为所有关联日期的 min/max        │
│                                      │                                 │
│                                      ▼                                 │
│          物化呈现视图 → `final_exhibition_view` (读写分离)             │
│      - 批重建强锁: process 结束时在 `BEGIN IMMEDIATE` 事务中一次性刷新  │
│      - 滑动冷热分区: 热活跃窗口 T_cold = 今天 - 30天；过老日程物理冻结  │
│      - 确定性指纹 ID: 主键强制采用 MD5(city+name_slug+type+bucket)     │
│                                      │                                 │
│                                      ▼                                 │
│   CSV 导出 (过滤 '已取消') │ summary --by-event │ calendar           │
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
# 编辑 .env 文件，填入相关的配置凭证。
```

> 💡 **B 站移动端第一方 gRPC 凭证获取及设备指引**
> 
> 为了让系统能稳定使用高精度的 gRPC 空间动态抓取并完美防范 B 站的风控安全拦截（如报错返回 `details = "-352"` 请求被拦截），请按以下步骤获取凭证并配置对齐指纹：
> 
> 1. **全自动扫码获取（强烈推荐）**：
>    在终端中运行高级扫码登录脚本：
>    ```bash
>    uv run python scripts/bili_app_qr_login.py
>    ```
>    - 运行后，终端会提示您选择模拟客户端。**强烈推荐选择 `[2] Bilibili HD (安卓平板版)`**。
>    - 使用您手机上的 B 站 App 扫描终端里渲染出的二维码，并在手机上确认登录授权。
>    - 授权成功后，终端会直接输出该客户端颁发的复合 `access_token`（长达 204 位）与数字 UID (`mid`)。
>    *(注：如需运行基于经典小电视 TV 协议的旧版脚本，可执行 `uv run python scripts/bili_qr_login.py`)*
> 
> 2. **配置 `.env` 环境变量**：
>    将获取到的凭证以及相配套的**指纹对齐变量**填入您项目根目录下的 `.env` 文件中：
>    ```bash
>    # B 站第一方 gRPC 凭证
>    BILIBILI_ACCESS_TOKEN=a1b49b065884f76ee3... (复制终端返回的完整长字符串)
>    BILIBILI_MID=3546926995737116
> 
>    # 🔹 客户端指纹对齐参数 (若在扫码时选择了 [2] Bilibili HD版，请如下配置以防 -352 拦截)
>    BILIBILI_MOBI_APP=android_hd
>    BILIBILI_DEVICE=pad
>    BILIBILI_BUILD=1410100
>    ```
>    - **为何要配置指纹参数？**：B 站在网关层实行设备与凭证强绑定核验。当您配置了 `android_hd` 指纹时，系统的 gRPC 客户端会自动将底层请求伪装为 Huawei MatePad 平板设备，完美匹配平板端 Token 的颁发载体，实现 100% 绿灯无阻碍通行。
> 
> 3. **抓包备选获取**：
>    如果选择手动抓包，可使用 PC 端抓包工具（如 **Charles** 或 **Fiddler**）在手机上拦截 B 站移动端 APP 流量。在 Host 包含 `bilibili.com` 的请求路径中找到 `access_key`（32位小写Hex），复制填入 `BILIBILI_ACCESS_TOKEN`，同时将 `BILIBILI_MID` 设置为您的账户数字 ID。此情况下对应的指纹配置应为默认的手机版配置：
>    ```bash
>    BILIBILI_MOBI_APP=android
>    BILIBILI_DEVICE=phone
>    BILIBILI_BUILD=8410300
>    ```
> 
> 4. **无痛降级**：
>    如果您不需要或不想使用 gRPC 抓取，可**直接留空**上述 `BILIBILI_` 相关的所有配置。系统在运行时会自动友好降级为 Playwright 无头网页渲染抓取，您只需在 `config/cookies/bilibili_cookies.json` 中放入您浏览器端普通的 B 站 Cookie 即可完美运行。


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

# 3. 禁用/修改 Coser 状态
uv run python src/main.py coser update --name "Coser昵称" --active 0

# 4. 删除 Coser
uv run python src/main.py coser delete --name "Coser昵称"
```

#### 🔹 智能 B站 UID 自动同步 (Sync Bili)

针对数据库中尚未绑定 B站 UID 的活跃 Coser，自动通过 B站搜索 API 批量检索候选账号，并利用启发式打分算法（昵称相似度 + Bio 关键词交叉验证）智能匹配并回写正确 UID：
```bash
# 1. 全自动批量同步 (默认上限 10 人)
uv run python src/main.py coser sync-bili

# 2. 指定本次最多同步 5 位 Coser
uv run python src/main.py coser sync-bili --limit 5

# 3. 预演模式：仅打印匹配分析报告，不修改数据库
uv run python src/main.py coser sync-bili --dry-run
```

* **`--limit N`**：限制本次最大同步人数配额，防止一次性消耗过多 API 资源，默认 10。
* **`--dry-run`**：仅执行搜索与启发式打分，输出候选对比报告，不写入数据库，适合在正式同步前人工审核结果。
* **批量复用会话与 WAF 降级**：所有 Coser 的检索在单次 Playwright 浏览器会话中完成。当检索遭遇 WAF 阻断或 2.5 秒内无响应时，秒级降级为 DOM 兜底解析，通过多选择器自适应兼容链定位 UID，并以正则提取粉丝数（支持“万”字换算）及个人签名。
* **新人免检绿色通道**：针对名字精确重名且具备官方认证的高信度新人 Coser，系统将开启免检绑定，忽略 `fans >= 100` 的低粉限制。

#### 🔹 Coser 候选人自动发现与管理 (Candidates)

系统在爬取博文时，如果发现博文中 @ 提及了其他二次元/Coser 昵称，会自动将提及对象预录入至候选人库中。
在运行 `discover` 命令时，系统会自动对待核验候选人执行自动核验流：
1. **背景资料抓取**：微博候选人通过 Ajax 接口拉取 UID 与简介，并自动裁剪专属昵称后缀；绑定 B站 UID 的候选人通过 Playwright 加载其空间主页并拦截 `wbi/acc/info` 接口，无损获取其完整签名及官方认证。
2. **免 LLM 强词匹配**：简介/认证命中强二次元特征词的候选人直接通过核验（`is_verified = 1`），免去后续 LLM 提炼流程。
3. **LLM 博文核验与三态流转**：未命中强词的候选人会被增量抓取其近期博文（弱特征抓取 10 条，普通抓取 3 条），调用核验智能体进行活跃 Coser 判定。若判定非 Coser 且置信度高（`>= 0.8`），则标记状态为 `'ignored'`；若置信度较低，则更新状态为 `'undetermined'` 并进入 7 天冷却期，两种情况均会自动物理清除 `candidate_raw_posts` 中的临时博文以保持数据库整洁。

你可以使用以下命令手动触发提及提取、核验与审核：
```bash
# 1. 手动触发对最近博文的提及提取与分析 (默认名额上限 15)
uv run python src/main.py coser discover --limit 15

# 2. 查看当前已发现的 Coser 候选人列表 (支持 pending / approved / ignored，默认 pending)
uv run python src/main.py coser list-candidates --status pending

# 3. 批准候选人导入正式追踪库
uv run python src/main.py coser approve-candidate --id <候选人_ID>

# 4. 忽略/拒绝候选人
uv run python src/main.py coser reject-candidate --id <候选人_ID>
```

#### 🔹 执行数据采集与分析提炼
本系统在物理和逻辑上支持完全的爬行与分析解耦：
```bash
# 1. 独立爬行任务 (拉取活跃 Coser 博文，存入数据库并 UNIQUE 去重)
# 支持通过 --limit 限制单平台拉取数 (默认 10)
# 支持通过 --name 过滤特定 Coser 姓名
# 支持通过 --platform 过滤特定平台 (weibo/bilibili/xhs/all，默认 all)
# 支持通过 --batch-size 限制单次最大分配去重 Coser 总量 (默认 30，实现有状态滑动窗口分批调度，规避风控阻断)
uv run python src/main.py scrape --limit 10 --name "池咲misa" --platform bilibili --batch-size 30

# 2. 独立分析任务 (增量拉取未处理博文，大模型分析，事务原子级录入 events 并标记状态)
# 支持通过 --confidence-threshold 过滤基准置信度 (默认 0.3)
uv run python src/main.py analyze --confidence-threshold 0.3

# 3. 独立物化重建与更新任务 (在单一原子事务中，对活跃时间窗口内的日程进行物化更新，划分冷热分区，生成确定性主键以保障路由稳定性)
uv run python src/main.py materialize

# 4. 统一调度进程 (顺序执行 scrape 爬取与 analyze 提炼后，在最末尾自动级联执行一次离线物化重建)
# 支持通过 --batch-size 限制单次最大爬取去重 Coser 总量 (默认 30)
uv run python src/main.py process --batch-size 30
```
* **细粒度过滤与滑动窗口调度 (`--name` / `--platform` / `--batch-size`)**：在数据爬取阶段，你可以通过指定 `--name` 匹配特定的 Coser，指定 `--platform` 匹配特定的社交平台以进行单点调试；在全量调度模式下，建议通过 `--batch-size`（默认 30）限制单次处理的去重活跃 Coser 总数。系统采用有状态时间滑动窗口算法，优先拉取各个平台最久未更新（或未爬取）的 Coser 列表，并在多个平台间采用公平的轮转机制（Round-Robin）动态分配配额，在保障队列流畅推进的同时完美规避高频风控阻断。
* **物化展示重建时机**：爬取分析和物化去重在物理上完全解耦以降低 SQLite 并发锁冲突。日程数据以只读状态存入 cosplay_events 事实表，展示层的数据一致性通过 `materialize` 重建指令（或 `process` 主任务链结束后自动级联调用）在原子写锁中一次性刷新物化表。

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
* **时间范围筛选 (`--scope`)**：支持 `future`（默认，仅未来及日期未知的潜在日程，且自动过滤已取消的日程）与 `all`（全量历史与未来日程）。
* **自适应格式智能推理 (`--format` 或后缀)**：支持 `csv` 与 `txt`。若省略，系统会根据 `--output` 后缀自动识别为 CSV 表格（`utf-8-sig` 编码防乱码）或纯文本日程表；当不提供 `--output` 时，默认以优雅文本格式在终端控制台进行打印。
* **视图模式与表格导出 (`--view`)**：支持 `default`（默认，以 Coser 行程明细排版）与 `calendar`（一键生成干净的 Markdown 表格日历或 Excel CSV 日历，包含日期、城市、名称、集结热度、展位）。
* **活动分类精筛 (`--type`)**：支持 `漫展`、`一日店长`、`摄影会`、`受邀模特`、`快闪/签售` 进行专属类型导出。
* **重定向友好**：当直接输出到控制台时，系统将提示语输出到 `stderr`，以防污染你的 Shell 重定向文件内容。当使用 `--format csv` 进行管道重定向时，系统会自动在 stdout 最前段注入 UTF-8 BOM（`\ufeff`），防止重定向生成的 CSV 文件在 Windows Excel 下打开时出现乱码。

#### 🔹 漫展集结看板 (Summary)

以归一化漫展超级节点为中心，纵览各漫展的完整集结阵容：
```bash
# 1. 默认视角：按 Coser 展示全量日程
uv run python src/main.py summary

# 2. 漫展视角：以超级漫展节点为外层，嵌套展示参展 Coser 信息、扮演角色与摊位
uv run python src/main.py summary --by-event

# 3. 按地级市进行精细筛选 (支持 Coser 视图与漫展视图)
uv run python src/main.py summary --city 上海
uv run python src/main.py summary --by-event --city 上海

# 4. 按活动类型与城市精筛联合使用
uv run python src/main.py summary --by-event --type 一日店长 --city 上海
```

* **`--by-event`**：切换为以归一化漫展（`normalized_events`）为大节点的层次化视图，嵌套展示各漫展下所有参展 Coser 的昵称、日期、扮演角色与摊位号（完全通过数据库物理联查，零 LLM 幻觉）。
* **`--city`**：支持按地级市名称精确过滤日程大看板，省略时默认展示全量城市。
* **`--type`**：支持 `漫展`、`一日店长`、`摄影会`、`受邀模特`、`快闪/签售` 五类精筛过滤，省略时默认输出全量日程。

#### 🔹 时间轴日历看板 (Calendar)

纯粹以"时间 + 空间"为维度查询高价值漫展排期，按月份多级聚合呈现：
```bash
# 1. 默认：查看所有城市的未来标准漫展排期
uv run python src/main.py calendar

# 2. 按城市过滤
uv run python src/main.py calendar --city 上海

# 3. 查看全量历史与未来漫展
uv run python src/main.py calendar --scope all

# 4. 查看特定小众活动类型的日历
uv run python src/main.py calendar --type 一日店长 --scope all
```

* **`--city`**：仅展示指定城市的漫展节点，省略时展示全国。
* **`--scope`**：`future`（默认，仅保留 `end_date >= 今日` 或日期未知的节点）/ `all`（含历史全量）。
* **`--type`**：默认值为 `漫展`，可切换为 `一日店长`、`摄影会` 等小众类型，实现大型漫展与小众活动的视觉分流。
* **输出格式**：按举办月份物理分组（如 `2026年5月`），月份内按日期升序排列，每个漫展节点显示名称、时间范围、城市场馆，以及 `👥 已集结 N 位 Coser` 的参展人数统计。

#### 🔹 维护与辅助工具 (Utilities)

```bash
# 1. 手动初始化 SQLite 数据库表结构 (用于在本地从零拉起或重建表)
uv run python src/main.py init-db

# 2. 一键物理去重并合并冗余的超级活动节点
# 合并由于拼写或缩写差异而重复产生的漫展超级节点，物理级归一化并合并 Coser 参展关联
uv run python src/main.py deduplicate
```

