## 1. 微博爬虫功能增强 (WeiboScraper)

- [x] 1.1 在 `src/tools/weibo_scraper.py` 中，新增 `resolve_screen_name(self, screen_name: str) -> dict` 异步方法。
- [x] 1.2 该方法通过 Playwright 加载会话上下文，并在页面中执行 fetch 请求微博 AJAX 用户信息接口（`/ajax/profile/info?screen_name=xxx`），成功时提取并返回包含 `idstr` 和 `description` 的用户对象。

## 2. 候选人发现服务更新 (DiscoveryService)

- [x] 2.1 在 `src/services/discovery_service.py` 中引入微博后缀裁剪预处理函数（例如 `prune_weibo_suffix`），剥离名字中类似 `_cos`, `_Coser`, `_ShiratoriK` 等常见无意义后缀。
- [x] 2.2 修改 `verify_pending_candidates`，在处理 `platform == 'weibo'` 的候选人时，优先调用 `WeiboScraper.resolve_screen_name` 获取其微博 UID 和 Bio。
- [x] 2.3 修改二次元属性过滤逻辑：候选人如果通过微博 Bio 二次元关键词校验，或者通过 B 站对齐匹配及 B 站简介校验，即视为校验通过。
- [x] 2.4 在调用 `DBService.add_candidate` 保存验证成功的候选人时，传入对应的 `matched_weibo_uid` 参数。

## 3. 测试与验证

- [x] 3.1 运行既有单元测试确保没有破坏已有功能。
- [x] 3.2 编写针对微博昵称解析和后缀裁剪的单元/集成测试。
- [x] 3.3 运行发现与验证流程，验证以 `北川白鸟_ShiratoriK` 和 `小沂Alter` 为例的微博候选人，在运行后是否被正确匹配并在数据库中成功对齐绑定双平台 UID。
