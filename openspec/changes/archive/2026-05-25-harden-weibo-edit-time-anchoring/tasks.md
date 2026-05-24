## 1. 微博爬虫层高精度编辑时间抓取与安全降级

- [x] 1.1 修改 `src/tools/weibo_scraper.py`，实现 `editHistory` 异步接口请求与最新编辑时间抓取解析，并在遭遇异常或受控时自动无损降级回退至解析原始 `created_at`

## 2. 数据库服务层智能有状态重锚写入

- [x] 2.1 修改 `src/services/db_service.py` 中的 `save_raw_posts` 写库事务，实现查重版本扫描判定。如果是历史首次录入（被动），在新插入记录时维持高精度或原始年份时间；如果是实时抓取编辑版本（主动），则新插入的编辑版本记录强行重锚 `published_at` 为当前北京抓取时间以防止相对日期漂移

## 3. 智能体 Prompt 模板 Few-Shot 坏例添加

- [x] 3.1 修改 `config/templates/event_analysis.jinja2` 提取模板，注入针对陈年置顶微博的 Few-shot 坏例（Bad Case）样本与推理约束
- [x] 3.2 修改 `config/templates/event_consensus_judge.jinja2` 裁判模板，注入针对陈年置顶微博的 Few-shot 坏例（Bad Case）样本与推理约束

## 4. 单元测试与系统验证

- [x] 4.1 在 `tests/test_cosevent.py` 中编写与升级高精度时间重锚相关的单元测试，包含接口请求解析成功断言、降级原始年份时间锁死断言、以及数据库事务重锚判断断言
- [x] 4.2 运行本地 `uv run pytest` 执行完整的测试套件，确保 23 个既有及新增用例 100% 绿屏成功通过
