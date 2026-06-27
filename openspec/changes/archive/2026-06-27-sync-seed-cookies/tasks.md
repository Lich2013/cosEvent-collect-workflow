## 1. 核心代码改造

- [x] 1.1 在 `src/tools/playwright_base.py` 的 `BaseScraper` 中实现 `update_seed_cookies` 方法，支持自适应检测并更新种子 Cookie。
- [x] 1.2 修改 `src/tools/playwright_base.py` 中的 `scrape_flow_handler`：在回写 `state.json` 之后获取当前最新 cookies 并触发 `update_seed_cookies`。

## 2. 单元测试与回归校验

- [x] 2.1 增加或修改单元测试，验证在不同原始格式下，种子回写输出是否符合预期。
- [x] 2.2 运行单测确认没有引入任何破坏性问题。
