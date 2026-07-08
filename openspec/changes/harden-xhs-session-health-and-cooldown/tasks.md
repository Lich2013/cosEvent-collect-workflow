## 1. 小红书健康分类与安全回写

- [x] 1.1 在 `XhsScraper` 中抽取 `otherinfo` 响应分类函数，覆盖 `healthy`、`empty_bio`、`auth_invalid`、`rate_limited`、`not_found_or_private`、`unknown_schema`。
- [x] 1.2 增加页面状态检测函数，识别登录页、验证码、滑块、安全验证、访问频繁、用户不存在和私密状态。
- [x] 1.3 调整 `fetch_xhs_posts`，使非健康状态通过会话健康机制阻止 `state.json` 和种子 Cookie 回写。
- [x] 1.4 扩展 `BaseScraper` 平台关键 Cookie 校验规则，小红书健康回写前校验 `web_session`、`a1`、`websectiga`、`xsecappid`。
- [x] 1.5 确保 `empty_bio` 不生成虚拟动态但被视作健康结束，不污染错误日志。

## 2. 调度状态与平台冷却

- [x] 2.1 为平台抓取状态增加 `last_scrape_status`、`last_scrape_error`、`next_retry_after` 的存储与数据库迁移。
- [x] 2.2 扩展 `DBService`/`CoserRepository` 的调度查询，过滤 `next_retry_after` 未到期的小红书账号。
- [x] 2.3 扩展时间戳更新接口，使调度层可记录成功、空 Bio、超时、登录失效、风控、未知结构等状态。
- [x] 2.4 在 `WorkflowOrchestrator.run_scrape` 中实现小红书 `rate_limited` 后的平台级冷却，并跳过当前运行周期后续小红书账号。
- [x] 2.5 定义不同失败类型的默认冷却时长：超时短冷却，未知结构中冷却，登录失效和风控长冷却。

## 3. Playwright 真实访问行为

- [x] 3.1 为小红书批次抓取增加 Browser/Context 复用路径，减少每个账号单独冷启动。
- [x] 3.2 为小红书上下文配置稳定的 User-Agent、viewport、locale、timezone 和必要权限，保持单批次指纹一致。
- [x] 3.3 增加轻量预热步骤，在目标用户主页前访问小红书首页或安全资料页。
- [x] 3.4 增加可配置随机等待、周期性长暂停和错误后的指数退避。
- [x] 3.5 增加有限滚动和页面停留逻辑，但检测到验证/风控页面时立即停止交互并进入冷却。
- [x] 3.6 约束小红书核心接口访问必须由页面自然触发；若实现 Playwright request 兜底，必须复用当前上下文并对齐 Referer、Origin、User-Agent 与 Cookie，禁止 Python HTTP 客户端直接请求。

## 4. 测试与回归

- [x] 4.1 添加小红书 `otherinfo` 健康分类单元测试，覆盖所有分类状态。
- [x] 4.2 添加小红书页面状态检测测试，覆盖登录页、验证码/滑块、访问频繁、用户不存在和正常页面。
- [x] 4.3 添加非健康状态禁止 `state.json` 和种子 Cookie 回写的测试。
- [x] 4.4 添加小红书关键 Cookie 缺失时保护种子文件的测试。
- [x] 4.5 添加调度冷却测试，验证冷却期账号不进入队列，`rate_limited` 后本轮后续小红书任务被跳过。
- [x] 4.6 添加小红书批次复用和 jitter/退避测试，确保不启动真实浏览器即可验证调用顺序。
- [x] 4.7 添加 Referer/Origin 上下文一致性测试，验证默认路径等待页面自然触发 `otherinfo`，兜底请求不使用 Python HTTP 客户端。
- [x] 4.8 回归运行 `tests/test_coser_bio_scraping.py`、`tests/test_fine_grained_scrape.py`、`tests/test_sliding_window.py` 及相关 `xhs` 数据库存储测试。
