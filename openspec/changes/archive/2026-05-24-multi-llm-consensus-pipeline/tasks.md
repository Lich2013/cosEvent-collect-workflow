## 1. 基础配置扩展与模板建立

- [x] 1.1 修改 `config/settings.yaml`，引入 `llm_providers` 与 `analysis_pipeline` 相关的配置（如多提供商端点、API Key、Triage 预检模型和裁判设置），并同步更新 `config/settings.yaml.example` 模板。
- [x] 1.2 修改 `src/config.py` 中的 `Settings` 类，增加对多大模型供应商配置及共识流水线相关参数的载入、默认值设定与属性映射。
- [x] 1.3 创建裁判智能体专用的 Jinja2 Prompt 模板 `config/templates/event_consensus_judge.jinja2`，提供模糊活动合并、要素取最优、消解歧义规则及 Few-Shot 样例。
- [x] 1.4 在 `src/models/schemas.py` 中新增 `TriageOutput` Pydantic 强契约类，用于结构化预检分流，并同步在 `README.md` 中增加关于明文 API Key 泄漏风险的安全警告。

## 2. 动态多端点 ModelProvider 桥接与日志模块重构

- [x] 2.1 新建 `src/tools/llm_bridge.py`，实现 `LLMClientRegistry` 连接池，负责解析 yaml 配置中的环境变量占位符，并按需懒加载初始化不同平台的 `openai.AsyncOpenAI` 客户端。
- [x] 2.2 在 `src/tools/llm_bridge.py` 中实现自定义的 `RegistryModelProvider`（继承自 `agents.ModelProvider`），支持重写 `get_model(model_spec)`，使得 Agent 在运行时能够通过 `RunConfig` 动态分发路由到正确的端点、凭证和模型名。
- [x] 2.3 重构冗余日志代码：新建公共日志模块 `src/utils/logger.py`，抽取重复的 `log_event` 和 `setup_local_logging` 实现，并对 `main.py`、`event_agent.py`、`db_service.py` 和 `playwright_base.py` 进行全局重构导入，遵循 DRY 原则。

## 3. 共识与分流流水线编排

- [x] 3.1 在 `src/agents/event_agent.py` 中引入 `RegistryModelProvider`，并重构核心提取逻辑，使其支持 `single` 单模型提取与 `consensus` 多模型共识分析两种可配置的运行模式。
- [x] 3.2 使用强契约重构首轮预检（Triage）过滤：在 `src/agents/event_agent.py` 中实例化具有 `output_type=TriageOutput` 约束的预检智能体，根据预检对象的 `has_event` 状态决定是否截断流水线并退出，废除脆弱的纯文本正则模糊匹配。
- [x] 3.3 实现共识模式下的多模型并行提取与单侧降级旁路裁判：利用 `asyncio.gather(..., return_exceptions=True)` 并发提取并捕捉单侧故障，当仅有一侧成功时降级为单侧信任，自动旁路（跳过）裁判大模型，防止不必要的 Token 消耗。
- [x] 3.4 实现裁判智能体裁决与 Pydantic 强契约最终校验：将多提取器候选草稿提交给裁判智能体，引导高推理模型（如 GPT-4o）根据 `event_consensus_judge.jinja2` 进行去重、时间/场馆重叠检测及字段合并，最终强制输出经过 Pydantic 校验的 `FinalOutput`。

## 4. 单元测试与端到端验证

- [x] 4.1 在 `tests/test_cosevent.py` 中更新单元测试用例，覆盖：`TriageOutput` 强契约字段校验解析、预检为 False 时零活动直接终止且触发旁路、公共 Logger 通用日志调用等重构的核心逻辑。
- [x] 4.2 启动本地测试套件，并通过 `uv run python src/main.py analyze` 命令行工具运行提取分析，确保所有重构代码逻辑无漏，12 个测试场景完美通过且无运行期崩溃。
