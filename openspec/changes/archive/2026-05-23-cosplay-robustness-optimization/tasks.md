## 1. 规约修复与物理根路径重构

- [x] 1.1 修复 `src/agents/event_agent.py` 中的 `Path` 延迟导入顺序，移至文件最顶部以符合规范
- [x] 1.2 重构 `src/config.py`，引入 `PROJECT_ROOT` 项目物理绝对寻址机制，并彻底替换项目中 `config.py`、`event_agent.py`、`playwright_base.py` 中所有的 `os.getcwd()` 为 `PROJECT_ROOT` 定位

## 2. 数据库事务重构与 Scraper 安全防御前置

- [x] 2.1 修改 `src/services/db_service.py` 中的 `save_extracted_events_transactional` 事务原子性逻辑，移除显式的 `BEGIN TRANSACTION;`，利用 Python 默认事务逻辑重构为 `with conn:` 上下文连接控制以保障线程/锁死安全
- [x] 2.2 在 Weibo, Bilibili, XHS 三平台 Scraper 类的 `fetch_*_posts` 核心方法前段增加对传入 `uid` 的防御性校验，当 UID 为空时在底层直接安全返回空列表，将低耦合前移防御

## 3. 本地 fallback JSON 日志配置与落盘落实

- [x] 3.1 在 `src/main.py` 的自检自适应 `init_observability` 降级分支中真正配置并注册标准的本地 `logging` 模块（配置 `FileHandler` 写入 `runtime/logs/cosevent.json.log`）
- [x] 3.2 在爬取、分析、重试失败报错后，除了在控制台发出警告/报错提示外，必须且将错误元数据以结构化 JSON 的形式记录落盘到上述日志中以供离线追踪审计

## 4. 测试用例补充与回归

- [x] 4.1 编写 `tests/test_cosevent.py` 中的新增测试用例，涵盖 CSV 导出的 `utf-8-sig` BOM 表头前缀校验，置信度二次过滤精筛逻辑，以及 `coser_name` 冗余注入及物理级联删除正确性校验
- [x] 4.2 运行本地 `uv run pytest` 并确保全部测试用例完美通过
- [x] 4.3 运行完整的 `uv run python src/main.py process` 工作流，验证无 API 键下的 3 次自适应错误纠错重试、本地 JSON 日志正常落盘与漂亮的四色报告输出
