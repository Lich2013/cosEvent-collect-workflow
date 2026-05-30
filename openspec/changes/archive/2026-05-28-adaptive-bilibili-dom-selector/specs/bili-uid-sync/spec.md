## MODIFIED Requirements

### Requirement: 批量上下文复用检索与秒级风控降级
系统爬虫检索模块 SHALL 引入批量上下文复用机制（在同一个 Chromium 浏览器实例中顺序/并发跑完所有搜索，避免高开销冷启动）。接口拦截超时 SHALL 缩短至 2.5 秒，以在发生风控滑块时极速秒级降级为 DOM 兜底解析。
在执行 DOM 兜底解析时，系统爬虫 SHALL 采用多选择器自适应兼容链（Multi-selector Fallback Chain）与正则表达式匹配特征技术。系统必须且 SHALL 精确过滤指向 `space.bilibili.com` 域名的 HTML 锚点（`<a>`）提取 UID（`mid`）与 UP主昵称，并使用正则精确匹配粉丝数值（支持“万”字换算）及提取个人签名，保障在新型 CSS 类名及 Module 属性变化下的数据提炼精度。

#### Scenario: 快速降级至 DOM 解析并自适应提取新版 HTML 数据
- **WHEN** 检索因 B站 反爬触发 WAF 阻断或接口在 2.5 秒内未响应，且页面以新型 CSS Module 扁平化布局渲染（如使用 `user-content`, `i_card_title`, `text_ellipsis` 等类名）
- **THEN** 系统秒级超时断开拦截器，优雅滑入 DOM 节点解析。通过寻找包含 `space.bilibili.com` 的 `<a>` 标签精确定位到 `mid` 为 `"1526435"`，`uname` 为 `"横川是川崽耶"`；同时利用正则匹配文本，成功提取并换算出粉丝数为 `58000`，并捕获到个人签名 `"吉尼斯纪录最小心眼保持者"`
