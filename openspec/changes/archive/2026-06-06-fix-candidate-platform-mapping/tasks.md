## 1. 数据库查询更新 (main.py)

- [x] 1.1 修改 `main.py` 的 `discover_command` 查询，在 `SELECT` 语句中新增 `platform` 字段，并将其正确保存至 `posts` 列表。

## 2. 候选人发现服务逻辑修复 (discovery_service.py)

- [x] 2.1 修改 `DiscoveryService.register_candidates_from_posts`，在提取 mentions 的临时列表 `all_mentions` 中添加 `platform` 属性。
- [x] 2.2 修改 `DiscoveryService.register_candidates_from_posts` 中插入候选人记录时调用 `DBService.add_candidate` 的 platform 参数，改用 `item["platform"]`。
- [x] 2.3 修改 `DiscoveryService.verify_pending_candidates`，在 `SELECT` 语句中加入 `platform` 字段以提取每个待验证候选人的原始 platform，并更新 candidates_to_verify。
- [x] 2.4 修改 `DiscoveryService.verify_pending_candidates` 在对齐成功调用 `DBService.add_candidate` 时的 platform 参数，改用 `cand["platform"]`。

## 3. 测试与验证

- [x] 3.1 运行 `test_discovery.py` 和 `test_bili_uid_matcher.py` 确保单元测试正常通过。
- [x] 3.2 运行独立候选人分析命令行 `uv run python src/main.py coser discover`，验证微博或B站提及的候选人记录在 `coser_candidates` 中 platform 是否正确。
