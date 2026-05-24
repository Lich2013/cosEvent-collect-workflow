## 1. 数据库定义加固与北京时间轴整顿

- [x] 1.1 修改 `src/models/db_models.py`，升级 `cosplay_events` 建表定义，为 `status` 列添加物理约束 `CHECK (status IN ('未开始', '已结束', '已取消'))`，并从三张核心表中彻底剥离 `DEFAULT CURRENT_TIMESTAMP` 隐式 UTC 约束
- [x] 1.2 重构 `src/services/db_service.py` 内部的所有 `INSERT` 与 `UPDATE` 语句，确保 created_at/scraped_at 的时间完全收归 Python 应用层，统一显式回填东八区北京时间格式 `now_str`；同时在写入前添加 status 列应用层防御性校验

## 2. 跨平台编辑内容对比与合成版本号机制

- [x] 2.1 修改 `src/services/db_service.py` 中的 `save_raw_posts` 博文去重与保存逻辑，引入博文正文内容（content）哈希/文本变化判定机制：对于 bilibili 和 xhs 等不支持原生编辑计数的平台，一旦判定正文发生变更，应用层自动虚拟递增 `edit_count = stored_edit_count + 1`，并对 `post_id` 自动追加 `#v{edit_count}` 后缀，在 `raw_posts` 中作为新纪录追加写入以自适应启动增量分析及级联软状态机取消

## 3. DeepSeekTransport 拦截层安全熔断与转义传输

- [x] 3.1 修改 `src/tools/llm_bridge.py` 中的 `DeepSeekTransport` 拦截机制，将 json_schema 降级改写全生命周期包裹在严密的 `try...except` 容错熔断控制块内。一旦拦截改写阶段遭遇任何异常，自动打印 `WARNING` 日志并立即降级熔断，安全无损回退发送原始客户端请求以保障系统绝不崩溃
- [x] 3.2 将 `DeepSeekTransport` 内序列化重写语句改写为 `ensure_ascii=True` 转义，强制将汉字与多字节 Emoji 转义为合规的纯 ASCII Payload 传输，彻底规避代理截断 Content-Length 偏差隐患

## 4. 单元测试与系统验证

- [x] 4.1 在 `tests/test_cosevent.py` 中编写完备的加固与合成版本控制单元测试，断言拦截层安全熔断、物理 CHECK 值域拦截、以及 B站/小红书二次编辑内容变更时的虚拟版本晋升及事务内级联软取消正常工作
- [x] 4.2 本地虚拟环境执行 `uv run pytest` 执行完整的回归测试，确保 21 个单元测试全量成功通过
