## Why

当前 B 站动态的抓取与二次编辑更新机制采用本地自适应模拟比对，无法获知真实的编辑次数，且无法获取精准的物理编辑时间（目前只能重锚为当前抓取时间）。
通过引入 B 站第一方移动端 gRPC（`DynSpace`）服务接口，利用已获取的长期有效第一方移动端 `access_token` 与 `mid` 凭证进行鉴权，可以直接在动态列表中提取真实的物理编辑时间标签（如“编辑于 2026年5月25日 04:05”）以及真正的动态 ID，从而将 B 站动态的编辑更新机制与微博对齐，实现精准的版本追踪与增量分析。

## What Changes

- **新增 B 站第一方 gRPC 动态抓取器**：整合已编译的 gRPC Protobuf 模块，支持通过安全 gRPC 信道（`grpc.biliapi.net:443`）请求目标 UP 主的空间动态列表。
- **动态提取与解析机制升级**：
  - 从 `extend.dyn_id_str` 提取真实的动态 ID。
  - 从 `module_opus_summary` 遍历节点提取完整的动态正文。
  - 从 `module_author.ptime_label_text` 解析时间，若包含“编辑于”字样，则正则提取其物理编辑时间并格式化为标准北京时间。
- **数据库入库去重逻辑对齐（物理版本化）**：修改 `coser_repository.py` 中的 `save_raw_posts` 方法，移除 B 站的本地自适应文本比对逻辑，改为与微博一致的物理版本去重逻辑（根据 `post_id#v{edit_count}` 的存在性进行增量插入，物理编辑时间作为 `published_at`）。

## Capabilities

### New Capabilities
- `bilibili-grpc-scraper`: 支持通过 B 站第一方客户端 gRPC 协议，结合有效 `access_token` 凭证抓取特定用户空间动态列表并精准解析二次编辑状态与时间的能力。

### Modified Capabilities
<!-- 无需求层面的变更 -->

## Impact

- `src/tools/bilibili_scraper.py`：新增 gRPC 动态列表拉取模块，当配置中存在有效 `access_token` 时优先通过 gRPC 抓取，否则自动降级为 Playwright 网页拦截抓取。
- `src/services/db/coser_repository.py`：修改 `save_raw_posts` 方法，使 B 站动态在存入数据库时支持真正的物理版本号比对与增量插入。
