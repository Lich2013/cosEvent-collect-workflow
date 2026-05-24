## 1. 种子 Cookie 自适应解析算法重构

- [x] 1.1 在 `src/tools/playwright_base.py` 中重构 `BaseScraper.load_seed_cookies()`。使其在 `json.load()` 解析异常或解析数据为单行 `str` 字符串时，支持自动纯文本提取、分号/等号切割，并为各键值对自动注入当前平台匹配的 Domain（微博: `.weibo.com`，B站: `.bilibili.com`，小红书: `.xiaohongshu.com`）和 Path `/`。
- [x] 1.2 对解析出来的 Cookie 执行防御性去空限制，跳过无效名称项。

## 2. 种子模板更新与用户手册说明补充

- [x] 2.1 将 `config/cookies/` 下的 `weibo_cookies.example.json`、`bilibili_cookies.example.json`、`xhs_cookies.example.json` 种子示例模板更新，使其展示支持更方便的一键复制粘贴单行原始字符串。
- [x] 2.2 在项目主 `README.md` 的 Cookie 配置及初始化说明小节中，更新关于“自适应支持直接贴入单行原始文本字符串”的使用教程。

## 3. 测试与回归校验

- [x] 3.1 编写 `tests/test_cosevent.py` 中的新测试用例 `test_user_friendly_cookie_parsing()`，使用 mock 单行原始字符串 Cookie 文件，并验证 `BaseScraper.load_seed_cookies()` 能够将其完美解析还原为合规的 Playwright 字典列表。
- [x] 3.2 运行本地 `uv run pytest` 并确保全部测试用例完美通过，保证极高用户体验设计的完美实施。
