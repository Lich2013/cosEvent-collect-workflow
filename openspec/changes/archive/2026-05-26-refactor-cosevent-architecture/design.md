## Context

随着微博二次编辑防漂移、二次元小众日程打标与融合旁路等核心业务能力的不断演进，系统的复杂性显著攀升。这导致原有的核心数据模块 `db_service.py` 膨胀至 651 行，不仅混合了 Coser 的基础 CRUD、原始博文的多版本更新管理，还揉入了大模型的原子写入事务以及看板/日历的超长聚合查询。

同时，`main.py` 作为 CLI 入口（441行），掺杂了极其繁琐的终端彩显渲染排版、等宽字符计算与采集/分析的流程控制代码；而 `event_agent.py` 与 `fusion_service.py` 中重复存在大模型客户端连接池初始化与 Jinja2 模板的解析渲染逻辑。

上述现象使这些模块演化成了典型的“上帝类 (God Class)”，严重违反了“单一职责原则 (SRP)”，增加了未来维护的风险，急需进行解耦和重构。

## Goals / Non-Goals

**Goals:**
*   **单一职责解耦**：将 `db_service.py` 彻底拆解为 Coser、博文、日程原子写入三个轻量级领域仓储以及一个只读查询服务。
*   **轻量级 CQRS (读写分流)**：将 summary 看板、calendar 日历等只读聚合查询与核心日程原子合并事务物理隔离开，隔离 SQL 变更风险。
*   **100% 向后兼容性**：保留 `src/services/db_service.py` 作为轻量 Facade 门面，保证所有已存外部引用（包括所有的单元测试套件 `pytest`）在零修改的前提下通过。
*   **展现层与流程控制隔离**：抽离控制台排版、等宽计算与 ANSI 彩显逻辑到 `terminal_renderer.py`；将工作流的异步编排胶水逻辑剥离到 `workflow_orchestrator.py`；`main.py` 仅作为纯粹的 Click 装饰器路由。
*   **基础设施统一化**：在 `src/utils/` 下统一 LLM 单例注册工厂与 Jinja2 模板加载渲染引擎，消除样板代码。
*   **严格遵循 AGENTS.md 规范**：100% 原样保留所有去幻觉、原子性事务回滚、裁判旁路、软状态机防御、Langfuse 自检降级、DeepSeek 传输层拦截转义防死锁等特种机制。

**Non-Goals:**
*   不变更系统的数据库物理 Schema，不增减表结构及字段约束。
*   不修改任何业务功能逻辑、时空融合引擎的相似度判定和日期区间收拢等核心算法。
*   不为任何单元测试代码本身做破坏性修改（即测试代码必须在零变动下通过）。

## Decisions

### 1. 门面模式 (Facade Pattern) 包装领域仓储
*   **决策**：在 `src/services/db/` 下建立 `coser_repository.py`、`post_repository.py`、`event_repository.py` 与 `query_service.py`。原 `db_service.py` 改写为 Facade 门面，对外签名保持 100% 一致，直接代理转发。
*   **理由**：物理文件大小可控制在平均 <100 行。通过门面模式能够以零侵入、零破坏的方式维持系统对外的稳定契约，达成无损平滑迁移。
*   **替代方案**：直接暴力修改所有导入了 `DBService` 的代码，将其重指向新的子服务。但这会导致极高的重构破坏面，大量测试代码都需要跟随着重构，极易产生回退漏洞。

### 2. 读写分离与轻量 CQRS 架构
*   **决策**：专门为 summary（Coser集结看板）、calendar（漫展日历看板）以及 `get_all_events` 汇总只读操作开辟独立的 `src/services/db/query_service.py`。写操作和原子事务保留在各自专属领域的 Repositories 中。
*   **理由**：看板和展示逻辑在迭代中会频繁发生排版、分类和汇总口径的微调，它的 SQL 往往极其臃肿；而 `save_extracted_events_transactional` 则是维护日程状态与外键完整性的关键所在。读写物理分流后，能完美隔离只读需求引起的 SQL 微调对写事务稳定性的潜在冲击。

### 3. View (展现层) 与 Controller (工作流编排) 彻底解耦
*   **决策**：
    1. 新建 `src/views/terminal_renderer.py`（View 层），将所有的 ANSI 彩显、`click.secho`、排版对齐以及 tabular 等计算抽取出来。
    2. 新建 `src/services/workflow_orchestrator.py`（Orchestrator 编排层），负责协调 scrape 抓取与 analyze AI 分析的具体流。
    3. `src/main.py` 重建为纯路由（Router 层），仅用于装饰 click 选项、绑定命令分支。
*   **理由**：原 `main.py` 的大部分臃肿都在于拼装终端的视觉效果。将渲染逻辑抽象为专职 View 后，主控逻辑非常清晰纯净。如果未来系统需要从 CLI 命令工具升级为 FastAPI 网页后端，我们可以在不改动任何核心业务逻辑的前提下，直接丢弃 `terminal_renderer` 并轻松复用所有 Orchestrator 与底层的仓储层服务。

### 4. 全局 LLM 单例工厂与 Jinja2 模板加载器
*   **决策**：在 `src/utils/llm_factory.py` 中初始化 `LLMClientRegistry` 和 `RegistryModelProvider` 的单例。在 `src/utils/templates.py` 中统一维护 `render_instruction_template` 函数。
*   **理由**：消除 `event_agent.py` 和 `fusion_service.py` 中各自重复配置 provider、加载 Jinja 渲染、拼接路径的样板文件代码，最大化连接池的复用性。

## Risks / Trade-offs

*   **[Risk] 门面类转发带来额外的栈调用开销**
    *   *Mitigation*：由于门面方法内部仅仅是在内存中对 Python 类静态方法进行简单的代理转发，相对于底层数据库的 SQLite 磁盘 I/O 以及大模型 API 的网络延迟，这种微小纳秒级的 Python 栈帧开销完全可以忽略不计。
*   **[Risk] 拆分文件过多，定位底层具体 SQL 时需要切换文件**
    *   *Mitigation*：在拆解中，子模块的物理边界和文件命名严格对齐数据库的表语义（`coser_repository` 管理 `cosers`，`post_repository` 管理 `raw_posts`）。这种领域级的高内聚高内聚性，使得开发人员能够一瞬间精准定位目标文件，相较于在原有 650 行的大文件中上下滚动更具效率。
