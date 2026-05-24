## 1. 规约与说明文档先行建设

- [x] 1.1 编写 `AGENTS.md`，确立 OpenAI Agents SDK 官方原生范式优先原则、Pydantic 结构化数据校验契约、Tool 职责边界和错误自适应重试等规范
- [x] 1.2 编写 `README.md`，提供系统全局架构说明、数据生命周期图解和 CLI 快速开始指引
- [x] 1.3 编写项目根目录 `.gitignore`，确保强制忽略 `runtime/` 运行时目录（包含 `state.json` 及 SQLite db）和种子目录中的敏感证书文件 `config/cookies/*.json`（排除 `.example.json` 模板），杜绝凭证泄漏风险

## 2. 基础框架与 SQLite Coser CRUD 核心开发

- [x] 2.1 初始化 `pyproject.toml` 依赖关系配置，引入 `openai-agents`、`playwright`、`langfuse`、`click`、`jinja2` 等库，使用 `uv sync` 生成虚拟环境
- [x] 2.2 在 `src/main.py` 中编写 CLI 入口，包含与本地自托管 Langfuse (`http://localhost:3000`) 的 `auth_check` 启动性连通校验与降级逻辑（如连接失败转为本地 file log 并跳过追踪插桩，不卡死程序）
- [x] 2.3 创建配置文件 `config/settings.yaml`，规范定义 `db_path`, `default_limit`, `page_load_timeout_seconds`, `analyze_confidence_threshold`, `langfuse_host` 等参数，并编写 `src/config.py` 解析模块
- [x] 2.4 编写 `src/models/db_models.py`，使用原生 SQL 初始化 `cosers`（Coser 表）、`raw_posts`（博文缓存去重表，外键关联 `cosers.id`）和 `cosplay_events`（活动分析提取表，一对多外键关联 `raw_posts.id`，且含冗余 `coser_name` 以供直接导出）三张表，为 `raw_posts` 设定 `UNIQUE(platform, post_id)` 索引
- [x] 2.5 实现 `src/services/db_service.py` 核心数据库业务服务，封装底层的 `sqlite3` 连接。**必须保证活动数据批量写入 `cosplay_events` 与博文 `is_analyzed = 1` 状态更新在同一个 SQL 事务中执行以实现原子性，并在此阶段注入通过 `raw_posts.coser_id` 查询出的真实 `cosers.name` 到 `cosplay_events.coser_name` 字段**
- [x] 2.6 在 `src/main.py` 中编写 `cosevent coser` 子命令组，使用 click 实现包含 `add`（新增）、`list`（查询）、`update`（修改）和 `delete`（物理删除）的原生 SQLite CRUD 管理逻辑

## 3. Playwright 统一爬虫基类与平台 Scraper 开发

- [x] 3.1 创建 `config/cookies/` 目录，新建微博、B站、小红书的初始种子 Cookie 静态 JSON 模板文件（`weibo_cookies.json`, `bilibili_cookies.json`, `xhs_cookies.json`），创建对应的 `.example.json` 供提交
- [x] 3.2 编写 `src/tools/playwright_base.py`，实现无头爬虫基类 `BaseScraper`，支持 `runtime/{platform}/state.json` 载入与回写续期；支持本地 JSON 损坏时的降级重构；支持单次页面加载 15s 严格超时与浏览器崩溃自动重启上下文的容错恢复机制
- [x] 3.3 编写 `src/tools/weibo_scraper.py`，结合 `BaseScraper` 循环处理 active Coser（若微博 UID 为空则优雅跳过），拦截 `statuses/mymblog` 接口并根据 `--limit` 数量提取博文正文，带去重入库
- [x] 3.4 编写 `src/tools/bilibili_scraper.py`，结合 `BaseScraper` 循环处理 active Coser（若B站 UID 为空则优雅跳过），拦截 `web-dynamic/v1/feed` 接口并根据 `--limit` 数量提取博文正文，带去重入库
- [x] 3.5 编写 `src/tools/xhs_scraper.py`，结合 `BaseScraper` 循环处理 active Coser（若小红书 UID 为空则优雅跳过），拦截 `api/sns/web/v1/user_posted` 接口并根据 `--limit` 数量提取小红书笔记并解析正文，带去重入库

## 4. OpenAI Agent 核心定义与 Jinja2 Prompt 动态渲染

- [x] 4.1 编写 `config/templates/event_analysis.jinja2` 大模型 System Prompt Jinja2 模板，规范日期提炼规则，过滤无关及过期历史信息
- [x] 4.2 编写 `src/models/schemas.py`，定义 `CosEvent`（严禁包含 `coser_name` 字段以防大模型产生幻觉）和 `FinalOutput` Pydantic 校验模型，作为数据格式约束
- [x] 4.3 编写 `src/agents/event_agent.py`，基于官方原生 OpenAI Agents SDK `Agent` 定义 `event_agent`，并支持动态 Jinja2 模板渲染（注入当前系统日期）与 `output_type=FinalOutput` 结构化约束
- [x] 4.4 在 `src/agents/event_agent.py` 中开发针对 LLM 解析报错的自适应重试逻辑，捕获抛出的 Pydantic 错误并自动附加到上下文中重新发起调用，最多尝试 3 次

## 5. 定时调度流程与无乱码 CSV 导出

- [x] 5.1 编写一键导出命令 `cosevent export`，调用 `src/services/export_service.py` 过滤所有有效漫展记录，支持置信度阈值过滤（允许用户在导出时进行二次精细筛选），格式化为包含完整表头且基于 `utf-8-sig` (UTF-8 BOM) 编码的 CSV 文件，保障 Excel 双击打开无乱码
- [x] 5.2 编写 CLI `cosevent scrape` 独立爬取命令（支持从配置文件读取 limit 限制，循环抓取并去重新增入库）与 `cosevent analyze` 独立分析命令（支持 `--confidence-threshold`，仅提取 `is_analyzed = 0` 的增量记录分析，并以 SQL 事务更新标记为 1），最后编写主调命令 `cosevent process` 依次异步调用两者，提供完备的四色控制台日志输出格式化的四色 summary 执行执行报告

## 6. 全链路验证、自动化测试与追踪检查

- [x] 6.1 在 `tests/` 下编写 mock 离线博文正文文件，设计测试案例对 `event_agent` 和 Pydantic 的解析提取准确度、防格式崩溃重试次数进行单元测试验证，并对多活动写入及 `is_analyzed` 状态回滚的事务原子性进行测试验证
- [x] 6.2 运行一次完整的 `process` 命令，检查本地 `http://localhost:3000` Langfuse 控制台，核实 Agent 内部调用链路、思维链追踪、Tool Calls 行为以及 tokens 消耗上报是否正常显示，当本地服务未开启时验证其已友好降级
