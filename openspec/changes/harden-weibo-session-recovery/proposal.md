## Why

当前微博抓取只按 `state.json` 文件可读性和 cookie 显式过期时间判断会话是否可用，无法识别“文件有效但微博接口业务级失效”的状态。用户手动更新种子 Cookie 后，旧 `state.json` 仍会优先被使用；同时异常或半登录状态下的运行期 Cookie 可能反向覆盖种子文件，导致冷启动兜底源被污染。

## What Changes

- 增加微博会话健康判定：对 `mymblog` 返回体进行业务结构检查，区分正常空列表、登录态失效、风控/验证、未知结构异常。
- 增加微博会话自愈：当 `state.json` 文件级有效但业务级失效时，跳过本轮会话回写，删除或旁路旧 `state.json`，使用种子 Cookie 冷启动重试一次。
- 增加种子 Cookie 新鲜度优先级：当 `config/cookies/weibo_cookies.json` 修改时间晚于 `runtime/weibo/state.json` 时，视为用户手动刷新凭证，必须优先使用种子 Cookie 重建运行态。
- 收紧 Cookie 回写策略：`state.json` 可在健康抓取后滚动更新；静态种子 Cookie 文件仅在明确验证会话健康后才允许覆盖，避免匿名态、风控态、半失效态污染兜底源。
- 增加可观测日志：记录会话来源、健康判定结果、自愈重试、跳过回写原因，便于定位微博登录态问题。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `content-scraping`: 强化 Playwright 抓取会话恢复、微博业务级登录态检测、种子 Cookie 优先级和安全回写契约。

## Impact

- 影响代码：`src/tools/playwright_base.py`、`src/tools/weibo_scraper.py` 及相关测试。
- 影响运行文件：`runtime/weibo/state.json`、`config/cookies/weibo_cookies.json` 的读取优先级与回写时机。
- 不引入新外部依赖，不改变 CLI 参数和数据库 schema。
- 行为变化：微博接口返回异常结构时不再被简单视为空结果；异常会话不再无条件覆盖 `state.json` 和种子 Cookie。
