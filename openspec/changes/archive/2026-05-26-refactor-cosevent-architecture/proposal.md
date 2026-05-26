## Why

本重构旨在解决 Cosplay 活动分析收集系统中的架构臃肿问题。随着微博二次编辑防漂移、二次元小众日程打标与融合旁路等业务能力的不断叠加，存储服务层（`db_service.py`）和主控命令行入口（`main.py`）已逐渐演变为典型的“上帝类 (God Class)”，严重违反了“单一职责原则 (SRP)”。

为了确保后续新增功能（如实时排班看板、增量多平台增强采集等）的平滑演进，提高系统代码的内聚度、降低类行数、提高单元测试隔离度，我们亟需对核心数据存储、展现层和智能体调度进行优雅拆解。

## What Changes

本变更聚焦于纯粹的代码重构与架构解耦，不引入任何新的业务需求，且 **100% 保持向后兼容性**，确保既存的单元测试套件（如 `tests/test_cosevent.py` 等）无需任何修改即可完美通过：

*   **数据存储层拆解与门面包装**：
    *   将 `src/services/db_service.py`（651行）中的具体底层逻辑原封不动拆分至 4 个高度单一职责的仓储/服务子模块：`coser_repository.py`（Coser 管理）、`post_repository.py`（原始博文与版本控制）、`event_repository.py`（核心 AI 日程原子写入事务）与 `query_service.py`（聚合只读查询）。
    *   将 `db_service.py` 物理重写为超轻量级“门面 (Facade)”类，完全对齐原有 API 接口签名，内部直接做代理委托转发。
    *   将 inline 的 `validate_status` / `validate_type` 值域校验和 `parse_city` 正则解析抽离至 `src/utils/` 下。
*   **终端展现层与主控路由分流**：
    *   在 `src/views/` 下新建 `terminal_renderer.py`，将 `main.py` 中 `summary` 与 `calendar` 命令行下负责控制台彩显、等宽计算、月份/城市分组拼接的繁琐逻辑彻底剥离出去。
    *   将 `main.py` 中异步抓取/分析/串联流程调度（`_async_scrape` / `_async_analyze` / `_async_process`）移至 `src/services/workflow_orchestrator.py` 中。
    *   `src/main.py` 重新回归为极简的 CLI 路由定义层。
*   **大模型基础设施与智能体调度解耦**：
    *   在 `src/utils/llm_factory.py` 中统一管理 `LLMClientRegistry` 和 `RegistryModelProvider` 的全局单例，避免 `event_agent.py` 与 `fusion_service.py` 出现多重初始化样板代码。
    *   在 `src/utils/templates.py` 中实现统一的 Jinja2 提示词渲染器，共享路径解析与北京时间动态注入。
    *   在 `src/agents/event_agent.py` 中引入 `AgentPipeline` 类将提取策略的流程对象化。

## Capabilities

### New Capabilities
*   无新业务能力引入（纯技术架构重构与解耦）

### Modified Capabilities
*   无业务层面的需求变更（原有所有 spec 行为、接口与校验逻辑保持 100% 一致）

## Impact

*   **受影响文件**：
    *   `src/main.py` (大幅缩减，解耦视图与调度)
    *   `src/services/db_service.py` (重写为向后兼容的门面 Facade 类)
    *   `src/services/fusion_service.py` (移除冗余的 LLM 初始化与模板解析，采用全局单例)
    *   `src/agents/event_agent.py` (重构为管道调度模式，移除冗余的 LLM 初始化与模板解析)
*   **新增文件**：
    *   `src/services/db/coser_repository.py` (Coser CRUD 物理仓储)
    *   `src/services/db/post_repository.py` (博文多版本管理仓储)
    *   `src/services/db/event_repository.py` (核心原子写入事务仓储)
    *   `src/services/db/query_service.py` (看板/日历只读聚合查询服务)
    *   `src/services/workflow_orchestrator.py` (工作流异步调度编排服务)
    *   `src/views/terminal_renderer.py` (终端输出与表格排版渲染器)
    *   `src/utils/llm_factory.py` (LLM 单例工厂)
    *   `src/utils/templates.py` (Jinja2 统一渲染引擎)
    *   `src/utils/validation.py` (硬枚举与分类值域校验器)
    *   `src/utils/parsers.py` (城市提取等正则解析器)
*   **外部依赖与外部接口**：无变化。
*   **数据库物理 Schema**：无任何变化。
