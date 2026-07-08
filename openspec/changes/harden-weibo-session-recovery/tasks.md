## 1. 会话来源与回写控制

- [x] 1.1 在 `BaseScraper` 中增加会话来源标记，区分 `state`、`seed`、`empty` 三类浏览器上下文来源。
- [x] 1.2 实现种子 Cookie 文件修改时间晚于 `state.json` 时旁路旧 state 的逻辑，并输出不含敏感值的日志。
- [x] 1.3 增加可跳过 `storage_state` 回写和种子 Cookie 回写的内部控制路径，确保异常会话不会污染运行态或冷启动源。
- [x] 1.4 为种子 Cookie 回写增加平台关键 Cookie 存在性校验，微博至少校验 `SUB`、`SUBP`、`WBPSESS`、`XSRF-TOKEN` 中的关键登录项存在且非空。

## 2. 微博业务级健康判定与自愈

- [x] 2.1 在 `WeiboScraper` 中抽取 `mymblog` 响应分类辅助函数，识别健康响应、正常空列表、登录态失效、验证/风控和未知 schema。
- [x] 2.2 调整微博抓取逻辑，使 HTTP 200 但缺失有效 `data.list` 的响应不再被无条件视为空结果。
- [x] 2.3 实现微博使用 `state.json` 发生业务级失效后的单次冷启动重试：跳过本轮回写、删除或旁路旧 state、注入种子 Cookie 再抓取一次。
- [x] 2.4 当种子 Cookie 重试仍失败时，优雅返回空结果并记录需要人工刷新 Cookie 的警告，禁止覆盖 `state.json` 和种子 Cookie。

## 3. 可观测性与安全日志

- [x] 3.1 为会话加载来源、种子 Cookie 新鲜度旁路、微博健康分类、自愈重试和跳过回写原因增加结构化日志。
- [x] 3.2 确保日志只记录 cookie 名称、响应顶层字段、`ok`、`msg` 摘要等非敏感信息，不输出 cookie value。

## 4. 测试覆盖

- [x] 4.1 添加单元测试：种子 Cookie 文件比 state 新时，`get_browser_context` 不加载旧 `storage_state`，而是注入种子 Cookie。
- [x] 4.2 添加单元测试：微博 `mymblog` HTTP 200 但缺失 `data.list` 时触发业务级失效路径并阻止回写。
- [x] 4.3 添加单元测试：微博 state 业务级失效后会使用种子 Cookie 重试一次，重试成功后允许健康回写。
- [x] 4.4 添加单元测试：微博 state 与种子 Cookie 均失效时返回空列表且不回写 `state.json` 或种子 Cookie。
- [x] 4.5 回归运行相关测试，至少覆盖 `tests/test_coser_bio_scraping.py`、`tests/test_weibo_resolution.py`、`tests/test_cosevent.py` 中的 Cookie 与微博解析用例。
