## Context

当前系统在运行全流程数据抓取与分析命令 `cosevent process` 时，最终的 Scraper 爬取摘要将“活跃 Coser 总人数”统一作为各大平台爬虫运行成功率的分母。
例如在有 2 位 Coser 且均未绑定小红书 UID 的情况下，会显示 `小红书(0/2)`，给用户带来“爬虫发生了重大崩溃”的虚假系统报错体验。
其物理本质在于每个 Coser 绑定的平台账号不同，因此各平台的爬行基准（有效分母）是独立且动态的。需要对 `src/main.py` 中的统计机制进行升级。

## Goals / Non-Goals

**Goals:**
- 将 `success_platforms` 统计容器进行结构升级，合并管理各平台“实际爬取成功数 (success)”与“实际绑定有效 UID 的总数 (total)”。
- 在 `_async_scrape` 循环体中，根据 Coser 是否配置了特定平台的有效 UID 动态增量累加该平台的分母统计。
- 重构终端总结报告的打印渲染逻辑，使其展示完全对齐客观事实的精确百分比率。
- 确保重构完美向下兼容，不破坏现有爬虫方法的其他功能或底层行为。

**Non-Goals:**
- 不修改 WeiboScraper, BilibiliScraper, XhsScraper 等各个平台爬虫类的底层 Ajax 请求拦截与解析提取规则。
- 不增加 `_async_scrape` 函数的返回值个数，避免大范围破坏方法的多变量接收签名。
- 不修改数据库层（SQLite）关于 Coser 的绑定属性字段与表结构。

## Decisions

### 决定 1：升级 `success_platforms` 容器为精细字典结构
- **决策内容**：将 `success_platforms` 的数据结构由单纯记录成功数的 `dict[str, int]`，升级为记录分子分母的二级复合嵌套字典：
  ```python
  success_platforms = {
      "weibo": {"success": 0, "total": 0},
      "bilibili": {"success": 0, "total": 0},
      "xhs": {"success": 0, "total": 0}
  }
  ```
- **原由与收益**：
  - **参数接收零破坏**：该改动保留了 `_async_scrape` 返回三个变量（`total_cosers, success_platforms, total_inserted`）的原始签名，使主调处 `scrape_command` 与 `_async_process` 无需重构签名，改动范围被完美收缩控制在 `src/main.py` 内部。
  - **高内聚统计**：分子和分母在同一个数据实体中统一闭环，逻辑极其清晰。
- **替代方案评估**：*引入第 4 个返回值变量 `configured_platforms`*。这会导致 `asyncio.run(_async_scrape(lim))` 处所有多变量解包（Unpacking）直接抛出 `ValueError: too many values to unpack` 并引起广泛红屏，故不予考虑。

### 决定 2：在 UID 检测分支中进行动态分母累加
- **决策内容**：在遍历每个启用状态的 Coser 时，一旦通过平台 UID 的非空有效性校验，即对其对应的 `total` 字段加 1：
  ```python
  if c["weibo_uid"]:
      success_platforms["weibo"]["total"] += 1
  ```
- **原由与收益**：此段代码仅在 Coser 实际绑定了微博账号且即将启动爬取前触发，能物理精准对齐“实际执行的爬行次数”。

## Risks / Trade-offs

- **[风险] 终端输出断言可能失效**
  * **缓解措施**：本项目单元测试中没有针对控制台 `click.echo` 的硬编码文本匹配断言（仅测试了底层 scraper 的 json 提取和数据入库），因此此终端报告的文案改进对测试套件完全无害。
