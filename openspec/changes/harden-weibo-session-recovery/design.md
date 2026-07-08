## Context

微博网页抓取使用 `BaseScraper` 统一管理 Playwright 会话：优先加载 `runtime/weibo/state.json`，文件不可用时才读取 `config/cookies/weibo_cookies.json` 注入种子 Cookie。当前失效判断主要依赖文件可读性和 cookie 的 `expires` 字段，无法覆盖服务端吊销、半登录、接口风控等业务级失效。

微博 `mymblog` 接口可能在 HTTP 200 的情况下返回无业务数据、登录异常或风控结构。现有微博抓取逻辑会把此类情况降级为空结果返回，使通用流程继续回写 `state.json` 和种子 Cookie，存在污染兜底凭证的风险。

## Goals / Non-Goals

**Goals:**

- 当种子 Cookie 文件比 `state.json` 更新时，优先使用种子 Cookie 重建运行态，确保用户手动刷新凭证立即生效。
- 对微博 `mymblog` 返回体做业务级健康判定，识别登录态失效、风控/验证和未知结构异常。
- 在微博业务级失效时，跳过本轮会话回写并使用种子 Cookie 自动重试一次。
- 只在会话健康确认后回写种子 Cookie，避免异常运行态污染冷启动源。
- 保持 CLI、数据库 schema、平台抓取返回契约不变。

**Non-Goals:**

- 不实现微博扫码登录或自动获取新 Cookie。
- 不改变 B站 gRPC 凭证刷新机制。
- 不把所有平台统一改造成复杂认证状态机；本次只补齐通用安全回写能力和微博专用健康判定。

## Decisions

1. **以种子 Cookie 修改时间作为用户意图信号**

   当 `config/cookies/weibo_cookies.json` 的 `mtime` 晚于 `runtime/weibo/state.json` 时，系统 SHALL 旁路旧 `state.json`，直接使用种子 Cookie 冷启动。这样用户更新 Cookie 后无需手动删除 state 文件。

   备选方案是增加 CLI 参数强制刷新会话，但这会增加用户操作负担，也不能自动覆盖定时任务场景。

2. **把微博 `mymblog` 解析结果分类，而不是只返回列表**

   微博抓取内部应把接口响应归类为 `healthy`、`auth_invalid`、`rate_limited`、`empty_timeline`、`unknown_schema`。其中 `healthy` 和确认正常的 `empty_timeline` 允许正常回写；`auth_invalid`、`rate_limited`、`unknown_schema` 必须阻止种子 Cookie 回写。

   备选方案是在通用基类里根据返回列表为空判断失败，但真实用户可能确实没有近期博文，不能简单等同为登录失败。

3. **使用可控异常或会话结果标记驱动回写策略**

   微博检测到业务级会话失效时，应向 `scrape_flow_handler` 传递“不要回写”的信号。实现可采用专用异常（例如 `SessionHealthError`）或返回元数据；为了不改变外部 `fetch_weibo_posts()` 返回契约，优先采用内部异常加一次重试的方式。

4. **`state.json` 与种子 Cookie 使用不同回写门槛**

   `state.json` 是运行态缓存，只在本轮会话健康时更新。种子 Cookie 是可信冷启动源，必须通过更严格的健康门槛后才覆盖。对于微博，至少需要确认关键登录 Cookie 存在且 `mymblog` 响应属于健康分类。

5. **失败自愈只重试一次**

   遇到 `state.json` 业务级失效后，系统删除或旁路旧 state，用种子 Cookie 重试一次。若重试仍失败，返回空结果并记录日志，但不继续循环，避免定时任务卡死和触发更高频风控。

## Risks / Trade-offs

- **风险：正常空微博被误判为异常** → 必须基于响应结构判断，只有明确 `ok` 成功且 `data.list` 是列表时才视作正常空列表。
- **风险：不同微博异常结构变化频繁** → 记录响应顶层字段、`ok`、`msg` 摘要，不记录 Cookie 值，便于后续补充分支。
- **风险：种子 Cookie 不再频繁覆盖，可能变旧** → 只有健康会话才覆盖；用户仍可手动更新种子 Cookie，且 `mtime` 规则会立即生效。
- **风险：删除 `state.json` 后种子 Cookie 也失效** → 重试失败时不覆盖种子文件，并输出明确日志提示需要人工刷新 Cookie。
