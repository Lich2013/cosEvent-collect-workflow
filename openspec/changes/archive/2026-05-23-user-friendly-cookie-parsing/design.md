## Context

为了给终端用户提供最顺畅、简便的使用体验，我们必须让静态种子 Cookie 支持单行原始 Cookie 字符串的载入。目前 Playwright `BaseScraper` 仅接收标准的 JSON 字典数组，我们需要在底层设计一个自动转换和映射器。

## Goals / Non-Goals

**Goals:**
- **自适应兼容**：支持加载原始单行 Cookie 字符串（支持被等号、分号分割的键值对形式），并自动为各键值对填充平台匹配的 Domain 和 Path `/`。
- **原有兼容性**：保留对原先标准 Playwright JSON 数组（列表字典）格式的直接加载，实现双模自适应。

**Non-Goals:**
- 不修改各 Scraper 本身的获取细节，抓取控制流和拦截器保持不变。

## Decisions

### 1. 种子 Cookie 自适应解析算法
- **机制**：
  在 `BaseScraper.load_seed_cookies()` 载入 JSON 文件时：
  1. 尝试以 `json.load()` 解析内容。
  2. 如果解析出的数据是一个 **list（列表）**，则断言其为标准 Playwright 字典数组，直接返回。
  3. 如果解析出的数据是一个 **str（字符串）**，或者由于文件并不是合法 JSON（只包含纯字符串文本）导致 `json.JSONDecodeError` 异常：
     - 系统捕获该异常，并使用 `f.read()` 读取整个文件的原始纯文本内容。
     - 使用自定义切割逻辑，将字符串按分号 `;` 分割成多条，再按等号 `=` 分割出 `name` 与 `value`。
     - 为每条 Cookie 自动注入其平台匹配的顶级域（Weibo: `.weibo.com`，Bilibili: `.bilibili.com`，XHS: `.xiaohongshu.com`）和 Path `/`。
     - 构造字典返回给 `context.add_cookies()`。

## Risks / Trade-offs

- **[Risk]** 用户复制的单行 Cookie 字符串末尾可能存在空白或格式不规范。
  - **Mitigation**：在解析时对 `name` 和 `value` 执行严格的 `.strip()` 去空操作，并且跳过 `name` 为空的无效项，增强过滤防崩溃度。
