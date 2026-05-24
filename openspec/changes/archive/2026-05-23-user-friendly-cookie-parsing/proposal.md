## Why

传统的 Playwright Scraper 会话种子机制（例如标准 Playwright 的 JSON 字典数组 Cookies）要求用户从第三方插件中导出，或在文件中组装包含 `name`、`value`、`domain` 和 `path` 的复杂结构，这对普通用户来说使用门槛过高。本变更旨在重构种子 Cookie 加载模块，使用户能够直接在 `weibo_cookies.json`、`bilibili_cookies.json` 和 `xhs_cookies.json` 中配置直接从浏览器开发者工具（DevTools）请求头中复制出来的单行原始 Cookie 字符串（例如 `"SUB=xxx; _s_tentry=yyy"`），实现极简、无门槛配置。

## What Changes

- **增强 Cookie 载入与自适应解析**：重构 `src/tools/playwright_base.py` 中的 `load_seed_cookies()` 方法。当文件内容是普通 JSON 格式的单行 Cookie 字符串或纯文本形式的键值对时，系统必须在后台自适应将其切割，并根据当前平台自动注入默认的 Domain（如 `.weibo.com`、`.bilibili.com`、`.xiaohongshu.com`）和 Path（`/`），转换构造成 Playwright 所需的标准字典列表。
- **更新 Cookie 文件种子模板**：将 `config/cookies/` 下的 `weibo_cookies.example.json`、`bilibili_cookies.example.json`、`xhs_cookies.example.json` 更新为支持更方便的 Cookie 字符串文本格式示例。
- **更新用户说明文档**：在项目主 `README.md` 的 Cookie 配置小节中，增加关于“支持一键复制粘贴单行原始字符串”的使用配置指引。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- 无

## Impact

- 影响 `src/tools/playwright_base.py` 爬虫基础类，以及 `config/cookies/*.json` 种子示例和说明文档。
- 向上保持对原有的严格 JSON 数组格式 Cookies 的完全兼容，不产生任何 BREAKING 破坏性变更。
