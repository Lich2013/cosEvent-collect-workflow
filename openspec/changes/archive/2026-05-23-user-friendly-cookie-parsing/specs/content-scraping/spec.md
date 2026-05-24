## MODIFIED Requirements

### Requirement: Playwright 静态 JSON 种子会话恢复、更新与 Git 屏蔽
系统**必须且 SHALL** 实现通用的 `BaseScraper` 模块。当启动爬虫任务时，系统**必须且 SHALL**：
1. 优先检测本地是否存在 `runtime/{platform}/state.json` 文件；
2. 如果存在，启动 Headless 模式并使用 `storage_state` 还原完整的会话状态（Cookies + LocalStorage）；
3. 如果不存在或损坏，系统**必须且 SHALL** 能够从用户提供的 `config/cookies/{platform}_cookies.json` 种子文件中自适应解析加载 Cookie：
   - 如果文件内容是标准的 Playwright JSON 数组格式，直接解析加载为 Cookie 列表；
   - 如果文件内容是单行文本字符串（支持直接复制粘贴自浏览器 DevTools 的 raw Cookie 键值对，例如 `"SUB=xxx; _s_tentry=yyy"`），系统**必须且 SHALL** 能够在后台自动对其分号与等号切割，并根据当前平台自动注入默认的 Domain（如 `.weibo.com`、`.bilibili.com`、`.xiaohongshu.com`）和 Path（`/`），转换构造成合规的字典列表载入，自动生成并保存完整的 storage state 到 `state.json` 文件中；
4. 每次数据爬取完毕后，**必须且 SHALL** 调用 Playwright 原生 `context.storage_state` 将最新 Cookie 及浏览器缓存更新回写到 `state.json` 文件；
5. 所有敏感凭证文件（`runtime/` 及 `config/cookies/*.json`，排除 `.example.json` 模板文件）**必须且 SHALL** 强制写入项目的 `.gitignore` 中。

#### Scenario: 首次启动无本地持久化状态时使用静态单行文本 Cookie 字符串初始化
- **WHEN** 执行爬取命令且本地不存在 `runtime/weibo/state.json` 文件，但 `config/cookies/weibo_cookies.json` 中配置了单行纯文本的原始 Cookie 字符串 `"SUB=weibo123; entry=weibo456"` 时
- **THEN** 爬虫后台自适应切割字符串并为每个键值对自动注入域为 `.weibo.com`，Playwright 顺利以此初始化并抓取，最终自动生成并保存完整的 `state.json` 状态文件
