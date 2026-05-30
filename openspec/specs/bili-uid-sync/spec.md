## ADDED Requirements

### Requirement: B站 UP 主自动化精确检索能力
系统 SHALL 能够利用 B站 的用户搜索服务，根据指定的 Coser 姓名/昵称在 B站 进行 UP 主搜索，并提取所有匹配候选人的结构化元数据（包含 B站 UID/mid、昵称、粉丝量、官方认证信息）。

#### Scenario: 成功检索到 UP 主候选人
- **WHEN** 系统向 B站 搜索接口查询昵称 `沐哲MuZZZ`
- **THEN** 接口成功返回结构化候选人列表，且列表包含 `uname`、`mid` , `fans` 和 `official_verify` 属性

### Requirement: 启发式多维度匹配与优选算法
系统 SHALL 能够对搜索出来的候选 UP 主进行启发式打分排序（Heuristic Scoring）。打分权重应综合考虑名称精确/模糊相似度、粉丝量级对数指数、官方认证状态。系统必须自动选择得分最高且高于置信度门槛的唯一候选人。

#### Scenario: 成功筛选出高置信度的真实账号
- **WHEN** B站 搜索接口返回两个候选人：候选人 A（昵称精确匹配、拥有 B站 官方认证、粉丝量 14.5 万）和候选人 B（昵称前缀匹配、无认证、粉丝量 12）
- **THEN** 启发式打分系统计算得出候选人 A 的分值显著高于候选人 B，且高于硬性阈值（分值 > 50 且粉丝数 > 100），系统 SHALL 自动优选并提取候选人 A 的 UID

### Requirement: 签名社交网络互证与新人免检绿色通道
启发式优选算法 SHALL 扫描候选 UP 主的个人主页签名（B站称为 `usign`/签名栏）及认证说明，如发现其包含微博姓名互链标志，SHALL 直接给予 +40 的高信度社交网络互证分。此外，针对精确重名（`Name Score = 50.0`）且拥有官方认证（`Verify Score = 20.0`）的优质新人 Coser，系统 SHALL 绿灯通过并不受 `fans >= 100` 的低粉限制。

#### Scenario: 低粉新人官方号免检成功
- **WHEN** 匹配新人 Coser 时，最佳匹配 of B站 粉丝仅有 30 个，但该候选人名字精确匹配且有官方认证
- **THEN** 系统判定其符合绿色免检条件，SHALL 忽略粉丝量硬限制并自动完成 UID 绑定

### Requirement: 批量上下文复用检索与秒级风控降级
系统爬虫检索模块 SHALL 引入批量上下文复用机制（在同一个 Chromium 浏览器实例中顺序/并发跑完所有搜索，避免高开销冷启动）。接口拦截超时 SHALL 缩短至 2.5 秒，以在发生风控滑块时极速秒级降级为 DOM 兜底解析。
在执行 DOM 兜底解析时，系统爬虫 SHALL 采用多选择器自适应兼容链（Multi-selector Fallback Chain）与正则表达式匹配特征技术。系统必须且 SHALL 精确过滤指向 `space.bilibili.com` 域名的 HTML 锚点（`<a>`）提取 UID（`mid`）与 UP主昵称，并使用正则精确匹配粉丝数值（支持“万”字换算）及提取个人签名，保障在新型 CSS 类名及 Module 属性变化下的数据提炼精度。

#### Scenario: 快速降级至 DOM 解析并自适应提取新版 HTML 数据
- **WHEN** 检索因 B站 反爬触发 WAF 阻断或接口在 2.5 秒内未响应，且页面以新型 CSS Module 扁平化布局渲染（如使用 `user-content`, `i_card_title`, `text_ellipsis` 等类名）
- **THEN** 系统秒级超时断开拦截器，优雅滑入 DOM 节点解析。通过寻找包含 `space.bilibili.com` 的 `<a>` 标签精确定位到 `mid` 为 `"1526435"`，`uname` 为 `"横川是川崽耶"`；同时利用正则匹配文本，成功提取并换算出粉丝数为 `58000`，并捕获到个人签名 `"吉尼斯纪录最小心眼保持者"`

### Requirement: 命令行自动同步指令
系统 SHALL 在 `coser` 管理命令组下提供 `sync-bili` 子命令，支持参数 `--limit`（单次同步上限数，以规避反爬风险）和 `--dry-run`（仅预览匹配结果，不写入数据库）。执行完毕后，控制台 SHALL 打印美观的高清彩显同步日志与结果表格。

#### Scenario: 运行同步指令并保存结果
- **WHEN** 用户在控制台运行 `python src/main.py coser sync-bili --limit 10`
- **THEN** 系统自动捞取数据库中前 10 个 `bilibili_uid` 为空的 active Coser，进行 B站 UP 主检索打分与自动绑定，最后通过数据库事务将更新持久化，并打印四色表格报告
