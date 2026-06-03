## Context

随着系统中管理的 Coser 实体的规模（当前 110 位）不断膨胀，用户在使用 `add` 或 `update` 指令管理 Coser 凭证时，因为缺乏直观的名字相似度校验与平台 UID 冲突检测，极其容易将同一个人误录入为两个拼写相近的条目（如 "桃景三酪" vs "桃景三酪_"），或者将已录入的 UID 错置绑定到其他 Coser 下。这会直接导致数据冗余、分析错乱和库级 `raw_posts` 博文约束报错。

由于不需要做繁重的 `coser merge`，我们将本变更的设计聚焦于**前置警告校验**：非阻断但足够显眼的黄色警示，把最终决定权交给用户。

---

## Goals / Non-Goals

**Goals:**
- 提供在添加或更新 Coser 前的名字相似度匹配警报。
- 提供在添加或更新 Coser 前的平台 UID 重合度校验警报。
- 在控制台（Click 命令行环境）中以标准黄色高亮渲染这些提示，让用户了然于心。

**Non-Goals:**
- 不强制中断 `add` 和 `update` 指令的写入动作（用户即使看到警告也可以选择继续注册/更新）。
- 不破坏既有的 SQLite 数据表物理结构与级联关联。
- 不引入重型的第三方 NLP 或模糊搜索依赖（使用内置 stdlib 的 `difflib` 与轻量正则即可）。
- 不实现 `coser merge` 的合并数据指令。

---

## Decisions

### 1. 名字相似度判定与执行条件 (Fuzzy Name Checking)
- **决策**：仅在新增 Coser（或启用 `check_name_similarity=True`）时进行名字相似度检查。在更新 Coser 属性时（`check_name_similarity=False`），跳过姓名相似度检查。
  - **检索优化**：不再调用 `list_cosers()` 加载完整实体，仅执行轻量级 SQL `SELECT name FROM cosers` 提取姓名列表。
  - **清洗与判定**：
    - 归一化比对：去除两者的空格和特殊符号 `[\s\-\_\,\.\!\?\#\&\*\/]` 并转小写：`clean(name) == clean(existing_name)`。
    - 子串包含判定：若其中一个名字被另一个包含，且较短的一方长度 $\ge 2$。
    - difflib 比对：`difflib.SequenceMatcher(None, clean(name), clean(existing_name)).ratio() >= 0.7`。

### 2. UID 重用碰撞校验 (UID Collision Checking)
- **决策**：多平台 UID 校验完全移入数据库 SQL 层面，实行 $O(1)$ 精准查询以应对规模化扩展：
  - **输入参数清洗**：强制转换为去掉空格和尾部换行符的字符串：`str(uid).strip()`，保障 int/str 类型的正常兼容与空白字符绕过。
  - **SQL 匹配逻辑**：
    ```sql
    SELECT name FROM cosers WHERE TRIM({platform}_uid) = ? AND name != ?
    ```
    通过直接定位是否存在绑定相同 UID 且属于其他 Coser 的记录，避免在 Python 中进行全量表扫描与多维循环校验。

### 3. 分层解耦与非阻断警告控制 (DAL & CLI Decoupling)
- **决策**：数据访问层与命令行表现层完全解耦（符合单一职责原则）：
  - **数据层 (CoserRepository)**：`check_coser_duplicates` 仅负责执行校验并返回一个包含警告信息的结构化 `list[str]` 列表，禁止强依赖 `click`，禁止在内部直接向控制台输出。
  - **日志落盘**：在 `add_coser` 与 `update_coser` 中若发现校验警告，调用 `log_event("WARNING", "CoserRepository", warning)` 将警报异步保存至本地结构化日志中以备观测。
  - **表示层 (main.py)**：CLI 命令行控制器前置显式调用 `CoserRepository.check_coser_duplicates`。遍历返回的警告列表，通过 `click.secho(warning, fg="yellow", bold=True, err=True)` 打印。
  - **警告输出路由**：显式配置 `err=True`，强制将警告文本推送到标准错误流（stderr）中，绝不污染 stdout，保障下游重定向及微服务脚本的安全解析。

---

## Risks / Trade-offs

- **[Risk] difflib 在极短文本（如 2-3 个英文/数字字符）下的相似度飘逸**
  - **Mitigation**：在相似度计算时，优先去除无意义的符号，且对于包含关系的子串校验设置了 $\ge 2$ 的长度门槛，有效排除高频杂音。
- **[Risk] SQLite 表未加物理 UNIQUE 约束对查询性能的影响**
  - **Mitigation**：即使缺少物理 `UNIQUE` 索引，对 100~5000 行的小型名单而言，基于 `WHERE TRIM(platform_uid) = ?` 的查询开销也远小于全量 `SELECT *` 读入内存后以 $O(N)$ 嵌套循环匹配。

