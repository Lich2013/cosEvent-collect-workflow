## Context

目前 B 站的 Coser 候选人发现依赖以下流程：
1. 爬取其他用户的动态，如果文本中含有 `@UserName`，就使用正则匹配出用户名。
2. 在验证阶段（`verify_pending_candidates`），使用这个用户名在 B 站搜索 API 进行模糊检索。
3. 利用 `BiliUidMatcher` 在搜索结果中进行昵称匹配 and 启发式评估，匹配出 `mid` 和签名。

这一流程存在两个关键局限：
- **无法直接解析 UID**：B 站 dynamics API 本身返回的数据中已经包含所提及用户的真实 UID。而我们把这些结构化数据丢弃，退化成了文本正则匹配，导致需要进行耗时的模糊搜索，并增加了反爬风控的概率。
- **验证不彻底（未进入主页）**：B 站搜索卡片中的签名（`usign`）极易被截断，且缺少官方认证等详细信息，限制了 ACG/Coser 关键词校验的置信度。

仿照微博的解析流程，我们将：
1. 从原始博文的数据源（gRPC 动态或 Playwright 拦截的 Web JSON）中，直接提取提及用户的 UID 与 Name，生成已绑定 UID 的候选人记录。
2. 为了能区分“已绑定但未核验 Coser 属性”的候选人，需为 `coser_candidates` 引入 `is_verified` 验证状态字段。
3. 在验证阶段，直接利用该 UID 进行“主页深度核验”：通过 Playwright 载入 `space.bilibili.com/{uid}` 并拦截 `wbi/acc/info` 接口，读取完整签名为验证提供支撑。

## Goals / Non-Goals

**Goals:**
- 在 gRPC 动态抓取中提取 mentioned UID 和名称，写入 `coser_candidates`。
- 新增 `is_verified` 数据库字段，将数据迁移封装在 `init_db` 中。
- 对未验证的 pending 候选人（`status = 'pending' AND is_verified = 0`）进行批量验证。
- 对于已绑定 `matched_bili_uid` 的候选人，直接使用 Playwright 访问其空间页面，拦截 `api.bilibili.com/x/space/wbi/acc/info` 以提取完整的 `sign`（签名）与官方认证。
- 对候选人验证实施双重检查：只要通过微博 Bio 校验 **或** B 站 Space 完整 Bio/认证校验，均视为通过。

**Non-Goals:**
- 不支持小红书（xhs）的直接 UID 解析和主页核验（暂处于 out-of-scope）。
- 不在爬虫拉取阶段进行实时的空间页面访问，避免拖慢爬虫吞吐和增加被 B 站风控的风险（必须在 `discover` 验证阶段异步核验）。

## Decisions

### 1. 数据库升级：引入 `is_verified` 字段
- **方案 A**: 在 `coser_candidates` 中加入 `is_verified INTEGER DEFAULT 0`。
- **方案 B**: 复用 `match_score` 进行判断（例如 `match_score > 0` 表示已验证）。
- **决定**: 采用 **方案 A**。因为 Weibo 来源的候选人在 B 站未匹配到时其 `match_score` 会被写入为 `0.0`，复用此字段极其混乱；新增 `is_verified` 字段不仅能完美区分 pre-bound 未核验状态，还能进行清晰的 SQL 过滤。
- **迁移实现**: 在 `src/models/db_models.py` 的 `init_db()` 中追加检测逻辑并执行 `ALTER TABLE coser_candidates ADD COLUMN is_verified INTEGER DEFAULT 0;`。

### 2. B站主页解析：Playwright 网络拦截
- **决定**: 创建 `BilibiliScraper.resolve_uids_batch(uids)` 方法。在已有的 Playwright 爬虫会话（`scrape_flow_handler`）下，依次在新 Page 中载入 `https://space.bilibili.com/{uid}`，并监听 `response` 拦截 `api.bilibili.com/x/space/wbi/acc/info` 接口的 JSON 响应，安全提取 `sign` 和 `official.title`。这能完全避开自行逆向 WBI 动态密钥签名的复杂性。

### 3. gRPC Mentions 提取
- **决定**: 修改 `_extract_text_and_author_from_item` 方法及 `fetch_bilibili_posts_grpc` 接口，除返回文本和原博外，还返回提取出的 `mentions` 数组：每一个元素为 `{"name": str, "uid": str}`。在 gRPC 解析中，遍历 `module_opus_summary.summary.text.nodes` (以及 `module_desc.desc`) 中包含 `link` 且链接含有 `space.bilibili.com`（或 LinkNode 判定为 mention 类型）的节点，获取其 `show_text` (用户名) 和 `biz_id` (用户 UID)。

## Risks / Trade-offs

- **[Risk]** B 站对于短时间内连续访问大量 `space.bilibili.com` 空间主页可能触发 WAF/滑块验证。
  - **Mitigation**: 限制单次验证的 `limit` 大小（默认 10-15 个），并在依次载入主页时加入 `1.5` 到 `3.0` 秒的随机休眠。
- **[Risk]** 数据库热升级如果在生产或并发下执行可能导致死锁。
  - **Mitigation**: SQLite 支持简单的 DDL 列追加，使用 `init_db()` 自带 of `PRAGMA table_info` 检测和 `auto_backup_db` 保障事务安全性。
