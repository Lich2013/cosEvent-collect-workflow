# coser-candidates Specification

## Purpose
TBD - created by archiving change fix-candidate-platform-mapping. Update Purpose after archive.
## Requirements
### Requirement: 候选人来源平台与引用记录
系统必须且 SHALL 在自动提取和更新 Coser 候选人（candidates）时，正确识别并记录原始博文的平台（platform，如 weibo, bilibili, xhs）与原始博文的网页 URL 引用（source_ref），避免硬编码或篡改来源信息。

#### Scenario: 微博博文自动提取注册候选人并保留来源平台
- **WHEN** 对一条微博博文内容提取 @ 提及的候选人并保存时
- **THEN** 数据库 `coser_candidates` 表中对应的新增候选人记录其 `platform` 字段为 `'weibo'`，且 `source_ref` 为该微博的 URL

### Requirement: 微博候选人 UID 与简介自动解析对齐
系统必须且 SHALL 对微博平台来源（`platform='weibo'`）的待验证候选人，在验证阶段通过请求微博官方 AJAX 接口（`https://weibo.com/ajax/profile/info?screen_name={nickname}`）进行昵称解析。解析成功后，系统必须提取其数字 UID (`idstr`) 和个人简介（`description`），并暂存为匹配候选。

#### Scenario: 成功解析微博候选人昵称并提取 UID 与个人简介
- **WHEN** 验证状态为 `pending` 且平台为微博的候选人 `"小沂Alter"` 时
- **THEN** 系统发起接口查询，成功获取该用户的微博 UID `"7188636063"` 和简介，且整个过程无需冷启动完整浏览器进行 DOM 渲染

### Requirement: 微博候选人名字后缀清洗
系统在进行 B 站跨平台检索前，必须且 SHALL 对提取出的微博候选人昵称执行后缀裁剪预处理，剥离常见的平台专属及二次元后缀（如以下划线开头的 `_cos`, `_Coser`, `_ShiratoriK` 等常见模式或末尾下划线），以防止 B 站检索失败。

#### Scenario: 包含专属后缀的名字搜索前被成功清洗
- **WHEN** 准备在 B 站检索微博候选人 `"北川白鸟_ShiratoriK"` 时
- **THEN** 系统自动将其清洗裁剪为 `"北川白鸟"`，并将其作为关键词在 B 站发起 UP 主搜索

### Requirement: 跨平台双向绑定确权与属性双重过滤
在二次元属性及 Coser 资格检验中，系统必须且 SHALL 支持双重判定机制：只要候选人通过了微博 Bio 的二次元关键词检测，**或者**通过了 B 站 UP 主对齐和 B 站简介检测，即视为检验通过。系统在保存验证成功的记录时，必须且 SHALL 同时将匹配成功的 `matched_bili_uid` 与 `matched_weibo_uid` 写入到候选人表中。

#### Scenario: 通过微博 Bio 判定为 Coser 并成功双向绑定
- **WHEN** 微博候选人 `"小沂Alter"` 的微博简介包含二次元关键词，或在 B 站成功匹配对齐
- **THEN** 该候选人成功通过属性校验，且候选人记录中同时被绑定写入了微博 UID `"7188636063"` 和对齐的 B 站 UID

### Requirement: 候选人博文抓取与物理隔离存储
对于已获取平台 UID 且未完成核验的 pending 状态候选人（`status = 'pending' AND is_verified = 0`），系统在执行验证任务时，必须且 SHALL 增量抓取其对应平台的最新 3~5 条博文文本，并将数据安全地存储在独立的候选人物化原始博文表 `candidate_raw_posts` 中，绝不能写入正式追踪的 `raw_posts` 表中。

#### Scenario: 成功爬取候选人微博博文并物理隔离写入 candidate_raw_posts
- **WHEN** 执行候选人核验任务，候选人 `"小沂Alter"` 拥有微博 UID `"7188636063"` 且尚未被核验时
- **THEN** 系统爬取其最新 3 条微博正文，并将其写入 `candidate_raw_posts` 中，正式的 `raw_posts` 表保持无污染

### Requirement: 博文纯文本 LLM 智能体分类核验
系统在抓取候选人近期博文文本后，必须且 SHALL 构造并调用纯文本核验智能体 `CandidateVerifyAgent`。该智能体依据指定的 Pydantic 强契约结构化输出格式评估该博文列表。若判定结果为活跃 Coser，则将该候选人的验证状态更新为 `is_verified = 1`，并在 `verify_reason` 中记录判定的核心理由；若判定不通过，则将候选人的 `status` 直接标记为 `ignored`。

#### Scenario: 智能体通过博文判定候选人为 Coser 并记录原因
- **WHEN** 核验智能体读取到候选人 `"小沂Alter"` 的博文内容包含 "CP30第一天芙宁娜返图..." 时
- **THEN** 智能体判定 `is_active_coser` 为 `True`，将 `coser_candidates` 的 `is_verified` 更新为 `1`，且 `verify_reason` 写入 "最近博文中含有CP30返图"

#### Scenario: 智能体判定候选人为非 Coser 并标记为忽略
- **WHEN** 核验智能体读取到候选人 `"用户123"` 的博文仅包含日常琐事且无任何 Cosplay 活动迹象时
- **THEN** 智能体判定 `is_active_coser` 为 `False`，将 `coser_candidates` 的 `status` 更新为 `'ignored'`

### Requirement: 终端列表直观展示核验依据
系统在终端列出候选人列表时，必须且 SHALL 在渲染表格中完整展现核验判定结果和 LLM 理由字段 `verify_reason`，以供用户在决定是否手动批准晋升时进行高效率的主观参考。

#### Scenario: 终端以表格形式高亮展示通过核验的候选人及理由
- **WHEN** 运行终端命令 `python src/main.py coser list-candidates` 时
- **THEN** 表格中包含核验状态与理由列，高亮呈现已核验（`is_verified = 1`）的候选人记录，并清晰展示其 `verify_reason` 内容

