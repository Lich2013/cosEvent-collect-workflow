## Context

为了提升二次元情报系统的健壮性，本设计旨在规避数据库层字段约束缺失、应用层与数据库时间格式混淆、跨平台二次编辑版本控制不对称，以及大模型传输改写缺少安全熔断机制的问题。

## Goals / Non-Goals

**Goals:**
- **跨平台合成版本号**：在 `db_service.py` 写入 raw_posts 时，对比已存正文（content），一旦发现 B站/小红书内容有变，在应用层虚拟递增 `edit_count = stored_edit_count + 1`，自动拼接 `#v` 后缀并在事务中级联软注销历史未来行程，实现版本控制对齐。
- **物理约束强制拦截**：在 `cosplay_events.status` 列注入物理 `CHECK (status IN ('未开始', '已结束', '已取消'))` 值域约束。
- **时区与时间线锁定**：全面移除 `DEFAULT CURRENT_TIMESTAMP` 隐式 UTC 赋值，由 Python 应用层强力锁死东八区北京时间 `YYYY-MM-DD HH:MM:SS` 格式写入。
- **传输拦截安全熔断**：为 `DeepSeekTransport` 添加 `try-except` 极速降级熔断与 `ensure_ascii=True` 转义防范机制，确保存输层的绝对可靠性。

**Non-Goals:**
- 不改变大模型智能体与裁判的核心 Pydantic 返回强契约。
- 不引入外部复杂的数据库迁移管理框架（如 alembic），基于内置 PRAGMA 在线嗅探自动热升级。

## Decisions

### 决定 1：利用正文对比虚拟合成版本控制（Synthetic Versioning）
* **决策内容**：在 `DBService.save_raw_posts` 时，先查询已存记录的 `content`。如果 `platform` 为 `bilibili` 或 `xhs`，且已存的 `content` 与当前抓取的 `content` 不一致，则判定博文已被编辑。此时，强制使 `edit_count = stored_edit_count + 1`，并将 `post_id = f"{post_id}#v{edit_count}"` 写入。
* **原由与收益**：B站和小红书的 API 响应中不提供显式的微博式 `edit_count`。该方案巧妙地在应用层无缝合成了版本号，能够全量复用已存在的微博 `#v` 历史快照多版本存储逻辑和事务中跨版本级联软取消算法，以最低的架构改造成本实现了跨平台完美的一致性。

### 决定 2：精细化的物理 CHECK 值域约束与 Python 插入前校验
* **决策内容**：
  1. 在 `db_models.py` 的 `cosplay_events` 创建语句中加入 `CHECK (status IN ('未开始', '已结束', '已取消'))`。
  2. 在 `db_service.py` 插入和更新时，显式检查 `status` 必须为上述三个有效状态之一。
* **原由与收益**：为防止在外部系统调用、开发时手动执行 SQL 或拼写错误时注入垃圾状态值（例如 `'已取销'`），在物理数据库层和 Python 应用层同时构建前置阻断防线。

### 决定 3：剥离 DEFAULT CURRENT_TIMESTAMP 由 Python 全程规范化托管
* **决策内容**：在 `db_models.py` 中移除所有表的 `DEFAULT CURRENT_TIMESTAMP`。所有 created_at / scraped_at 的时值填充，在 `db_service.py` 内部全部显式采用 `now_str` (北京时间) 进行手动写入。
* **原由与收益**：`CURRENT_TIMESTAMP` 是 SQLite 的 UTC 本地时值回填，与我们定制的东八区北京时间 `now_str` 在格式和时区上双重冲突。完全剥离默认值可强制约束所有写库入口均使用标准统一的北京时间写入，彻底消除时空漂移隐患。

### 决定 4：DeepSeekTransport 拦截重写熔断兜底与纯 ASCII 转义
* **决策内容**：
  1. 在 `DeepSeekTransport._rewrite_request` 内进行 JSON 降级处理时，使用 `try...except Exception` 包裹全过程。一旦捕获到任何序列化、分块传输或类型解析异常，打印警告日志并**立即熔断**，不执行任何重写，无缝回退发送原始客户端请求。
  2. 改写时的 `json.dumps(payload, ensure_ascii=True)` 强制转义汉字和 Emoji。
* **原由与收益**：在 HTTP 拦截层修改包体是高危操作。`ensure_ascii=True` 生成纯 ASCII 的合规 HTTP payload，彻底杜绝了特定网络网关/代理对多字节 Emoji 截断的风险。熔断兜底则保证了拦截层绝对不会成为引起主线程崩溃的单点故障。

## Risks / Trade-offs

- **[风险 1] ensure_ascii=True 导致请求体体积膨胀**  
  * **缓解措施**：虽然转义会导致中文汉字变为 `\uXXXX` 格式使字节数略微增加，但对于普通的 Prompt 长度，这部分的网络传输开销微乎其微，相比于多字节 Emoji 在 HTTP 网关层被截断或 Content-Length 计算偏差而崩溃，该权衡换取了极其高昂的传输稳健性。
- **[风险 2] 合成版本控制在内容微小噪声变化时频繁生成新版本**  
  * **缓解措施**：由于抓取回来的正文已经过爬虫精简过滤，且只有当 Coser 确实修改了内容（如修改行程）时内容才会发生变化。此外，软状态机只会取消“未来的未办行程”并保留历史行程，因此版本增加不会引入数据脏乱，完全在系统容纳范围内。
