## Context

目前，本系统支持 Weibo、Bilibili、XHS 的多平台活动日程采集与去重融合。然而，在通过 JSON 批量导入或手动追加微博 Coser 时，各平台对应的 `bilibili_uid` 默认留空，严重阻碍了自动化数据管道的连通。为了实现一键自动追踪的闭环，我们需要在系统中引入一套轻量级、零 LLM 额外开销、高精准的 B站 UID 智能自动检索与启发式匹配绑定系统。

## Goals / Non-Goals

**Goals:**
- 在 `BilibiliScraper` 爬虫工具类中扩展 B站 用户搜索与元数据拦截抓取方法。
- 实现确定性的启发式匹配评分算法（Heuristic Scoring），综合比对姓名精确度、粉丝数对数衰减分以及 B站 官方认证权重，以接近 100% 精度优选真实账号。
- 新增 `python src/main.py coser sync-bili` 指令，支持分页读取未绑定 Coser、批量自动打分检索与原子事务入库。
- 提供对命令行参数 `--limit`（单次同步上限数）和 `--dry-run`（只读预览模式）的完整支持。
- 使用 `TerminalRenderer` 实现四色彩显的检索得分结果输出，提供极致的 CLI 用户体验。

**Non-Goals:**
- 本次变更暂不包含小红书（XHS）UID 的自动同步（本期仅聚焦于 B站）。
- 不采用第三方的外部搜索引擎（如 Google、Baidu），完全基于 B站 原生的用户搜索与 Playwright 有状态会话环境，确保不引入新的外部依赖。

## Decisions

### 决策 1：基于 Playwright 浏览器 Session 批量复用拦截 vs 逐个冷启动独立请求
- **选型**：BilibiliScraper 全局批量 Context 复用检索模式。
- **原因**：为解决逐个 Coser 调用产生的浏览器冷启动 CPU/内存开销，我们在 `BilibiliScraper` 中开发 `search_bilibili_users_batch(keywords)` 方法。整个 CLI 指令生命周期内**仅拉起一次 Playwright Chromium 浏览器实例**，在同一个浏览器上下文中顺序或并发搜索，并在全部完毕后统一关闭，使性能整体提升数倍。

### 决策 2：启发式打分排序算法与防误杀策略
- **选型**：多指标评分（Name Score + Log Fans + Verify Score + Bio Cross-verify）+ 萌新绿色通道。
- **原因**：
  1. **社交网络互证**：如果 Coser 的 B站 签名（`usign`）或官方认证描述中显式包含其微博昵称（如“微博：@横川是川崽”），则直接赋予 **+40 分特权分**，彻底消除由于多平台昵称不一致导致的硬性漏配。
  2. **冷启动新人免检通道**：如果候选人满足精确匹配（`Name Score = 50.0`）且拥有官方认证（`Verify Score = 20.0`），说明身份无疑。直接绿灯放行通过，不再受 `fans >= 100` 的门槛误杀限制。

### 决策 3：拦截超时极速降级与人机风控特征隐藏
- **选型**：2.5秒极速超时降级 + Stealth 防爬特征隐藏。
- **原因**：
  1. **超时缩短**：将 `expect_response` 的等待超时从 10s 大幅压缩至 2.5s，若遇到 WAF 风控或人机验证码，系统能在秒级实现**无感降级**到 DOM 解析，避免产生百秒以上的挂起假死。
  2. **防检测**：利用 `playwright-stealth` 的防特征外泄机制屏蔽 `navigator.webdriver` 标志，防止 WAF 防火墙通过指纹识别为自动化进程，提升对抗能力。

## Risks / Trade-offs

- **[Risk] B站账号风控或反爬限制**
  - **Mitigation**: 引入同步上限限制，且在批量检索中对每个用户施加 2 到 4 秒的随机冷却延迟。
- **[Risk] 部分 Coser B站昵称与微博差异过大**
  - **Mitigation**: 提供基于签名（Bio）的社交链抓取分析以提升召回率，同时提供 `--dry-run` 预览打分报告供人工核对。
