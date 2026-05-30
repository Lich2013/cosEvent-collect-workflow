## 1. 重构 Scraper 单条查询 DOM 提取引擎

- [x] 1.1 在 `src/tools/bilibili_scraper.py` 的 `search_bilibili_user` 方法中的 DOM 解析分支里，引入多选择器自适应兼容选择链（包含 `.user-content`, `[class*="user-item"]` 等）来定位用户卡片。
- [x] 1.2 重构昵称与 UID 的提取逻辑，改为直接定位包含 `space.bilibili.com` 路径的超链接 `<a>` 标签，提取其文本作为昵称，提取其属性 `href` 拆解出 `mid`。
- [x] 1.3 重构粉丝数与个人签名的提取逻辑，通过特征定位包含 `"粉丝"` 字样的文本元素，读取其 `title` / `inner_text` 并使用正则 `([\d\.]+)(万)?\s*粉丝` 进行高精确度提取与换算。优先查找内层 `<span>` 以定位简介，降级则切片 `"视频"` 字样后的文本。

## 2. 重构 Scraper 批量查询 DOM 提取引擎

- [x] 2.1 同步更新 `src/tools/bilibili_scraper.py` 的 `search_bilibili_users_batch` 方法中的 DOM 兜底解析逻辑分支，对齐 1.1 的卡片容器定位规则。
- [x] 2.2 同步更新批量解析中昵称与 UID 的超链接硬提取规则。
- [x] 2.3 同步更新批量解析中基于正则与关键字的粉丝数、简介签名的提取规则，保障大批量执行下的提取健壮性。

## 3. 编写与运行单元及回归测试

- [x] 3.1 在 `tests/test_bili_uid_matcher.py` 或新建专门的测试用例中，模拟包含新版 HTML 结构的网页 DOM，测试并验证自适应 DOM 解析器能 100% 精准提炼出目标 UID（如 1526435）、用户名、换算粉丝数（58000）和个人简介。
- [x] 3.2 运行回归测试（如 `.venv/bin/pytest`），确保全部 42 个单元测试用例完美红绿灯通过。
