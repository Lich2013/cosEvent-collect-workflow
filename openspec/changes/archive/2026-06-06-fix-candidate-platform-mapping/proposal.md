## Why

在自动发现 Coser 候选人时，系统未能正确记录候选人的来源社交平台。例如，即使提及来自微博（Weibo），候选人记录的 `platform` 字段也被硬编码记为了 `bilibili`。这导致审查候选人列表和后续的数据同步报告中来源信息错乱，难以准确定位候选人的最初提及来源。

## What Changes

- 修改 `main.py` 中的 `discover` 命令，在查询 `raw_posts` 时额外查询 `platform` 字段。
- 修改 `DiscoveryService.register_candidates_from_posts`，在提取 mentions 时保留原始博文的 `platform` 信息，并将其传给 `add_candidate`。
- 修改 `DiscoveryService.verify_pending_candidates`，在加载待验证候选人时查询其原始 `platform` 属性，并在更新候选人信息调用 `add_candidate` 时传入，防止被误覆写为 `"bilibili"`。

## Capabilities

### New Capabilities

- `coser-candidates`: 自动发现与管理提及的 Coser 候选人，并在数据库中记录对应的提及平台 (platform) 及原始链接引用。

### Modified Capabilities

无

## Impact

- 影响模块：`src/main.py`、`src/services/discovery_service.py`。
- 不影响任何对外 API、gRPC 协议或外部依赖。
