# Cosplay 活动分析收集系统：Agent 编码与运行规范 (AGENTS.md)

本文件规定了本项目中大语言模型智能体（Agent）的开发标准、输入输出契约契合度、可观测性架构以及健壮性重试降级规范。所有参与本项目的开发者必须且 SHALL 严格遵守本规范。

---

## 1. 核心设计原则

### 1.1 官方原生范式优先 (Official SDK First)
- **要求**：必须直接采用官方原生 `openai-agents` SDK 进行 Agent 实例化和执行（基于 `from agents import Agent, Runner, ModelSettings`）。
- **禁止**：严禁自行编写多余的 Prompt 拼接器、手动大模型循环调度器等“重复造轮子”的第三方逻辑。

### 1.2 职责单一原则 (Single Responsibility)
- **要求**：Agent 的职责仅限于**语义决策、文本流编排和多维结构化数据提炼**。
- **限制**：Agent 使用的所有 Tool（如数据库读写、Playwright 页面数据拦截抓取）必须抽离在 Tool 函数中（通过 `@function_tool` 定义）。Tool 仅提供纯净的数据交互，严禁在 Agent System Prompt（`instructions`）中塞入爬虫或 SQL 建表等逻辑。

---

## 2. 强契约输入/输出约束 (Schema First)

- **强约束输出**：每个 Agent 在声明时必须指定 `output_type` 属性，且该属性必须是一个继承自 `pydantic.BaseModel` 的强类型模型。
- **去幻觉规范**：在定义活动提炼 Pydantic 模型（`CosEvent`）时，**严禁且 SHALL NOT** 声明 `coser_name` 字段以防 LLM 产生幻觉。Coser 昵称应由数据库业务层（`DBService`）在事务插入阶段，根据 `raw_posts` 的 `coser_id` 物理联查 `cosers.name` 自动注入。

```python
# Pydantic 强类型输出范式示例
from pydantic import BaseModel, Field
from typing import List, Optional

class CosEvent(BaseModel):
    event_name: str = Field(..., description="活动名称，例如 CP30")
    event_date: str = Field(..., description="活动日期，格式必须为 YYYY-MM-DD。如果未知，则写'未知'")
    event_place: str = Field(..., description="活动城市与具体场馆")
    event_description: Optional[str] = Field(None, description="Coser 具体日程或扮演角色")
    confidence: float = Field(..., description="置信度评分，0.0 到 1.0 之间")
    event_type: str = Field(default="漫展", description="活动类型，必须为: '漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售'")
    source_url: str = Field(..., description="来源博文 URL 地址")

class FinalOutput(BaseModel):
    event_list: list[CosEvent] = Field(..., description="格式化的 Cosplay 活动列表")

class TriageOutput(BaseModel):
    """首轮预检分流强契约模型"""
    has_event: bool = Field(..., description="博文中是否包含未来漫展/排班计划")
    candidate_events: List[str] = Field(default=[], description="未来活动主题候选名称列表")

class FusionJudgeOutput(BaseModel):
    """超级漫展同义融合裁判智能体输出契约"""
    is_same: bool = Field(..., description="事件A与事件B是否为同一个二次元活动")
    confidence: float = Field(..., description="置信度评分，0.0 到 1.0 之间")
    reason: str = Field(..., description="判定的核心依据与逻辑推理理由")

class CandidateVerifyOutput(BaseModel):
    """候选人博文纯文本核验智能体输出契约"""
    is_active_coser: bool = Field(..., description="根据近期的博文判断该博主是否为活跃的 Coser")
    confidence: float = Field(..., description="置信度评分，0.0 到 1.0 之间")
    reason: str = Field(..., description="判定理由，结合博文中的证据简短描述")
```

---

## 3. Prompts 动态模板规范

