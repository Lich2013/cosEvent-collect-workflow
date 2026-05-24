## MODIFIED Requirements

### Requirement: Click CLI scrape 控制流、NULL 平台跳过与错误恢复策略
Click 命令行工具**必须且 SHALL** 提供 `cosevent scrape` 独立爬取命令。该命令的控制流逻辑**必须且 SHALL** 遵循以下规范：
1. 从数据库中查询所有 `is_active = 1` 的 Coser；
2. 循环遍历每个 Coser 绑定的微博、B站、小红书 UID；
3. **NULL/空值跳过**：若某个 Coser 绑定的平台 UID 为 `NULL` 或为空字符串，系统**必须且 SHALL** 优雅跳过当前平台的爬取而不抛出异常；在具体平台的 Scraper 抓取方法中，系统**必须且 SHALL** 自主在爬取前段执行严格的 UID 校验防御，若 UID 为空或无效则直接在底层方法内优雅且安全地返回空列表，将校验拦截前移以降低子模块间的耦合度并防止 Playwright 的无效连接；
4. **加载超时与崩溃恢复**：单次页面加载**必须且 SHALL** 设置 15s 严格超时。一旦超时或 Playwright 浏览器发生意外崩溃，系统**必须且 SHALL** 捕获异常，打印错误日志，优雅重启浏览器上下文并**继续**执行下一个 Coser 的任务，绝对不能中断阻断 CLI 整体运行。

#### Scenario: 部分平台 UID 为空及页面加载超时不中断整体爬取
- **WHEN** Coser A 的微博 UID 为空，Coser B 发生 15s 页面加载超时，用户执行 `cosevent scrape` 命令时
- **THEN** 爬虫优雅跳过 Coser A 微博，捕获 Coser B 的超时错误并记录日志，顺利执行完其他 Coser 的爬行任务并正常退出，退出码为 0
