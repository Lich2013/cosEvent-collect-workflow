## Why

解决系统在真实多变的物理运行环境下的健壮性隐患，修复代码规范（如 `Path` 延迟导入）与架构缺陷（如依赖 `os.getcwd()` 导致路径漂移、以及 `BEGIN TRANSACTION` 显式调用与 Python `sqlite3` 事务控制冲突的隐患），并落地设计文档中所载的本地 JSON 离线结构化日志降级，同时提高单元测试对核心边界用例的覆盖度。

## What Changes

- **修复代码规范**：将 `src/agents/event_agent.py` 中的 `from pathlib import Path` 移至文件顶部。
- **防止路径漂移**：将 `config.py`、`event_agent.py` 和 `playwright_base.py` 中的 `os.getcwd()` 依赖重构为基于 `__file__` 文件物理定位的项目根目录绝对路径定位。
- **重构数据库事务控制**：修改 `db_service.py` 中的 `save_extracted_events_transactional` 事务提交与回滚逻辑，移除显式的 `BEGIN TRANSACTION;` 执行，转为采用 Python 标准的 `with conn:` 数据库连接上下文事务管理器，消除数据库事务潜在冲突与锁死隐患。
- **落实本地 JSON 降级日志**：在 `LANGFUSE_ACTIVE = False` 连通自检失败时，真正配置并初始化 Python `logging` 的 `FileHandler`，在捕获抓取/分析/重试失败后，将结构化报错以 JSON 格式输出至 `runtime/logs/cosevent.json.log` 中。
- **增加爬虫健壮性边界防御**：在 Weibo, Bilibili, XHS Scraper 的具体获取逻辑中，增加对 `uid` 的防御性校验，当 UID 为空时优雅地在爬虫内部直接跳过，避免无谓的 Playwright 页面等待超时。
- **拓宽单元测试覆盖率**：在 `tests/test_cosevent.py` 中增加对 CSV 导出 BOM 字符校验、置信度多阶段阈值筛选、以及 `coser_name` 冗余注入关联查询的单元测试用例。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- 无

## Impact

- 影响模块包括 `src/config.py`、`src/agents/event_agent.py`、`src/services/db_service.py`、`src/tools/playwright_base.py`、三平台爬虫模块、`src/main.py` 以及测试用例 `tests/test_cosevent.py`。
- 本次重构无任何 BREAKING 破坏性变更，保持所有 CLI 命令行接口向前完全兼容。
