## 1. 数据库升级与迁移 (Database Migration)

- [x] 1.1 在 `src/models/db_models.py` 的 `init_db()` 中，新增创建 `candidate_raw_posts` 表的 SQL 初始化语句，支持以 `candidate_id` 关联 `coser_candidates(id)`。
- [x] 1.2 在 `init_db()` 中，编写检测并在 `coser_candidates` 表中自动热追加 `verify_reason TEXT` 属性的 SQLite DDL 迁移逻辑。
- [x] 1.3 在 `src/services/db/candidate_repository.py` 中，新增适配 `verify_reason` 属性的增改查（add_candidate / list_candidates）操作，并新增 `save_candidate_raw_posts` 用于物理隔离写入候选人的博文。

## 2. 候选人博文爬取与调度集成 (Candidate Scrape & Scheduling)

- [x] 2.1 修改 `src/tools/weibo_scraper.py` 爬行服务，支持对单个微博 UID 爬取指定条数（如 3 条）的博文正文信息。
- [x] 2.2 修改 `src/tools/bilibili_scraper.py` 爬行服务，支持抓取指定 B 站 UID 的最新 3 条博文文本。
- [x] 2.3 在 `src/services/discovery_service.py` 中，设计并实现候选人博文的后台抓取调度。筛选 `status = 'pending' AND is_verified = 0` 且包含有效 UID 的候选人进行抓取，将抓取结果写入 `candidate_raw_posts` 表。

## 3. 文本核验智能体与流转逻辑实现 (Verification Agent & Lifecycle)

- [x] 3.1 在 `config/templates/` 下，创建核验智能体模版文件 `candidate_verify.jinja2`，提供精准的 Coser 行为判定规则与 Few-shot 约束。
- [x] 3.2 在 `src/models/schemas.py` 中，定义 `CandidateVerifyOutput` 的 Pydantic 强契约结构。
- [x] 3.3 在 `src/agents/event_agent.py` 中使用官方原生 `openai-agents` 实例化并实现核验智能体，支持读取候选人博文文本并进行评估。
- [x] 3.4 升级 `DiscoveryService.verify_pending_candidates` 的核心流转逻辑：对捞取出的待验证候选人，若有新抓取的 `candidate_raw_posts`，则调用核验智能体进行分类；判定通过时将 `is_verified` 置为 1，并在 `verify_reason` 写入 LLM 原因；判定不通过时将 `status` 直接标记为 `ignored`。

## 4. 命令行 CLI 列表展示增强 (CLI Display Enhancement)

- [x] 4.1 在 `src/views/terminal_renderer.py` 中，为候选人表格新增 `Verify Reason` 展现列，并对 `is_verified = 1` 的行使用绿色等高亮输出。
- [x] 4.2 适配 `src/main.py` 中的 `list-candidates` 终端命令，使其正确读取并展示核验理由字段。

## 5. 测试与验证 (Testing)

- [x] 5.1 编写单元测试或集成测试，模拟候选人博文抓取及 LLM 智能体分类评估，验证分类行为契合契约且结果符合预期。
- [x] 5.2 运行测试套件，确认候选人核验、博文物理隔离及 CLI 渲染功能全部通过验证，且不破坏存量功能。
