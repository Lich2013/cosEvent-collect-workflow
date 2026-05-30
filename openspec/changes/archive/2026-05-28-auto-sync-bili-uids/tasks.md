## 1. 基础数据层与爬虫检索模块扩展

- [x] 1.1 在 `src/services/db/coser_repository.py` 中新增 `get_active_cosers_without_bilibili()` 查询方法，用于批量获取未绑定 B站 UID 的活跃 Coser 列表。
- [x] 1.2 在 `src/tools/bilibili_scraper.py` 中新增并实现 `search_bilibili_user(keyword)` 检索方法，使用 Playwright 的 `expect_response` 异步拦截 B站 用户检索接口并解析候选人元数据。

## 2. 启发式匹配与打分算法核心业务逻辑

- [x] 2.1 新增 `src/services/bili_uid_matcher.py` 精确优选服务，实现启发式打分打分机制：包含名称一致性比对、对数粉丝量计算（`math.log10(max(fans, 1))`）、官方认证加分，返回最高得分且高信度唯一匹配。
- [x] 2.2 在 `tests/` 下新增针对 `bili_uid_matcher` 算法模块的单元测试，模拟各种极端环境（精确重名、低粉仿冒、模糊拼写、无/有官方认证等）的打分排序与硬门槛阻断。

## 3. 命令行指令路由与控制台彩显

- [x] 3.1 在 `src/views/terminal_renderer.py` 中为 `TerminalRenderer` 新增并开发专门用于展示 B站 UID 同步过程、分值排序与绑定结果的高清四色彩显表格渲染方法。
- [x] 3.2 在 `src/main.py` 中注册并配置 `coser sync-bili` CLI 命令行参数（支持 `--limit` 与 `--dry-run`），串联同步工作流控制，添加 2~4 秒的随机冷却规避反爬风险。
- [x] 3.3 运行整体流程冒烟测试及 `pytest` 单元回归测试，保障系统 100% 稳定与向后兼容。

## 4. CR 反馈缺陷修正与性能优化

- [x] 4.1 在 `BilibiliScraper` 中实现并添加 `search_bilibili_users_batch(keywords)` 方法，实现 Playwright 浏览器 Session 的全局批量复用检索（防冷启动开销）。
- [x] 4.2 缩短 `expect_response` 超时为 2.5 秒，在 `BiliUidMatcher` 中引入签名 Bio 社交网络互链比对加分（+40分）与新人官方号绿色放行通道。
- [x] 4.3 重构 `src/main.py` 的 `sync-bili` 指令以复用批量检索服务，完善防检测（stealth）人机绕过特征，并运行 35 个 pytest 单元测试回归保障 100% 稳定性。
