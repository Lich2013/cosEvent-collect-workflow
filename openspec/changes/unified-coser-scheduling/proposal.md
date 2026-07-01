## Why

目前 Coser 的爬取调度是以平台为维度的（各个平台独立选出该平台下最久未爬取的 Top 30 进行去重合并）。这导致当一个 Coser 在不同平台的上次抓取时间不同步时（例如，某 Coser 的微博在 6/29 刚被抓取过，但在 B站 很久没抓），她在 B站 被调度选中后，在这一轮调度中只有 B站 会被抓取，而微博则因为“不够久”被微博队列漏掉。抓取完成后她的 B站 时间戳被更新，导致此后很难在同一批次中同时触发这两个平台的抓取，产生严重的漏抓 Bug。

本修改旨在将调度逻辑统一为**以 Coser 个人为维度**进行调度，确保一旦选出最久未碰过的 30 人，就一次性抓完他们所有已配置的平台，从而彻底解决漏抓和时间戳不同步的问题。

## What Changes

- **调度逻辑重构**：从“每个平台独立获取 Top 30 后交错去重”改为“统一按 Coser 维度获取全局最久未碰过的 Top 30 活跃 Coser”，然后对于选中的每个人，抓取其所有已配置的平台。
- **时间戳存储简化**：弃用 `coser_scrape_state` 表（每人每平台一行），直接在 `cosers` 表中添加 `last_scraped_at` 字段。只要该 Coser 在任意平台被抓取（不论成功或失败），均更新此全局时间戳。
- **平滑历史数据迁移**：在初始化/升级数据库结构时，自动将 `coser_scrape_state` 中各 Coser 的最晚抓取时间迁移至 `cosers.last_scraped_at` 字段，避免迁移后产生瞬间高频爬取的流量风暴。
- **测试用例修正**：更新 `test_sliding_window.py` 与 `test_fine_grained_scrape.py` 以适配新的全局调度机制。

## Capabilities

### New Capabilities

- 无（本改动为现有爬取调度机制的底层重构与 Bug 修复）

### Modified Capabilities

- content-scraping: 调度从按平台独立取 Top 30 重构为全局按 Coser 维度取 Top 30，更新全局的 last_scraped_at 字段。

## Impact

- 涉及的文件：
  - `src/models/db_models.py`：数据库表结构初始化及 `ALTER TABLE` 热升级历史数据迁移。
  - `src/services/db/coser_repository.py`：重构调度查询 `list_active_cosers_by_schedule` 和时间戳更新 `update_scrape_timestamp`。
  - `src/services/workflow_orchestrator.py`：简化 `run_scrape` 内部的调度分配循环。
  - `tests/test_sliding_window.py` / `tests/test_fine_grained_scrape.py`：单元测试用例的 Mock 及断言更新。
- 数据库变动：
  - `cosers` 表新增 `last_scraped_at TEXT` 字段。
  - 弃用 `coser_scrape_state` 表的实际写入。
