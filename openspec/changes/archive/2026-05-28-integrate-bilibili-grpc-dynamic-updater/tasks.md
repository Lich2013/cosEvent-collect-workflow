## 1. 配置与初始化

- [x] 1.1 在 `config/settings.yaml` 中新增 B 站 gRPC 凭证配置（如 `bilibili_grpc_access_token` 和 `bilibili_grpc_mid`），并在 `src/config.py` 中解析这两个配置，支持读取 `.env` 中的 `BILIBILI_ACCESS_TOKEN` 与 `BILIBILI_MID` 进行环境变量注入。

## 2. B站 gRPC 抓取与降级机制实现

- [x] 2.1 在 `src/tools/bilibili_scraper.py` 中导入 `scratch/grpc_gen` 中已编译的 gRPC protobuf 相关服务存根模块，在 `BilibiliScraper` 启动时自适应判断是否已提供合规凭证。
- [x] 2.2 在 `BilibiliScraper` 中实现辅助时间解析方法 `_parse_bili_ptime`：支持识别 `ptime_label_text` 中的“编辑于”字样，正则匹配处理绝对时间（如“2026年5月25日 04:05”）与相对时间，缺少年份时基于当前系统年份进行推算，若所得时间在未来则自动减去 1 年，最终统一格式化为标准北京时间格式。
- [x] 2.3 在 `BilibiliScraper` 中编写核心 gRPC 空间动态拉取及富文本解析流：成功提取动态 ID，遍历富文本摘要或 legacy desc 字段合并文本内容，若为转发则将原作者和原动态内容与自身附言安全拼接；字典列表中必须输出 `"is_grpc": True` 及 `"is_edited": True/False` 自定义标记。
- [x] 2.4 在 `BilibiliScraper.fetch_bilibili_posts` 中整合 gRPC 主流程，使用 `try-except grpc.RpcError` 健壮性结构捕获通信故障、风控与凭证异常，输出黄色 `WARNING` 并立刻静默降级熔断至 Playwright 网页抓取流，保障整个工作流正常运行。

## 3. 数据库物理版本冲突检测与去重升级

- [x] 3.1 修改 `src/services/db/coser_repository.py` 的 `save_raw_posts` 方法：当收到 `platform == "bilibili"` 且包含 `"is_grpc": True` 自定义标记 of 博文时，查询当前最新已存版本记录。
- [x] 3.2 若满足物理编辑 `is_edited == True` 且其物理编辑时间与库中最新版本不同，则虚拟递增 `edit_count = stored_edit_count + 1`，并将 `post_id` 自动合成拼接后缀 `#v{edit_count}` 录入全新版本行；若时间一致则直接跳过去重；若库中完全无记录则按 base `post_id` 首次插入。
- [x] 3.3 保证网页无凭证抓取 B 站动态时（`is_grpc` 为 False 或不存在），依然能自适应回退到基于文本内容的变更对比合成版本机制，保证向下兼容。

## 4. 测试与验证

- [x] 4.1 编写单元测试或集成测试，全量覆盖 `_parse_bili_ptime` 方法，对各种含“编辑于”字样、相对时间、缺少年份绝对时间的输入进行验证，确保年份推算逻辑无误。
- [x] 4.2 结合真实的 UID 模拟运行抓取、物理版本去重保存以及增量提炼分析流，验证端到端逻辑的健壮性。
