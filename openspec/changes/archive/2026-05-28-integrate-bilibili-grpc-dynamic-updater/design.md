## Context

当前 B 站动态的抓取与二次编辑更新机制采用本地自适应模拟比对，无法获知真实的编辑次数，且无法获取精准的物理编辑时间（目前只能重锚为当前抓取时间）。
在已完成的 gRPC 原型验证中，我们发现 B 站第一方移动端 gRPC（`DynSpace`）服务接口在提供有效 `access_token` 与 `mid` 凭证进行鉴权后，可以直接从 `module_author.ptime_label_text` 中解析出真实的物理编辑时间标签（例如 `"编辑于 2026年5月25日 04:05"`），并通过第一方长 ID 实现真正的动态版本控制。
本设计旨在引入 B 站第一方 gRPC 动态抓取器，并对齐微博的物理版本化（`post_id#v{edit_count}`）增量去重保存机制，提升活动更新的时效性与精准度。

## Goals / Non-Goals

**Goals:**
- **gRPC 优先与降级机制**：当配置文件或环境变量中存在有效的 B 站移动端凭证（`access_token` 和 `mid`）时，`BilibiliScraper` 必须优先采用 gRPC 通信抓取目标用户的空间动态；在凭证缺失、失效或网络超时等异常情况下，自动且零崩溃降级为 Playwright 网页拦截抓取。
- **高精度时间解析与正则匹配**：设计健壮的正则解析器，能够匹配并处理 `ptime_label_text` 字段中的各种时间格式（如“编辑于 2026年5月25日 04:05”、“编辑于 5-25”等），自动补齐年份并统一格式化为标准北京时间格式 `YYYY-MM-DD HH:MM:SS`。
- **物理版本化去重对齐**：修改数据库 `CoserRepository.save_raw_posts`，引入针对 B 站 gRPC 抓取结果的冲突版本判定。基于解析到的物理编辑时间与已存最新版本进行对比，若编辑时间不同，自动合成版本号 `post_id#v{edit_count}` 并作为新版数据增量插入，实现与微博完全一致的物理版本去重流程。
- **可观测性无缝结合**：当系统正常运行时，gRPC 内部逻辑及外部调用能被 Langfuse 可观测性链路追踪和本地日志架构自动捕获。

**Non-Goals:**
- 抓取非动态类型的 B 站数据，如视频投稿、专栏文字等。
- 实现 B 站账号登录态/凭证的自动刷新机制（凭证长期有效，失效后采用人工干预或配置更新）。
- 更改小红书或微博现有的非 B 站相关抓取实现。

## Decisions

### 1. 凭证配置与 gRPC 启动检测
- **决策**：将 B 站 gRPC 第一方凭证配置在 `config/settings.yaml` 中，并支持通过 `.env` 环境变量进行覆盖。
- **配置项**：
  - `bilibili_grpc_access_token` (对应 `.env` 中的 `BILIBILI_ACCESS_TOKEN`)
  - `bilibili_grpc_mid` (对应 `.env` 中的 `BILIBILI_MID`)
- **逻辑**：在 `BilibiliScraper` 的 `fetch_bilibili_posts` 方法中，首先读取配置。若 `access_token` 和 `mid` 均存在且非空，则进入 gRPC 抓取流，否则打印 `WARNING` 并直接降级为 Playwright 抓取。

### 2. 多重时间格式的正则解析与年份补齐算法
- **决策**：在 `BilibiliScraper` 中引入专门的静态辅助方法 `_parse_bili_ptime` 用于解析 `module_author.ptime_label_text` 字段。
- **时间正则匹配与逻辑**：
  - **编辑状态识别**：若字符串匹配 `r"编辑于\s*(.*)"`，则标记 `is_edited = True` 并对剩余部分进行解析；若不包含，则标记 `is_edited = False`。
  - **绝对时间解析**：
    - 格式如 `2026年5月25日 04:05`：直接提取年月日时分，转换为 `2026-05-25 04:05:00`。
    - 格式如 `5月25日 04:05` 或 `05-25` 等缺少年份的格式：使用系统当前参考时间（或发表时刻）的年份进行智能推算补齐。若补齐后的日期时间晚于当前系统时间，则自动向前推算一年（`year - 1`）以杜绝年份幻觉。
    - 格式如 `昨天 04:05` 或 `前天 12:00` 或 `小时前` 等相对时间：基于当前抓取时刻的北京时间进行高精度偏移推导。

### 3. 数据层物理版本自适应递增机制
- **决策**：在 `CoserRepository.save_raw_posts` 中，由于 Scraper 本身在 gRPC 状态下是无状态的（无法独立获知已存版本号），版本递增和物理版本行写入必须完全交给数据库事务来控制。
- **协议契约设计**：
  - gRPC 抓取器返回的动态数据字典中包含自定义标记：`"is_grpc": True`，`"is_edited": True/False`。
  - `save_raw_posts` 逻辑变更：
    - 如果 `platform == "bilibili"` 且包含 `"is_grpc": True` 标记：
      - 查询 `raw_posts` 中对应的 `base_post_id`（去掉 `#v` 的 ID）的最新已存记录。
      - 如果有历史记录且 `is_edited` 为 `True`：
        - 比较传入的 `published_at`（高精度物理编辑时间）与已存最新记录的 `published_at`。
        - 若时间不同（代表发生新编辑），则 `edit_count = stored_edit_count + 1`，生成 `post_id = f"{base_post_id}#v{edit_count}"` 并执行 `INSERT` 插入全新版本行。
        - 若时间相同（代表已存过当前编辑版本），则直接跳过，不进行任何写入。
      - 如果有历史记录且 `is_edited` 为 `False`：
        - 说明是最原始的发布版，且库中已存有记录，直接跳过。
      - 如果库中没有历史记录（全新博文）：
        - 直接以 base `post_id`（`edit_count = 0`）执行首次 `INSERT` 插入。
    - 如果是 Playwright 网页抓取返回的数据（`is_grpc` 为 `False` 或不存在）：
      - 维持原有的“自适应内容变动合成版本控制”逻辑以保证向后兼容性。

### 4. 健壮的 RpcError 错误拦截与熔断降级
- **决策**：在 gRPC 执行体中使用严格的 `try-except grpc.RpcError` 捕获所有传输层及鉴权故障。
- **处理方式**：当捕获到 Rpc 异常时，系统输出黄色 `WARNING` 并输出异常明细（如授权失效 `-101` 或风控指纹错误 `-352`），随后执行 `return await self._scrape_bili_playwright_fallback(context, uid, limit)`，静默转入 Playwright 模式，保障抓取流程不受阻断。

## Risks / Trade-offs

- **[Risk 1] B站 gRPC 服务由于反爬或风控返回错误（如 -352 指纹校验）**
  - **Mitigation**：通过传入真实合法的移动端 `access_token`、`mid`、`buvid` 进行授权请求，可完美绕过指纹安全限制。此外，系统设置了秒级熔断，一旦 gRPC 报错即立刻降级为 Playwright 无头浏览器模式。
- **[Risk 2] 相对时间（如“昨天”、“1小时前”）在零点边界时可能产生的解析偏差**
  - **Mitigation**：在解析器中以当前精确的北京时间（GMT+8）作为计算偏移的基准，并将抓取运行时间记录在案，将时间误差降到分钟级，杜绝跨天边界计算引发的日期漂移风险。
