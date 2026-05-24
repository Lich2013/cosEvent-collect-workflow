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

class CosEvent(BaseModel):
    event_name: str = Field(..., description="活动名称，例如 CP30")
    event_date: str = Field(..., description="活动日期，格式必须为 YYYY-MM-DD")
    event_place: str = Field(..., description="活动城市与具体场馆")
    event_description: str = Field(..., description="Coser 具体日程或扮演角色")
    confidence: float = Field(..., description="置信度评分，0.0 到 1.0 之间")
    source_url: str = Field(..., description="来源博文 URL 地址")

class FinalOutput(BaseModel):
    event_list: list[CosEvent] = Field(..., description="格式化的 Cosplay 活动列表")
```

---

## 3. Prompts 动态模板规范

- **管理方式**：System Prompt / Instructions 严禁在 Python 代码中硬编码，必须统一放置在 `config/templates/` 目录下（如 `event_analysis.jinja2`）进行版本跟踪。
- **系统时间动态注入**：在运行提取任务时，必须使用 Jinja2 模板动态注入**当前系统时间**作为环境参数（格式 `YYYY-MM-DD`），使 LLM 能够准确判断并绝对过滤已发生的过期历史活动。

---

## 4. 容错重试与降级机制

大模型在处理高噪声社交媒体动态时，极易产生非标准 JSON 或类型缺失。必须设计三层防崩溃屏障：
1.  **自动重试 (Auto-Retry)**：当 Pydantic 校验抛出验证异常（`ValidationError`）或 LLM 返回非法格式时，系统必须捕获异常，并在记录警告日志后，将上一轮的报错描述作为系统反馈附加到上下文中，自动重新发起调用。重试上限必须设置为 **3 次**。
2.  **优雅跳过**：若 3 次重试全部失败，系统必须优雅记录 `ERROR` 审计日志，将对应博文的错误记录在案，并**继续处理下一条增量博文**，绝对不允许阻断主 CLI 定时进程。
3.  **原子性事务保障**：博文的活动入库与 `raw_posts.is_analyzed = 1` 状态的更新，必须且 SHALL 包裹在同一个数据库 SQL 事务中执行。事务中任何一部分报错，必须执行 `ROLLBACK`，避免数据部分写入或丢失。

---

## 5. 可观测性追踪 (Observability)

- **本地 Langfuse 连接自检**：在 CLI 程序启动时，系统必须先进行 `Langfuse().auth_check()` 连通性测试。
- **自动全局插桩**：自检成功后，系统必须调用 `OpenAIAgentsInstrumentor().instrument()` 对大模型运行时执行流、思维链（Thinking Process）及 Tool Calls 进行无缝追踪上报。
- **零干扰降级**：若本地 Langfuse 未启动或连通失败，系统必须输出黄色 `WARNING` 并**跳过插桩注册**，全面自动降级到本地结构化文件日志 `runtime/logs/cosevent.json.log`，不得因监控缺失引发运行时崩溃。
