## 1. 基础设施解耦 (LLM Factory & Templates)

- [x] 1.1 在 `src/utils/` 下新建 `llm_factory.py`，移动大模型连接池 `LLMClientRegistry` 和 `RegistryModelProvider` 的实例化逻辑至该单例工厂中。
- [x] 1.2 在 `src/utils/` 下新建 `templates.py`，实现统一的 `render_instruction_template` 工具函数，支持 Jinja2 模板路径寻址与北京参考时间动态注入。
- [x] 1.3 重构 `src/services/fusion_service.py`，移去冗余的 LLM 连接池初始化与 Jinja2 渲染拼装，改用全局统一单例和模板引擎。
- [x] 1.4 重构 `src/agents/event_agent.py`，移去冗余的 LLM 初始化与 Jinja2 渲染拼装。

## 2. 数据存储层拆分 (Repository & CQRS)

- [x] 2.1 将 inline 辅助方法（`validate_status`、`validate_type`）抽离至 `src/utils/validation.py`。将 `parse_city` 城市智能正则解析抽取至 `src/utils/parsers.py`。
- [x] 2.2 在 `src/services/db/` 目录下新建 `coser_repository.py`，迁移 Coser 相关的基础 CRUD 以及原始博文多版本管理（`save_raw_posts`、`get_unanalyzed_posts` 等）。
- [x] 2.3 在 `src/services/db/` 目录下新建 `event_repository.py`，迁移日程相关的原子并发写锁合并事务逻辑（`save_extracted_events_transactional`）。
- [x] 2.4 在 `src/services/db/` 目录下新建 `query_service.py`，迁移看板和日历相关的只读聚合查询逻辑（`get_all_events`、`get_event_centric_summary`、`get_normalized_events`）。
- [x] 2.5 重写 `src/services/db_service.py`，使之转变为轻量门面类（Facade），100% 对齐原 `DBService` 的所有 API 签名，并内部代理委托至新建的各 Repo 与 Service。

## 3. 终端展现层与工作流控制解耦 (View & Controller)

- [x] 3.1 在 `src/views/` 下新建 `terminal_renderer.py`，将 `main.py` 中所有的等宽拼装、看板彩显、月份/城市分组等 View 展现逻辑彻底搬迁过去。
- [x] 3.2 在 `src/services/` 下新建 `workflow_orchestrator.py`，迁移抓取（`_async_scrape`）、分析（`_async_analyze`）和串联（`_async_process`）的具体异步协调控制逻辑。
- [x] 3.3 重构 `src/main.py`，移除展示层与采集分析控制逻辑，使之转变为只负责 Click 装饰路由的轻量中转站。
- [x] 3.4 移动链路追踪 `init_observability` 到 `src/utils/observability.py` 中。

## 4. 智能体流水线对象化解耦 (Agent Pipeline)

- [x] 4.1 在 `src/agents/event_agent.py` 中，将 `consensus`（多模型共识）与 `single`（单模型提取）流程重构为 `AgentPipeline` 类，提高代码内聚性与可读性。

## 5. 验证与回归测试 (Verification & Testing)

- [x] 5.1 运行代码语法与类型静态自检，排除任何拼写及导入冲突。
- [x] 5.2 运行回归单元测试 `pytest -v tests/test_cosevent.py` 与 `pytest -v tests/test_niche_events.py`，验证 100% 向后兼容，且无任何破坏行为。
- [x] 5.3 运行 CLI 集成测试 `python src/main.py process --limit 2` 及 `python src/main.py summary --by-event`，验证全链路运行正常，控制台表格高颜值排版如初。
