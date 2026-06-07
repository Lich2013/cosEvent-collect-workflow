## 1. 数据库结构迁移 (Database Migration)

- [x] 1.1 在 `src/models/db_models.py` 的 `init_db()` 中追加检测逻辑，并在 `coser_candidates` 表中自动热追加 `is_verified` 字段（`INTEGER DEFAULT 0`）。
- [x] 1.2 在 `src/services/db/candidate_repository.py` 的 `add_candidate` 和 `list_candidates` 模块中，对 `is_verified` 字段进行适配，使其在插入和查询时均能正确绑定和返回。

## 2. B 站动态抓取提及 UID 提取 (Mention Extraction)

- [x] 2.1 在 `src/tools/bilibili_scraper.py` 的 `_extract_text_and_author_from_item` 辅助函数中，对 gRPC 返回的 `module_opus_summary.summary.text.nodes` (以及 `module_desc.desc`) 进行深度解析，提取类型为链接/空间且包含 `biz_id` 的 Mention 信息，生成 `{"name": str, "uid": str}` 构成的提及列表。
- [x] 2.2 修改 `fetch_bilibili_posts_grpc` 接口及 `fetch_bilibili_posts` 方法，使其在解析动态时，为返回结果的字典中注入 `mentions` 字段。
- [x] 2.3 修改 `DiscoveryService.register_candidates_from_posts`，在提取候选人时优先读取 `mentions` 字段中的 pre-bound UID。若有 pre-bound B 站 UID，则在调用 `DBService.add_candidate` 时传入，初始验证状态记为 `is_verified = 0`。

## 3. B 站空间主页深度解析与核验流程 (Space Verification)

- [x] 3.1 在 `src/tools/bilibili_scraper.py` 中，新增 `resolve_uids_batch(self, uids: list[str]) -> dict[str, dict]` 异步方法。此方法在单个会话周期下，依次导航至 `https://space.bilibili.com/{uid}` 空间主页，通过拦截 `api.bilibili.com/x/space/wbi/acc/info` 接口，提取完整的 `sign`（签名）与 `official.title`（官方认证）。
- [x] 3.2 在 `src/services/discovery_service.py` 中修改 `verify_pending_candidates` 的选择查询：从 `coser_candidates` 检索所有 `status = 'pending' AND is_verified = 0` 的候选人进行验证。
- [x] 3.3 在 `verify_pending_candidates` 中优化验证流程：
    - 对无 UID 的候选人执行原有的 B 站搜索匹配流程，获取 `best_mid`。
    - 对所有持有 UID（含 pre-bound 及新匹配出）的候选人，调用 `BilibiliScraper.resolve_uids_batch` 进行空间主页信息拉取。
    - 执行 ACG 二次元关键词校验（结合微博 Bio 与 B 站 Bio 认证多路合并校验）。
    - 验证通过后，调用 `DBService.add_candidate` 时将 `is_verified` 更新写入为 `1`；验证不通过时将其 `status` 置为 `ignored`。

## 4. 测试与验证 (Testing)

- [x] 4.1 在 `tests/` 中编写针对 B 站 mention 提取及空间主页拦截核验的单元测试，模拟 gRPC nodes 数据和 Space `wbi/acc/info` 接口返回值。
- [x] 4.2 运行测试套件，确认新版 B 站解析逻辑能正常抓取和对齐，且不破坏已有的微博解析和历史分析功能。