- **管理方式**：System Prompt / Instructions 严禁在 Python 代码中硬编码，必须统一放置在 `config/templates/` 目录下进行版本跟踪，当前系统内含以下四个核心模板文件：
    *   `event_analysis.jinja2`：用于增量提取博文中的漫展/活动日程。
    *   `event_consensus_judge.jinja2`：用于多模型共识判定下的最终金牌裁判。
    *   `event_fusion_judge.jinja2`：用于超级漫展同义名称与重名合并判定。
    *   `candidate_verify.jinja2`：用于待核验候选人的博文文本二次元活跃特征判定。
- **系统时间与发表日期动态注入**：在运行提取与核验任务时，必须使用 Jinja2 模板动态注入**当前系统参考时间**（格式 `YYYY-MM-DD`）以及**博文发表日期时间**（`published_at`），使 LLM 能够准确相对推算年份、并绝对过滤已发生的过期历史活动。

---

## 4. 容错重试与降级机制

大模型在处理高噪声社交媒体动态时，极易产生非标准 JSON 或类型缺失。必须设计多层防崩溃屏障：
1.  **自动重试 (Auto-Retry)**：当 Pydantic 校验抛出验证异常（`ValidationError`）或 LLM 返回非法格式时，系统必须捕获异常，并在记录警告日志后，将上一轮的报错描述作为系统反馈附加到上下文中，自动重新发起调用。重试上限必须设置为 **3 次**。
2.  **优雅跳过**：若 3 次重试全部失败，系统必须优雅记录 `ERROR` 审计日志，将对应博文的错误记录在案，并**继续处理下一条增量博文**，绝对不允许阻断主 CLI 定时进程。
3.  **原子性事务保障**：博文的活动入库与 `raw_posts.is_analyzed` 状态的更新，必须且 SHALL 包裹在同一个数据库 SQL 事务中执行。事务中任何一部分报错，必须执行 `ROLLBACK`，避免数据部分写入或丢失。
4.  **共识裁决与裁判旁路 (Consensus & Judge Bypass)**：
    *   在共识模式下，首轮 **Triage Agent** 必须声明 `output_type=TriageOutput`。若 `has_event` 为 `False`，必须**立即截断流水线**，不再调用提取器及裁判以节省 API 费用。
    *   在并行提取阶段，若所有提取器产出的候选事件列表皆为空，系统必须**自动旁路（Bypass）裁判智能体**直接安全返回空列表。
    *   在提取器仅有一个运行成功时，系统必须降级为“单侧信任模式”，**自动旁路裁判智能体**以降低二次 API 开销。
5.  **软状态机与值域校验防御**：
    *   在 `cosplay_events` 表中管理软状态机时，状态值必须且 SHALL 被硬锁死在 `('未开始', '已结束', '已取消')` 三个枚举内。
    *   数据库物理建表必须包含 `CHECK` 约束；同时应用层在保存事务前，必须且 SHALL 在进入事务前通过嵌套辅助函数（`validate_status`）执行值域断言，防止非标状态写入。
6.  **智能旁路闸门加固与动态黑名单配置**：
    *   极简旁路黑名单必须且 SHALL 从代码中完全移出，统一配置在 `config/settings.yaml` 中的 `bypass_generic_names` 数组下，并在程序中动态热加载。
    *   在旁路闸门判断中，针对城市名前缀检测，必须且 SHALL 严密检测并剥离地级市前缀以提取基础词进行精准黑名单核验，严防带前缀的极简日程发生坍塌合并。
7.  **增量分析三态状态机与结构性失败隔离**：
    *   数据库 `raw_posts.is_analyzed` 状态应按照三态进行管理，彻底规避结构性异常导致的死循环：
        *   `0`：未分析（默认，调度检索过滤源）；
        *   `1`：分析并成功入库（含博文无日程的空列表情况）；
        *   `2`：分析异常挂起隔离。
    *   **异常分流机制**：发生暂时性网络超时或 API 抖动等暂时性异常时，保持 `is_analyzed = 0` 以便重试；若发生 Pydantic `ValidationError`、`AssertionError` 或数据校验及 `IntegrityError` 等永久性/结构性硬异常，系统主事务必须 `ROLLBACK`，并开启一个独立的数据库事务将 `is_analyzed` 标记为 `2` 进行安全熔断隔离。
