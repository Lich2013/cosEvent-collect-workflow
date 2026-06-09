## 1. 修改数据库初始化与迁移逻辑

- [x] 1.1 在 `src/models/db_models.py` 的 `init_db()` 函数中，检索 `candidate_raw_posts` 的既有 DDL 定义，检查其中是否包含 `"coser_candidates_old"`
- [x] 1.2 若包含失效的表名引用，在执行 `CREATE TABLE IF NOT EXISTS candidate_raw_posts` 前，执行 `DROP TABLE candidate_raw_posts;` 物理清理该表以进行自愈重建

## 2. 验证与回归测试

- [x] 2.1 运行 CLI 命令 `uv run python src/main.py init-db` 触发数据库校验与结构修复，检查终端输出是否包含自愈重建日志
- [x] 2.2 运行发现命令 `uv run python src/main.py coser discover --limit 1`，确认能成功对队列首个候选人完成校验流转，且没有 `no such table: main.coser_candidates_old` 的回滚错误，缓冲队列待验证候选人数量成功递减
- [x] 2.3 运行项目全量单元测试 `uv run pytest`，确保没有发生回归异常且 100% 成功通过
