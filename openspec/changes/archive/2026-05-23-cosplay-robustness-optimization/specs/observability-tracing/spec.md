## MODIFIED Requirements

### Requirement: 启动自检本地自托管 Langfuse 连接性与友好降级
系统**必须且 SHALL** 在 CLI 程序初始化或开始运行爬取/分析任务前，先验证与本地自托管 Langfuse 服务的网络与权限连通性：
- 默认连接的主机地址**必须且 SHALL** 为 `http://localhost:3000`（或通过 `.env` 中的 `LANGFUSE_HOST` 配置）；
- **必须且 SHALL** 调用 `Langfuse().auth_check()` 方法；
- 如果验证成功，控制台日志应输出绿色的成功状态并激活自动插桩追踪器；
- 如果验证失败，必须在控制台打印醒目的黄色警告，系统**必须且 SHALL** 优雅降级，完全不向 Langfuse 注册自动插桩追踪器以避免后续运行抛出连接报错，且绝对不能阻断后续任务在本地的继续执行；
- 在降级模式下，系统**必须且 SHALL** 自动激活本地结构化文件日志记录，配置并初始化标准的 Python `logging` 文件处理器，将运行时的所有异常、爬虫超时、大模型重试失败等结构化错误以标准 JSON 格式追加记录到项目根目录下的 `runtime/logs/cosevent.json.log` 文件中，确保离线状态下的可观测性。

#### Scenario: 成功连接至本地 Langfuse 并显示成功日志
- **WHEN** CLI 启动且本地 `http://localhost:3000` 上的 Langfuse 服务正常运行时
- **THEN** 控制台成功打印连接状态自检成功的通知，并正常激活追踪机制启动程序

#### Scenario: 本地 Langfuse 不可用时程序友好降级不阻断执行
- **WHEN** CLI 启动但本地 Langfuse 服务未开启（`auth_check()` 失败）时
- **THEN** 控制台成功捕获异常并打印黄色 Warn 日志，跳过追踪器插桩注册，配置并初始化本地 JSON 结构化日志输出，程序继续正常执行后续的所有本地爬取/分析任务并落盘错误日志
