## Context

目前，本系统的 Playwright 爬虫会将运行期最新捕获的 Cookie 写入 `runtime/{platform}/state.json`，但未同步更新至配置种子 `config/cookies/{platform}_cookies.json`。导致当环境初始化或缓存被隔离删除时，种子文件仍使用陈旧的数据。

为了在运行时持久化会话自动增量滚动成果，需要在 `scrape_flow_handler` 中实现种子 Cookie 文件的自适应同步回写。

## Goals / Non-Goals

**Goals:**
- 实现种子 Cookie 文件自适应格式检测（Playwright JSON 数组、JSON 包装单行字符串、纯文本字符串）。
- 在爬取成功的持久化节点，自动抽取最新 Cookie 同步覆写至种子文件。

**Non-Goals:**
- 引入第三方复杂的 Cookie 解密/验证逻辑。

## Decisions

### 决策一：自适应回写格式兼容
- **方案选择**：
  读取原本的种子文件，解析出它是三种可能格式中的哪一种，并以相同的格式将最新的 Cookie 序列化后回写。
  - **格式 A（Bilibili）**：标准 JSON 列表 `[{'name': '...', 'value': '...'}, ...]` -> 用 `json.dumps(cookies)` 写入。
  - **格式 B（Weibo, XHS）**：双引号包裹的 JSON 字符串 `"name1=value1; name2=value2"` -> 将最新 cookies 拼装后使用 `json.dumps(cookie_string)` 写入。
  - **格式 C（其他）**：纯文本字符串 `name1=value1; name2=value2` -> 将最新 cookies 拼装为明文字符串直接写入。
- **考量**：这样可以零侵入地兼容目前系统已存的所有 Cookie 配置风格。

### 决策二：调用触发时机
- **方案选择**：在 `playwright_base.py` 的 `scrape_flow_handler` 成功调用 `context.storage_state()` 之后，通过 `await context.cookies()` 获取最新数据，并执行同步回写。
- **考量**：这保证了只有在爬取成功且会话正常时，才会更新种子 Cookie，避免异常或受污染的状态回写到种子中。

## Risks / Trade-offs

- **[Risk]** 在并发抓取下，多个进程可能会同时尝试回写同一个平台的种子文件。
  - **Mitigation**：目前系统是一个平台顺序进行单进程抓取的，各平台之间物理隔离，无并发写冲突风险。
