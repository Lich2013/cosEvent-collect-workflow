## Context

小红书当前采用 Bio-only 抓取：访问用户主页，优先拦截 `api/sns/web/v1/user/otherinfo`，失败后通过 `.user-desc` DOM 兜底，仅生成 `bio_{uid}` 虚拟动态。该策略已经显著降低了风控面，但现有实现缺少业务级状态分类，无法可靠区分空简介、登录态失效、风控验证、用户不存在、接口改版等状态。

近期微博会话恢复加固已经引入会话健康标记和安全回写控制，但小红书仍默认被视为健康会话。若小红书进入半登录或风控页面且没有触发 `XhsRateLimitError`，系统可能错误回写 `state.json` 或种子 Cookie。调度层也只有单一 `last_scraped_at`，无法根据失败类型决定冷却或重试。

## Goals / Non-Goals

**Goals:**

- 对小红书 `otherinfo` 响应和页面状态做业务级健康分类。
- 在风控、登录失效、未知结构等非健康状态下阻止会话与种子 Cookie 回写。
- 为小红书建立平台级冷却和失败类型记录，减少同一轮持续触发风控。
- 保持 Bio-only 范围，不恢复笔记列表抓取。
- 优化批次抓取行为，减少 Playwright 冷启动和固定节奏访问特征。

**Non-Goals:**

- 不绕过验证码、滑块、安全验证或平台访问控制。
- 不引入非官方签名破解、接口逆向或代理池。
- 不改变事件分析、数据库原始博文格式和 `bio_{uid}` 虚拟动态契约。

## Decisions

1. **小红书引入专用健康分类器**

   在 `XhsScraper` 中抽取 `classify_otherinfo_response` 和 `classify_page_state`，分类为 `healthy`、`empty_bio`、`auth_invalid`、`rate_limited`、`not_found_or_private`、`unknown_schema`。`healthy` 和 `empty_bio` 是可安全结束状态；其余状态必须阻止会话回写。

   备选方案是继续依赖 “API 失败 + DOM 失败” 判定风控，但这会漏掉 HTTP 200 异常 JSON 和登录/验证页面。

2. **使用通用会话健康机制隔离污染状态**

   小红书非健康状态应调用 `mark_session_unhealthy` 或抛出专用健康异常，使 `BaseScraper` 跳过 `state.json` 与种子 Cookie 回写。对 `rate_limited` 状态不进行自动重试，避免扩大访问压力。

   备选方案是直接返回空列表，但这会丢失失败类型，并可能触发健康回写。

3. **关键 Cookie 校验采用平台配置化规则**

   将 `_has_required_cookies` 从微博硬编码扩展为平台规则。小红书健康回写前至少校验 `web_session`、`a1`、`websectiga`、`xsecappid` 存在且非空；`id_token` 作为可观测字段记录但暂不强制必需，避免不同登录态差异导致误伤。

4. **调度状态从单一时间戳升级为可解释状态**

   在现有调度模型中增加或恢复平台级状态字段：`last_scrape_status`、`last_scrape_error`、`next_retry_after`。`list_active_cosers_by_schedule` 必须过滤仍在冷却期的记录。小红书风控应设置长冷却；网络超时可设置短冷却；空 Bio 和健康成功正常轮转。

   备选方案是继续只更新 `last_scraped_at`，但无法区分“正常空简介”和“风控失败”。

5. **批次行为优化分阶段落地**

   第一阶段先做分类、隔离和冷却；第二阶段将小红书批次改为复用同一个 Browser/Context，并引入更宽的 jitter、长暂停和指数退避。这样降低一次性改动风险，同时把行为优化纳入任务清单。

6. **Playwright 访问行为以一致性和低频为核心**

   小红书抓取应优先使用持久化浏览器上下文、稳定的 User-Agent/viewport/locale/timezone/geolocation 权限配置、页面预热、自然停留时间、有限滚动和单账号页面内等待，减少“频繁冷启动 + 固定节奏 + 立即关闭”的自动化特征。遇到登录页、验证码、滑块或安全验证时必须停止并冷却，不尝试绕过验证。

   备选方案是加入更强的 stealth/绕过插件或模拟验证流程，但这会提升维护风险和合规风险，不纳入本变更。

7. **接口请求必须保持自然页面上下文**

   小红书核心接口（尤其 `otherinfo`）应优先由真实页面导航后的前端 JS 自然触发，使 Referer、Origin、Cookie、User-Agent、路由状态和页面执行环境保持一致。系统不应使用 Python HTTP 客户端直接请求小红书核心接口；如果未来必须使用 Playwright request 作为诊断或兜底，请求头中的 Referer/Origin/User-Agent/Cookie 必须与当前 Page/Context 对齐，并且不得绕过登录、验证或访问控制。

   备选方案是在底层手动拼装 Referer/Origin 直接打接口，但这会制造与页面环境不一致的请求链路，增加风控风险。

## Risks / Trade-offs

- **[Risk] 误把空 Bio 判定为异常** → 只有用户资料结构明确有效且 `desc` 为空时才归类为 `empty_bio`，允许健康结束。
- **[Risk] 小红书接口字段变化导致分类过严** → 对未知结构记录顶层字段、`code`、`success`、`msg` 摘要，不记录 Cookie 值，便于后续调整。
- **[Risk] 冷却导致恢复变慢** → 按失败类型设置不同冷却，`auth_invalid` 和 `rate_limited` 长冷却，网络超时短冷却，健康空 Bio 正常轮转。
- **[Risk] 批次复用 Context 失败影响整批** → 批次复用应保留单账号异常隔离；遇到平台级风控时中止后续小红书任务，避免整批继续冲击。
- **[Risk] 数据库迁移影响既有调度** → 使用向后兼容的新增字段或平台状态表迁移，旧数据默认状态为空且可被正常调度。
- **[Risk] 过度模拟交互增加复杂度** → 仅实现少量确定性可测的访问节奏与上下文一致性控制，不实现复杂的人类行为生成。
- **[Risk] 手动接口请求产生上下文不一致** → 默认禁止脱离页面上下文请求核心接口；兜底请求必须复用当前 Playwright 上下文并显式对齐 Referer、Origin、User-Agent 与 Cookie。
