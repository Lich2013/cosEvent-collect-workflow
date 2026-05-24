## Context

系统目前已完成了 1.0 版本的核心功能开发和单元测试，包括 SQLite 数据库、Playwright 拦截爬虫、OpenAI Agents 分析提取以及 CSV 导出等流程。经过全方位的代码审查（Code Review），我们识别出系统在真实运行环境中、异常恢复状态下存在若干路径、规范、事务机制和本地降级日志方面的不足。本项目设计旨在以高内聚、低耦合的架构规范，重构和优化这部分边缘健壮性设计。

## Goals / Non-Goals

**Goals:**
- **规范路径定位**：彻底消除对 `os.getcwd()` 的依赖，全部换成项目物理路径定位，消除执行目录漂移引起的路径碎裂。
- **重构事务处理**：将 `db_service.py` 事务管理从脆弱的手动 `BEGIN TRANSACTION` 切换为标准的 `with conn:` 上下文管理器。
- **落实离线日志 fallback**：在 Langfuse 连通性自检失败时，真正激活本地 JSON 离线结构化日志写入 `runtime/logs/cosevent.json.log`。
- **消除模块耦合**：将 Scraper 平台对 NULL UID 的校验迁移至 Scraper 类方法内部，由底层执行防御跳过。
- **修复代码规范**：将 `Path` 等延迟导入的包移至文件顶部。
- **补充测试覆盖**：增加 CSV 编码、事务回滚细节和 `coser_name` 缓存属性等针对性测试用例。

**Non-Goals:**
- 不涉及任何 CLI 功能或参数的行为变更，保持与 1.0 版本接口完全一致。
- 不引入任何新的第三方库，依然使用 `pyproject.toml` 中的现有依赖。

## Decisions

### 1. 路径定位重构：绝对物理寻址替代 Working Directory 依赖
- **原因**：`os.getcwd()` 绑定终端工作目录，如果从外部目录或 Cron 定时任务执行命令会引发寻址漂移崩溃。
- **决策**：在 `src/config.py` 中引入 `PROJECT_ROOT = Path(__file__).resolve().parent.parent`，并导出该常量作为所有配置、DB、Cookie 和日志文件寻址的统一起点。

### 2. 事务原子性：Python 数据库连接管理器（Standard Connection Context Manager）
- **原因**：sqlite3 的默认隐式事务控制与显式手动 `BEGIN TRANSACTION` 发生冲突，是代码质量的隐患点。
- **决策**：使用标准库推荐的 `with conn:` 机制，它在抛出异常时自动回滚（ROLLBACK），块结束且无异常时自动提交（COMMIT）。

### 3. 本地日志记录：FileHandler 与结构化 JSON 格式
- **原因**：Langfuse 自检失败降级到本地后不能只是单纯的 `print` 错误，应该结构化落盘。
- **决策**：当 Langfuse `lf.auth_check()` 失败或不可用时，系统真正实例化一个 `logging.getLogger("cosevent")`，为其配置 `FileHandler` 写入 `runtime/logs/cosevent.json.log`，日志格式遵循 JSON 规范，记录关键字段：`timestamp`、`level`、`component`、`message`、`exception`。

### 4. 爬虫防御性校验前置：
- **原因**：如果 UID 为空，直接调用 `fetch_weibo_posts` 会导致 Playwright 无谓的页面加载并一直超时到 15s 后才崩溃跳过。
- **决策**：三平台爬虫在 `fetch_*_posts` 前置处防御检测：`if not uid: return []`。

## Risks / Trade-offs

- **[Risk]** 数据库并发写入可能触发 SQLite 的锁争用导致事务超时。
  - **Mitigation**：SQLite 本身是单写多读，我们保持每次分析原子提交单条博文，块事务运行时间极短，能有效缓解争用风险。
