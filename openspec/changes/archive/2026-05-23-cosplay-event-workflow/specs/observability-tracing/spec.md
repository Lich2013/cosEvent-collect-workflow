## ADDED Requirements

### Requirement: 启动自检本地自托管 Langfuse 连接性与友好降级
系统必须在 CLI 程序初始化或开始运行爬取/分析任务前，先验证与本地自托管 Langfuse 服务的网络与权限连通性：
- 默认连接的主机地址必须为 `http://localhost:3000`（或通过 `.env` 中的 `LANGFUSE_HOST` 配置）；
- 必须调用 `Langfuse().auth_check()` 方法；
- 如果验证成功，控制台日志应输出绿色的成功状态并激活自动插桩追踪器；
- 如果验证失败，必须在控制台打印醒目的黄色警告，系统必须**优雅降级，完全不向 Langfuse 注册自动插桩追踪器以避免后续运行抛出连接报错**，且绝对不能阻断后续任务在本地的继续执行。

#### Scenario: 成功连接至本地 Langfuse 并显示成功日志
- **WHEN** CLI 启动且本地 `http://localhost:3000` 上的 Langfuse 服务正常运行时
- **THEN** 控制台成功打印连接状态自检成功的通知，并正常激活追踪机制启动程序

#### Scenario: 本地 Langfuse 不可用时程序友好降级不阻断执行
- **WHEN** CLI 启动但本地 Langfuse 服务未开启（`auth_check()` 失败）时
- **THEN** 控制台成功捕获异常并打印黄色 Warn 日志，跳过追踪器插桩注册，程序继续正常执行后续的所有本地爬取/分析任务

### Requirement: 智能体运行链路的零侵入式自动插桩追踪
系统必须在初始化且 Langfuse 连通性自检成功阶段通过 `openinference.instrumentation.openai_agents` 注册自动插桩追踪器。在 `event_agent` 调用 `Runner.run_streamed()` 的全生命周期中：
- 智能体每一次接收到的用户指令和上下文必须被完整记录；
- 智能体执行过程中的思维链（Thinking Process）及 Tool Calls 必须被自动捕获；
- 智能体所调用的 API 耗时、消耗的 prompt 和 completion tokens 必须自动上报到本地 Langfuse 系统，以便在 Langfuse 仪表盘中呈现场景的调用图谱。

#### Scenario: Agent 运行时调用链与 Token 消耗自动在 Langfuse 展现
- **WHEN** 智能体开始运行博文分析提取且后台发起 OpenAI API 请求后
- **THEN** 本地 Langfuse 仪表盘（Dashboard）中能自动生成一条新的 trace，完整树状记录了本次提取任务下的子调用步骤、时序耗时以及 Token 统计数据
