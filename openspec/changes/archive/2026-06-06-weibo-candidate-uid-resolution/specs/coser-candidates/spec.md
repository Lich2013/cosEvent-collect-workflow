## ADDED Requirements

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
