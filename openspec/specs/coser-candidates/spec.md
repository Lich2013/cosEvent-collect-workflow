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
对于已获取平台 UID 且未完成核验的候选人（包含 `status = 'pending'` 与过期冷却状态为 `'undetermined'` 且 `is_verified = 0`），系统在执行验证任务时，必须且 SHALL 并发增量抓取其对应平台的博文文本，并将数据存储在隔离的原始博文表 `candidate_raw_posts` 中。
系统必须且 SHALL 执行**自适应抓取深度**：
1. 若候选人的 Bio（微博简介、认证或B站简介、认证）中命中了**二次元弱特征词**，则自适应抓取上限提升至 **10 条**（内存中切片过滤，防止日常信息挤占窗口）；
2. 其余无明显特征的普通候选人，抓取上限保持为 **3 条**。

#### Scenario: 成功爬取弱特征候选人博文且执行深抓取 10 条
- **WHEN** 执行候选人核验任务，候选人 `"小沂Alter"` 微博简介含有弱二次元词 "写真"，拥有微博 UID且尚未核验时
- **THEN** 系统发起抓取并将切片限制设定为 10 条，将抓取结果写入 `candidate_raw_posts`

#### Scenario: 普通候选人执行浅抓取 3 条
- **WHEN** 执行候选人核验任务，候选人 `"路人甲"` 无任何二次元特征，尚未核验时
- **THEN** 系统发起抓取并将限制设定为 3 条，写入 `candidate_raw_posts`

### Requirement: 博文纯文本 LLM 智能体分类核验
系统在抓取候选人近期博文文本后，必须且 SHALL 通过强弱关键词和 LLM 智能体完成分类评估。
系统必须且 SHALL 遵循以下判定及流转机制：
1. **强词优先匹配 (Strong Bio Match)**：若名字/简介命中了**二次元强特征词**（如 `cos`, `cosplay` 等），直接验证通过并将 `is_verified` 置为 `1`，无需执行博文爬取与 LLM 分析。
2. **弱词/无词 LLM 判定**：未命中强词（包括仅命中弱词或名字包含 cos 但 Bio 无强词）的候选人强制走 LLM 判定。
3. **软状态机过滤 (Undetermined)**：若 LLM 判定 `is_active_coser` 为 `False`：
   - 如果置信度评分 `confidence >= 0.8`，则直接判定不通过，将 `status` 标记为 `'ignored'`；
   - 如果置信度评分 `confidence < 0.8`（判定模糊/博文无证据），则判定为待定状态，将 `status` 标记为 `'undetermined'`，保留冷却，冷却期为 7 天。

#### Scenario: 强关键词命中直接验证通过并绕过 LLM
- **WHEN** 候选人 `"池咲misa"` 的 B站官方认证为 "知名Coser"（强词）时
- **THEN** 系统直接将 `is_verified` 设为 `1`，`verify_reason` 记为 "Bio 关键词匹配成功"，且不调用 LLM 及博文抓取

#### Scenario: LLM 核验失败且高置信度时标记为硬忽略
- **WHEN** 智能体判定候选人 `"用户123"` `is_active_coser` 为 `False` 且置信度为 `0.95` 时
- **THEN** 系统将该候选人 `status` 更新为 `'ignored'`，并物理清除其在 `candidate_raw_posts` 表中的所有临时博文

#### Scenario: LLM 判定模糊且低置信度时标记为待定软状态
- **WHEN** 智能体判定候选人 `"普通测试用户"` `is_active_coser` 为 `False` 且置信度仅为 `0.65` 时
- **THEN** 系统将该候选人 `status` 更新为 `'undetermined'`，物理清除其临时博文，开启 7 天冷却计数

### Requirement: 终端列表直观展示核验依据
系统在终端列出候选人列表时，必须且 SHALL 在渲染表格中完整展现核验判定结果和 LLM 理由字段 `verify_reason`，以供用户在决定是否手动批准晋升时进行高效率的主观参考。

#### Scenario: 终端以表格形式高亮展示通过核验的候选人及理由
- **WHEN** 运行终端命令 `python src/main.py coser list-candidates` 时
- **THEN** 表格中包含核验状态与理由列，高亮呈现已核验（`is_verified = 1`）的候选人记录，并清晰展示其 `verify_reason` 内容

### Requirement: B 站博文提及直连 UID 提取
系统在通过 B 站 gRPC 或 API 抓取原始动态时，必须且 SHALL 从动态的富文本节点（如 TextNode 的 LinkNode 链接控制信息）中，直接提取提及用户的 UID 与名称，避免仅依赖文本正则匹配，并无损地将此对齐信息随同候选人记录一起持久化保存。

#### Scenario: B 站动态直接提取提及并包含 pre-bound UID
- **WHEN** 抓取一条包含 `@艾西Aiwest` 动态提及的 B 站博文时
- **THEN** 系统直接解析出其对应的 B 站 UID `"5687638611"`，并将该 UID 作为 `matched_bili_uid` 预存写入 `coser_candidates`，且其状态为未验证（`is_verified = 0`）

### Requirement: B 站空间主页拦截核验机制
系统必须且 SHALL 对所有具有 `matched_bili_uid` 且未通过核验（`is_verified = 0`）的 pending 状态候选人，在验证阶段通过 Playwright 访问其空间主页 `space.bilibili.com/{uid}` 并拦截 `wbi/acc/info` 响应，获取其完整且未截断的个人签名与官方认证，执行 ACG 关键词校验。

#### Scenario: 拦截空间主页接口获取签名并通过 Coser 核验
- **WHEN** 对 pre-bound UID 为 `"5687638611"` 的候选人执行验证时
- **THEN** 系统使用 Playwright 加载其主页并截获接口，提取出其完整的个人简介，若简介包含二次元关键词，则将其验证状态标记为已核验（`is_verified = 1`）

### Requirement: 候选人数据库 is_verified 验证状态与热迁移
系统必须且 SHALL 在候选人表 `coser_candidates` 中完整支持 `is_verified` 验证字段与 `'undetermined'` 软状态（通过 CHECK 约束硬锁死在 `('pending', 'approved', 'ignored', 'undetermined')` 范围内）。在 CLI 启动时，系统必须且 SHALL 能够安全自动地对已存在的老版数据库进行影子表重构（DDL）热迁移，无损还原历史数据及字段。

#### Scenario: CLI 启动自动执行包含新状态约束的影子表热迁移升级
- **WHEN** 启动 CLI 命令行且检测到老数据库的 CHECK 约束不支持 `'undetermined'` 时
- **THEN** 系统通过自动执行影子表（Shadow Table）热重建事务，完成 `coser_candidates` 重建并迁移全量历史数据