8.  **读写强事务锁包覆规约**：
    *   在执行保存提取结果的数据库事务中（`save_extracted_events_transactional`），为了在并发调度中杜绝读写时间真空期产生的脏读和主键/别名冲突，系统必须在进入 `with conn:` 上下文后立即执行 `BEGIN IMMEDIATE;` 升级为强写锁。所有的历史日程查询和别名比对 `SELECT` 必须包裹在写锁内进行。
9.  **活动类型值域断言校验**：
    *   系统在将活动持久化入库或更新前，必须通过应用层嵌套辅助函数 `validate_type` 校验 `event_type` 属性，确保其值完全处于 `('漫展', '一日店长', '摄影会', '受邀模特', '快闪/签售')` 值域内，形成与数据库底层 `CHECK` 约束对应的双重防御。

---

## 5. 可观测性追踪 (Observability)

- **本地 Langfuse 连接自检**：在 CLI 程序启动时，系统必须先进行 `Langfuse().auth_check()` 连通性测试。
- **自动全局插桩**：自检成功后，系统必须调用 `OpenAIAgentsInstrumentor().instrument()` 对大模型运行时执行流、思维链（Thinking Process）及 Tool Calls 进行无缝追踪上报。
- **零干扰降级**：若本地 Langfuse 未启动或连通失败，系统必须输出黄色 `WARNING` 并**跳过插桩注册**，全面自动降级到本地结构化文件日志 `runtime/logs/cosevent.json.log`，不得因监控缺失引发运行时崩溃。
- **DeepSeek 传输层拦截降级与安全熔断**：
    *   由于非 OpenAI 供应商（如 DeepSeek）不支持原生 `json_schema` 强输出协议，系统在注册客户端时，必须且 SHALL 挂载自定义的 `DeepSeekTransport`。
    *   该拦截器必须在通信底层透明拦截请求：若包含 `json_schema`，自动提取 Schema 并转义拼接注入 System Message 尾部，同时将 `response_format` 降级改写为 `{"type": "json_object"}`。
    *   在反序列化重组 payload 时，**必须且 SHALL** 设置 `json.dumps(payload, ensure_ascii=True)`，强制将中文字符转义为纯 ASCII 序列以杜绝 HTTP `Content-Length` 多字节长度不匹配产生的网络死锁。
    *   改写拦截体内部必须使用 `try-except` 结构进行健壮包裹，若发生任何异常，自动安全熔断回退，将原始请求无损转发，绝对不允许传输层报错阻断智能体运行。

---

## 6. 候选人智能体核验与状态流转 (Candidate Verification)

候选人（Coser Candidates）发现与核验涉及专用的智能体规则，开发中必须严格遵循以下状态及核验逻辑：
1.  **强词免检索绿色通道**：当候选人简介/认证信息命中二次元强特征词（如 `cos`, `cosplay`）时，系统必须直接将 `is_verified` 设为 `1`，无需抓取博文或调用核验智能体。
2.  **弱特征/无特征 LLM 核验**：对于未命中强特征的候选人，系统会增量抓取其博文文本（具体抓取深度为：命中弱特征词的抓取前 10 条，其余抓取前 3 条）并传入核验智能体（`CandidateVerifyOutput`）进行判定。
3.  **置信度自适应软状态机**：
    *   若核验智能体判定 `is_active_coser` 为 `True`，系统将 `is_verified` 更新为 `1`。
    *   若判定为 `False`：
        *   若 `confidence >= 0.8`：代表高度确信其非 Coser，将 `status` 设为 `'ignored'`（硬忽略），并物理删除该候选人在 `candidate_raw_posts` 中的临时博文。
        *   若 `confidence < 0.8`：代表信息不足或判断模糊，将 `status` 设为 `'undetermined'`（待定状态），清除其临时博文，并开启 7 天冷却计数，冷却期内不重复参与自动核验。
