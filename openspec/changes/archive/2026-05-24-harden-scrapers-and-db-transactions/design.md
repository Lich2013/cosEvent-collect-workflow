## Context

本项目拟针对代码审查 (CR) 中发现的五大安全解析与运行时缺陷（包括微博注销用户 None 容错、服务器 UTC 跨时区偏差、B站动态无发布时间、SQLite 游标连接泄漏以及终审裁判 Prompt Token 冗余开销）进行全面的一体化加固与深度优化。

## Goals / Non-Goals

**Goals:**
- **安全解析**：实现被转发作者为 `None` 的真值兜底，将其安全格式化为 `"原作者"`。
- **时区锁死**：全局引入 `Asia/Shanghai` 时区，彻底规避 UTC 物理服务器运行引起的 1 天时空分流偏差。
- **动态时间时序化**：从 B 站 Ajax 拦截响应中提取原生 `pub_ts` 并将其标准化写入数据库，提升 B 站原始记录的可排序性。
- **数据库事务与游标彻底闭合**：利用 Python 语言 `with conn:` 事务与 `with conn.cursor() as cursor:` 游标双上下文，确保并发读写下的百分百彻底释放，解决 SQLite `database is locked` 死锁缺陷。
- **共识裁判 Prompt Token 瘦身**：将并行的模型提取候选草稿极度压缩（过滤一切无用冗余字段，仅保留 `name`、`date`、`place`、`desc`、`conf`）再提交给终审裁判，大幅节省大模型运行的 Token 费用开销并提高去重合并精准度。

**Non-Goals:**
- 不涉及数据库 Schema 表结构的物理更改，纯粹在应用层进行健壮性加固与大模型费用优化。

## Decisions

### 决策 1：原博作者 None 值真值兜底机制
- **技术选型**：利用 Python `or` 运算的真值/假值评估。
- **实现**：`orig_user = orig_user_dict.get("screen_name") or "原作者"`。若 `screen_name` 为空字符串或 `None`，表达式自动右结合降级兜底为 `"原作者"`，一举解决微博注销或隐私博主的 None 干扰缺陷。

### 决策 2：显式强制注入北京时区 (Asia/Shanghai)
- **技术选型**：在 `db_service.py` 获取系统时间进行增量比较与时间流判定时，全局使用 `datetime.timezone(datetime.timedelta(hours=8))` 格式化本地日期，锁定 YYYY-MM-DD，免除物理主机 UTC 带来的分流错乱隐患。

### 决策 3：SQLite 自动事务与自动游标闭合上下文
- **技术选型**：全面修改 `DBService`。不仅通过 `with conn:` 上下文交由 SQLite 底层驱动自动执行 `commit/rollback`，更将每一个 SQL 执行的 `cursor` 均包裹在 `with conn.cursor() as cursor:` 块中。这能保证一旦离开代码块，游标资源无论成功与否均被物理闭合，从根本上绝迹连接泄漏缺陷。

### 决策 4：草稿 JSON Token 降维精简算法
- **技术选型**：对传参给裁判智能体 `consensus_judge_agent` 的 `valid_outputs` 候选草稿进行降维投影。
- **实现**：在组装裁判 Prompt 前，遍历候选活动并将每个活动字典映射精简为 `{name, date, place, desc, conf}`，剔除其余非必要的高噪声调试/URL 信息，实现终审 Token 的断崖式降费。

### 决策 5：B站无文本空动态过滤防御机制
- **技术选型**：在 `BilibiliScraper` 提取并合并完转发内容后，检查 `content_text.strip()` 是否为空。若为空，说明该动态为纯多媒体/投稿且没有任何用户填写的文本附言。
- **实现**：若最终合并文本内容为空，执行 `continue` 退出当前动态解析循环，防范无意义的空记录入库，消除由此引发的下游 LLM 增量分析的费用空耗。

## Risks / Trade-offs

- **[Risk] B站动态 pub_ts 字段突变引发 KeyError**
  - **Mitigation**：在 `BilibiliScraper` 提取该字段时，设计严格的 `try-except (KeyError, TypeError)` 安全屏障，一旦解析失败则优雅地将 `published_at` 填补为 `None` 或当前系统时间，绝不导致 Playwright 爬行链路发生崩溃。
