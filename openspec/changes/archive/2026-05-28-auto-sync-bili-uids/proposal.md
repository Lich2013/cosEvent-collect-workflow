## Why

目前系统支持微博、B站、小红书多平台日程的采集与智能融合。然而，当用户批量导入或新增 Coser 追踪名单时，B站的 UID 默认留空。手动通过命令行逐个补全 UID 极其繁琐。因此，需要设计并实现一套基于 Coser 昵称、自动精确检索并智能去重绑定 B站 UID 的同步机制，从而彻底打通多平台一键追踪的业务闭环。

## What Changes

- 新增 Coser B站 UID 自动同步子命令：`python src/main.py coser sync-bili`，支持根据平台 Coser 姓名/昵称自动检索 B站对应的 UP 主。
- 检索通道复用底层 Playwright 有状态会话环境，保障反爬和网络通信的稳定运行。
- 引入启发式算法评分排序机制（结合名称相似度、粉丝量级对数权重、官方认证加分）自动识别高信度候选者，防范抢注与高仿，并支持多候选手动覆写绑定。
- 在控制台提供直观的高清彩显同步过程及匹配得分结果展示。
- 更新数据库状态与 CLI 指令，支持对同步行为进行事务更新。

## Capabilities

### New Capabilities
- `bili-uid-sync`: B站 UID 自动精确同步检索与启发式匹配绑定能力。

### Modified Capabilities
<!-- 无 spec-level 级已有需求的变更 -->

## Impact

- `src/main.py`: 新增 `coser sync-bili` CLI 子命令及参数路由。
- `src/tools/bilibili_scraper.py`: 新增 `search_bilibili_user` 方法以实现基于 API 或网页的用户检索。
- `src/services/db/coser_repository.py`: 新增获取缺失 B站 UID 列表的查询，以及更新 B站 UID 的接口。
- `src/services/db_service.py`: 对齐 Facade 接口的向后兼容，暴露 UID 更新与查询接口。
