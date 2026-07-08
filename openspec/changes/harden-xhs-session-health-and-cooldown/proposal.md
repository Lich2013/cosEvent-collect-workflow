## Why

小红书当前已降级为 Bio-only 抓取以降低风控面，但仍缺少对 `otherinfo` 业务响应、登录态失效、验证码/滑块、用户不可访问等状态的明确分类。现有逻辑在部分异常场景下可能把异常会话当作普通空结果处理并回写本地状态，同时调度层无法基于失败类型进行平台冷却，容易扩大同一轮小红书失败面。

## What Changes

- 增加小红书 `otherinfo` 响应健康分类，区分 `healthy`、`empty_bio`、`auth_invalid`、`rate_limited`、`not_found_or_private`、`unknown_schema`。
- 增强小红书页面状态检测，识别登录跳转、验证码/滑块、安全验证、访问频繁、用户不存在或私密等页面状态。
- 收紧小红书会话回写策略：风控、登录失效、未知结构等非健康状态禁止覆盖 `runtime/xhs/state.json` 和 `config/cookies/xhs_cookies.json`。
- 增加小红书关键 Cookie 校验，确保健康回写前 `web_session`、`a1`、`websectiga`、`xsecappid` 等关键项存在且非空。
- 引入小红书平台级冷却机制：检测到风控/验证后，本轮后续小红书抓取应暂停或延后，并记录冷却原因。
- 扩展抓取调度状态，记录 `last_scrape_status`、`last_scrape_error`、`next_retry_after`，使网络超时、空 Bio、登录失效和风控可以采用不同重试策略。
- 优化小红书批次行为：支持在同一批次内复用 Browser/Context，配合更自然的 jitter、长暂停和指数退避，减少 Playwright 冷启动和高频访问特征。
- 约束小红书接口访问上下文：优先通过页面导航让前端自然触发 `otherinfo`，避免脱离页面上下文直接请求核心接口；如必须兜底请求，`Referer`、`Origin`、`User-Agent` 与 Cookie 必须和当前浏览器上下文一致。
- 保持小红书 Bio-only 范围，不恢复笔记列表抓取，不实现验证码/滑块绕过。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `content-scraping`: 强化小红书会话健康判定、反风控隔离、调度冷却和批次抓取行为契约。

## Impact

- 影响代码：`src/tools/xhs_scraper.py`、`src/tools/playwright_base.py`、`src/services/workflow_orchestrator.py`、`src/services/db/coser_repository.py`、数据库初始化/迁移逻辑以及相关测试。
- 影响数据库：可能为抓取状态增加 `last_scrape_status`、`last_scrape_error`、`next_retry_after` 字段，或在现有调度状态模型中恢复/扩展平台级状态表。
- 不新增外部依赖，不改变小红书只抓 Bio 的业务范围。
- 行为变化：小红书风控/登录异常不再被视作普通空结果；平台风控后会触发冷却，减少同一轮持续请求。
