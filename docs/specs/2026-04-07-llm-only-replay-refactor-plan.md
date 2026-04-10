# LLM-Only Comparison and End-to-End Replay Refactor Plan

**版本**: 1.0  
**日期**: 2026-04-07  
**状态**: Proposed  
**目标**: 在不覆盖现有设计文档的前提下，为当前项目提供一份面向重构的落地方案。新方案放弃 `tool` 比对，统一收敛到 **LLM 比对**，并将 **端到端链路回放比对** 作为第一优先级。

---

## 1. 背景与结论

当前项目已经实现了一版“执行后自动比对”，但它的核心模型是：

- 场景基线以 `baseline_tool_calls` 为中心
- 过程比对以 `tool spans` 为主
- 最终结果比对只看最后一个 `llm span`
- 前端页面也围绕“工具调用比对”展开

这套实现和当前目标已经不一致。

当前重构目标明确为：

1. 不再做 `tool` 比对
2. 只保留 `LLM` 维度的过程比对和结果比对
3. 优先实现 **端到端链路回放比对**
4. 允许将当前 comparison 实现视为过渡代码，而不是长期兼容对象

**结论**：

- 这是一次 **替换式重构**，不是在现有 `tool-comparison` 上做增量增强
- 最优路径不是继续补旧 comparison，而是建立新的 **Replay 主线**
- MVP 应优先做 **Full Agent Replay**
- `step_fixed_input replay` 可以作为后续增强，不建议与第一期强绑定

---

## 2. 当前代码现状

### 2.1 已有能力

当前代码已经具备以下可复用能力：

- 可发起一次真实 Agent 执行
- 可记录 `execution_jobs`
- 可通过 `trace_id` 从 ClickHouse 拉取 spans
- 可从 trace 中提取 LLM spans、token、TTFT、TPOT 等指标
- 执行详情页已有 trace 展示和比对入口

这些能力意味着：**端到端 replay 不是从零开始**。

### 2.2 当前实现和目标的冲突点

#### 冲突一：基线模型仍以 `tool` 为中心

当前场景实体包含：

- `baseline_tool_calls`
- `process_threshold`
- `tool_count_tolerance`
- `enable_llm_verification`

这说明“过程比对”的设计中心仍然是工具调用，而不是 LLM 行为。

#### 冲突二：详细比对服务以 `tool spans` 为主

当前 `ComparisonService` 的过程比对逻辑：

- 从 trace 中筛 `tool_spans`
- 对 `tool_spans` 做次数检查、贪心匹配、相似度计算
- 最终得出 `process_score`

这和“只保留 LLM 比对”的目标直接冲突。

#### 冲突三：前端交互围绕工具比对展开

当前执行详情页展示：

- 工具调用比对列表
- 工具过程分数
- 工具基线内容

如果重构为 LLM-only，这一整块 UI 都应被替换，而不是继续演进。

#### 冲突四：当前数据模型还不适合完整 replay

当前 execution 侧只稳定保存了：

- `scenario.prompt`
- `trace_id`
- `original_response`
- 关联 `agent_id / scenario_id / llm_model_id`

但对“端到端 replay”真正需要的“运行快照”保存不足，例如：

- 原始请求结构快照
- 运行模式快照
- 对应 Agent 配置快照
- 用于回放的基准来源说明

所以 Full Replay 可以做，但第一期必须接受“真实重跑 + trace 对比”的定位，而不是“严格可重复模拟执行”。

---

## 3. 重构目标

### 3.1 产品目标

系统需要支持两件事：

1. 对一次已完成执行，重新发起一次真实 Agent 执行，并对 **新旧执行的 LLM trace** 做比对
2. 在场景层面维护 **LLM 基线**，并允许 replay 结果相对于该基线进行验证

### 3.2 技术目标

- 移除 `tool-comparison` 作为主路径
- 新增 `replay` 子系统作为主能力
- 基线统一收敛为 `LLM calls + final result`
- comparison 结果面向 replay 服务，而不是 execution 服务里的附属逻辑

### 3.3 非目标

以下内容不建议进入本次 MVP：

- 继续扩展 `tool` 对比能力
- 同时上线 `full_agent replay` 与 `step_fixed_input replay`
- 做严格 deterministic replay
- 支持复杂规则式忽略字段配置
- 支持批量回放

---

## 4. 目标架构

### 4.1 新主线

新主线应为：

1. 用户从某次执行详情页发起 replay
2. 系统创建 `replay_task`
3. 后台根据原 execution / scenario 发起一次新的真实 Agent 执行
4. 新 execution 完成后拉取新 trace
5. 将新 trace 的 `LLM spans` 与基准 trace / 基线做比对
6. 持久化 replay comparison 结果
7. 前端展示 replay 状态、比对结论、差异明细、性能指标

### 4.2 基准来源

建议支持两种基准来源：

- `reference_execution`
  说明：基准来自用户发起 replay 时当前选中的对照 execution trace
- `scenario_baseline`
  说明：基准来自场景中维护的 LLM 基线

两种模式的目标不同：

- `scenario_baseline`
  用于回答“这次 replay 是否仍然符合官方预期”
- `reference_execution`
  用于回答“这次 replay 是否复现了当前选中的那次对照执行”

MVP 建议同时支持两种模式，但**不做隐式比较基准默认推断**。

用户在点击“启动回放”时，必须显式选择：

- `scenario_baseline`
- `reference_execution`

这样可以避免产品语义模糊，也能避免“系统替用户决定比较对象”带来的误解。

### 4.3 执行来源与比较基准分离

需要明确区分两个概念：

- **执行来源**
  replay 总是从用户当前选中的 `original_execution` 出发，重新发起一次真实执行
- **比较基准**
  replay 完成后，拿什么数据作为 LLM 比较基准

本方案建议：

- 执行来源固定为 `original_execution`
- 比较基准由用户选择：
  - `scenario_baseline`
  - `reference_execution`

这意味着：

- 原 execution 总是 replay 的执行起点
- 只有当用户显式选择 `reference_execution` 作为比较基准时，系统才拉取原 execution trace 参与比较
- 用户选择 `scenario_baseline` 时，系统不拉原 execution trace 做比较判定

### 4.4 比对范围

统一只比较 `LLM spans`：

- 过程比对：比较所有 LLM span 的行为一致性
- 结果比对：比较最终一个 LLM span 的输出
- 性能对比：比较输入/输出 tokens、TTFT、TPOT 等聚合指标

`tool spans` 的处理方式：

- 仅用于完整链路展示
- 不参与最终打分
- 不参与 overall pass/fail 判定

---

## 5. 数据模型重构方案

## 5.1 `scenarios` 表

### 建议新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `baseline_llm_calls` | Text(JSON) | LLM 基线数组，元素结构为 `{name, input, output}` |
| `baseline_result` | Text | 最终基线输出 |
| `baseline_trace_id` | String nullable | 当前基线来源的 trace_id |
| `baseline_updated_at` | DateTime nullable | 当前基线最后一次被覆盖的时间 |
| `compare_enabled` | Boolean | 是否启用自动比对或 replay 后自动判断 |
| `llm_count_tolerance` | Integer | LLM 调用次数容忍度 |

### 建议废弃字段

以下字段进入废弃状态：

- `baseline_tool_calls`
- `process_threshold`
- `result_threshold`
- `tool_count_tolerance`
- `compare_process`
- `compare_result`
- `enable_llm_verification`

### 废弃策略

不建议第一天物理删除。建议分两步：

1. 代码层不再读取旧字段
2. 第二阶段通过 migration 删除旧字段

这样可以降低切换风险。

## 5.2 `execution_jobs` 表

建议保留现有表，但新增更适合 replay 的快照字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `request_snapshot_json` | Text(JSON) | 记录执行时的请求快照 |
| `run_source` | String | manual / replay |
| `parent_execution_id` | UUID nullable | replay 产生的新 execution 可回指原 execution |

说明：

- 这不是为了完全复刻远端 Agent 内部状态
- 而是为了让 replay 的行为来源更可解释

## 5.3 新表：`replay_tasks`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `original_execution_id` | UUID | 原始 execution |
| `scenario_id` | UUID nullable | 关联场景 |
| `baseline_source` | String | `reference_execution` / `scenario_baseline` |
| `llm_model_id` | UUID nullable | 指定 replay 使用的模型 |
| `status` | String | queued / running / pulling_trace / comparing / completed / failed |
| `new_execution_id` | UUID nullable | replay 产生的新 execution |
| `comparison_status` | String | pending / processing / completed / failed |
| `overall_passed` | Boolean nullable | 最终是否通过 |
| `error_message` | Text nullable | 错误信息 |
| `created_at` | DateTime | 创建时间 |
| `started_at` | DateTime nullable | 开始时间 |
| `completed_at` | DateTime nullable | 完成时间 |

这是 replay 的主实体。

补充说明：

- `original_execution_id` 表示 replay 的执行起点
- `baseline_source` 表示 replay 完成后采用哪种比较基准
- 二者不应混为一个概念

`baseline_source` 建议定义为枚举字段：

| 枚举值 | 含义 |
|------|------|
| `scenario_baseline` | 使用场景中保存的 `baseline_llm_calls` 和 `baseline_result` 作为比较基准 |
| `reference_execution` | 使用当前选中的对照 execution 的 LLM trace 作为比较基准 |

建议在各层统一采用同一套枚举值，避免字符串漂移：

### 数据库层

- 字段名：`baseline_source`
- 类型建议：`String` 或数据库原生 `ENUM`
- 推荐值：
  - `scenario_baseline`
  - `reference_execution`

### 后端领域层

建议新增枚举：

```python
class ReplayBaselineSource:
    SCENARIO_BASELINE = "scenario_baseline"
    REFERENCE_EXECUTION = "reference_execution"
```

如果项目后续会强化类型约束，也可以直接使用 Python `Enum`：

```python
from enum import Enum

class ReplayBaselineSource(str, Enum):
    SCENARIO_BASELINE = "scenario_baseline"
    REFERENCE_EXECUTION = "reference_execution"
```

### Pydantic / API 层

请求模型建议直接约束为枚举，而不是裸字符串：

```python
class CreateReplayRequest(BaseModel):
    original_execution_id: UUID
    baseline_source: ReplayBaselineSource
    llm_model_id: UUID | None = None
```

这样可以保证：

- 非法值在 API 入参阶段直接被拒绝
- 避免服务层写重复校验逻辑

### 前端 TypeScript 层

建议统一定义：

```ts
export type ReplayBaselineSource =
  | 'scenario_baseline'
  | 'reference_execution'
```

发起 replay 的请求类型建议写成：

```ts
export interface CreateReplayRequest {
  original_execution_id: string
  baseline_source: ReplayBaselineSource
  llm_model_id?: string
}
```

### 前端展示文案映射

建议不要在 UI 直接显示枚举值，而是单独维护展示映射：

```ts
export const REPLAY_BASELINE_SOURCE_LABEL: Record<ReplayBaselineSource, string> = {
  scenario_baseline: '跟场景基线比较',
  reference_execution: '跟当前执行比较',
}
```

这里建议前端文案使用“跟当前执行比较”，比“跟 reference execution 比较”更自然。

### 服务层分支建议

服务层不要到处散落字符串判断，建议统一封装：

```python
if replay_task.baseline_source == ReplayBaselineSource.SCENARIO_BASELINE:
    ...
elif replay_task.baseline_source == ReplayBaselineSource.REFERENCE_EXECUTION:
    ...
```

### 非法值处理建议

- API 层：通过枚举约束直接拦截
- 数据库层：如果不是原生 ENUM，服务层写入前仍应使用枚举对象而不是裸字符串
- 前端层：表单提交前必须要求用户显式选择，不允许空值自动兜底

## 5.4 新表：`replay_comparison_results`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `replay_task_id` | UUID | 关联 replay task |
| `process_passed_count` | Integer nullable | 过程通过的 LLM 数量 |
| `process_total_count` | Integer nullable | 过程总 LLM 数量 |
| `result_passed` | Boolean nullable | 最终结果是否通过 |
| `overall_passed` | Boolean nullable | 总体是否通过 |
| `details_json` | Text | 比对详情 |
| `aggregated_metrics_json` | Text nullable | 聚合指标 |
| `status` | String | pending / processing / completed / failed |
| `error_message` | Text nullable | 错误信息 |
| `created_at` | DateTime | 创建时间 |
| `completed_at` | DateTime nullable | 完成时间 |

说明：

- 不建议继续复用当前 `comparison_results`
- replay comparison 是独立主线，语义更清晰

---

## 6. Replay 执行流程

### 6.1 MVP 流程

```text
用户在 ExecutionDetail 发起“端到端回放”
    ->
创建 replay_task(status=queued)
    ->
后台创建一个新的 execution_jobs(run_source=replay, parent_execution_id=原 execution)
    ->
复用当前执行调用链，真实调用 Agent
    ->
新 execution 完成
    ->
根据 baseline_source 决定比较基准提取方式
    ->
如果 baseline_source = reference_execution:
  拉取原 execution trace 和新 execution trace
如果 baseline_source = scenario_baseline:
  拉取新 execution trace，并从 scenario 读取 baseline_llm_calls / baseline_result
    ->
提取待比较的 LLM 数据
    ->
执行过程比对 + 结果比对 + 性能聚合
    ->
写入 replay_comparison_results
    ->
更新 replay_task(status=completed)
```

### 6.2 基准提取规则

#### 模式一：`scenario_baseline`

执行流程：

1. 从 `scenario.baseline_llm_calls` 读取过程基线
2. 从 `scenario.baseline_result` 读取结果基线
3. 拉取 replay 产生的新 execution trace
4. 提取新 trace 中的全部 LLM spans
5. 执行 LLM-only comparison

特点：

- 更轻量
- 更适合常规回归验证
- 不依赖原 execution trace 的可用性

#### 模式二：`reference_execution`

执行流程：

1. 拉取原 execution trace
2. 提取原 trace 中的全部 LLM spans 和最终结果
3. 拉取 replay 产生的新 execution trace
4. 提取新 trace 中的全部 LLM spans 和最终结果
5. 执行 LLM-only comparison

特点：

- 更适合复现某次历史执行
- 更利于定位行为漂移问题
- 调试价值更高

### 6.3 为什么复用 execution 主链

因为当前项目中最稳定的真实执行路径已经存在：

- 调用 Agent
- 获得 trace_id
- 拉取 trace

如果重新做一套 replay 专用执行器，短期会重复建设。

建议做法是：

- replay service 负责“调度和组织”
- 真正的 Agent 调用仍复用 execution service

### 6.4 replay 与 execution 的关系

建议模型关系如下：

- `replay_task.original_execution_id` 指向基准执行
- `replay_task.new_execution_id` 指向 replay 产生的新执行
- 新执行的 `parent_execution_id` 回指原执行

这样可以从两个方向追踪：

- 从 replay 看它生成了哪个 execution
- 从 execution 看它是否由 replay 产生

---

## 7. LLM 比对算法

### 7.1 基本原则

- 只比较 `llm spans`
- `tool spans` 不参与评分
- 最终结果只看最后一个 `llm span`
- 过程明细用于分析
- 最终通过判定由“计数一致性 + 最终结果一致性”决定

### 7.2 基线提取规则

从 trace 中筛出所有 `span_type = llm` 的 spans，按 `start_time` 排序，提取：

```json
[
  {
    "name": "llm_call_1",
    "input": "...",
    "output": "..."
  }
]
```

最终结果：

- 取最后一个 LLM span 的 output

### 7.3 匹配策略

MVP 建议采用：

- 同名优先
- 贪心最优匹配
- 只在 `llm spans` 范围内匹配

具体策略：

1. 先检查 `abs(actual_count - baseline_count) <= llm_count_tolerance`
2. 对每个实际 LLM span，在所有未匹配的基线 LLM span 中寻找最佳匹配
3. 名称不同可以直接降权，或 MVP 中直接视为不可匹配
4. 匹配成功后进行内容比对
5. 未匹配项直接记为失败

### 7.4 内容比对策略

沿用当前项目里已经验证过的两阶段思路，但作用对象换成 LLM：

1. JSON 预处理
2. Levenshtein 相似度粗筛
3. 高相似度直接通过
4. 低相似度调用 LLM 进行语义验证

### 7.5 最终判定

建议 `overall_passed` 规则如下：

- LLM 数量差异超出容忍度 -> 失败
- 最终结果比对失败 -> 失败
- 其他情况下 -> 通过

说明：

- 中间每一步 LLM 的过程结果要记录
- 但它们不单独构成“平均分阈值型”判定
- 这样比当前 `process_threshold/result_threshold` 更稳定、更可解释

---

## 8. 基线管理方案

### 8.1 场景基线

场景基线应改为：

- `baseline_llm_calls`
- `baseline_result`
- `baseline_trace_id`
- `baseline_updated_at`

### 8.2 设置基线方式

保留“从执行设置为基线”这个入口，但提取逻辑改为：

- 不再提取 `tool calls`
- 只提取全部 `llm spans`
- 保存最后一个 LLM span 的 output 到 `baseline_result`
- 保存本次来源 execution 的 `trace_id` 到 `baseline_trace_id`
- 保存本次覆盖时间到 `baseline_updated_at`

### 8.3 为什么仍保留场景基线

虽然 MVP 优先从 execution 发起 replay，但场景基线仍然有价值：

- 可以作为“官方预期版本”
- 可用于跨执行复用
- 可用于未来批量回归

### 8.4 基线模式选择策略

建议前端在“启动回放”弹窗中提供“比较基准”选项：

- `跟场景基线比较`
- `跟 reference execution 比较`

交互策略：

1. 用户点击“启动回放”时，必须显式选择比较基准
2. 系统不应在后台自动切换为另一种比较模式
3. 即使场景存在基线，也不默认替用户选择“跟基线比较”

校验规则：

- 用户选择 `scenario_baseline`，但场景没有任何 LLM 基线时，前端禁止提交，并提示先设置基线
- 用户选择 `reference_execution` 时，不依赖场景基线是否存在

---

## 9. API 重构方案

## 9.1 建议保留

- `GET /api/v1/execution/{id}`
- `GET /api/v1/execution/{id}/trace`
- `POST /api/v1/scenario/{id}/set-baseline/{execution_id}`

但 `set-baseline` 的语义要改为设置 **LLM baseline**。

## 9.2 建议新增

### 发起 replay

`POST /api/v1/replay`

请求体建议：

```json
{
  "original_execution_id": "uuid",
  "baseline_source": "reference_execution",
  "llm_model_id": "uuid or null"
}
```

字段说明：

- `original_execution_id`
  表示 replay 从哪次 execution 重新发起
- `baseline_source`
  表示 replay 完成后拿什么作为比较基准
  可选值：
  - `scenario_baseline`
  - `reference_execution`

### 获取 replay 详情

`GET /api/v1/replay/{id}`

返回：

- replay task 基本信息
- new execution 概览
- comparison 状态

### 获取 replay comparison 结果

`GET /api/v1/replay/{id}/comparison`

### 重新比对 replay 结果

`POST /api/v1/replay/{id}/recompare`

### 获取某条 execution 关联的 replay 列表

`GET /api/v1/execution/{id}/replays`

用途：

- 给 `ExecutionDetail` 页的“查看回放详情”入口使用
- 用于展示当前 execution 关联的多次 replay 摘要信息

建议返回字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | replay task id |
| `original_execution_id` | UUID | 原始 execution id |
| `new_execution_id` | UUID nullable | replay 生成的新 execution id |
| `baseline_source` | String | `scenario_baseline` / `reference_execution` |
| `status` | String | replay 状态 |
| `comparison_status` | String | comparison 状态 |
| `overall_passed` | Boolean nullable | 总体是否通过 |
| `llm_model_id` | UUID nullable | 本次 replay 使用的模型 |
| `llm_model_name` | String nullable | 模型名称，方便前端直接展示 |
| `created_at` | DateTime | 创建时间 |
| `started_at` | DateTime nullable | 开始时间 |
| `completed_at` | DateTime nullable | 完成时间 |
| `error_message` | Text nullable | 错误摘要 |

建议响应结构：

```json
[
  {
    "id": "uuid",
    "original_execution_id": "uuid",
    "new_execution_id": "uuid",
    "baseline_source": "reference_execution",
    "status": "completed",
    "comparison_status": "completed",
    "overall_passed": true,
    "llm_model_id": "uuid",
    "llm_model_name": "GPT-4o",
    "created_at": "2026-04-09T10:00:00Z",
    "started_at": "2026-04-09T10:00:03Z",
    "completed_at": "2026-04-09T10:01:12Z",
    "error_message": null
  }
]
```

## 9.3 建议废弃

以下接口建议进入废弃阶段：

- `GET /api/v1/execution/{id}/comparison`
- `POST /api/v1/execution/{id}/recompare`

原因：

- comparison 不再是 execution 的附属能力
- 新主线应当是 replay

---

## 10. 前端重构方案

### 10.1 ExecutionDetail 页面

建议调整为：

- 保留 trace 展示
- 将“比对详情”卡片改为“回放与对比”
- 保留“设为基线”
- 当前阶段保留原有“重新比对”按钮
- 当前阶段新增“查看回放详情”按钮

按钮语义区分：

- `重新比对`
  继续走现有 comparison 主线，只对当前已有执行结果重新计算比对结论
- `查看回放详情`
  用于查看当前 execution 关联的 replay 记录，不直接发起新的 replay

阶段性策略：

- 在 replay 主线稳定前，详情页继续保留旧“重新比对”按钮
- `ExecutionDetail` 页不作为“启动回放”的主入口
- 详情页承担“查看 replay 历史和跳转详情”的辅助入口

“查看回放详情”交互建议：

- 点击后展开一个回放记录区域，或打开抽屉/折叠面板
- 展示当前 execution 关联的 replay 列表
- 每条 replay 记录展示：
  - replay 状态
  - 比较基准
  - overall_passed
  - 创建时间
  - 新 execution 跳转入口
  - 回放详情跳转入口
- 支持查看多次 replay，不只展示最近一次

### 10.2 ExecutionList 页面

测试执行列表页应作为“启动回放”的主入口。

建议调整为：

- 在每条执行记录的“操作”列新增 `回放` 或 `启动回放` 按钮
- 按钮点击后打开回放配置弹窗
- 当前行对应的 execution 作为 `original_execution_id`

启动回放弹窗建议新增：

- LLM 模型选择
- 比较基准选择
  - 跟场景基线比较
  - 跟当前执行比较

交互要求：

- 比较基准为必选项
- 不做自动兜底切换
- 用户提交前应明确知道本次 replay 将按哪种基准判定
- 如果某些状态不允许发起回放，需要在操作列禁用按钮并给出原因说明

### 10.3 新增 ReplayDetail 页面

页面职责：

- 展示 replay task 状态
- 展示原 execution 与 replay execution 的关联
- 展示聚合指标对比
- 展示完整链路中的 LLM 对比详情
- 可跳转到 replay 生成的新 execution 详情页

补充说明：

- `ExecutionDetail` 页中的“查看回放详情”入口主要用于查看某条 execution 的 replay 历史
- 单条 replay 的完整信息仍由 `ReplayDetail` 页面承载

建议 `ReplayDetail` 首屏字段：

- replay id
- 原 execution id
- 新 execution id
- baseline source
- replay status
- comparison status
- overall passed
- llm model name
- created_at / started_at / completed_at
- error_message

除首屏摘要外，`ReplayDetail` 还需要完整链路展示能力。

原则如下：

- `tool spans` 不参与 comparison 判定
- `tool spans` 必须参与链路展示
- 页面既要回答“这次回放是否通过”，也要回答“这次回放内部到底发生了什么”

建议 `ReplayDetail` 接口补充两套 trace 数据：

- `original_trace`
  - `trace_id`
  - `spans`
- `replay_trace`
  - `trace_id`
  - `spans`

每个 `span` 建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `span_id` | String | span 唯一标识 |
| `span_type` | String | `llm` / `tool` / 其他 |
| `name` | String | span 名称 |
| `start_time_ms` | Integer nullable | 开始时间 |
| `end_time_ms` | Integer nullable | 结束时间 |
| `duration_ms` | Integer nullable | 耗时 |
| `input` | Text nullable | 输入 |
| `output` | Text nullable | 输出 |
| `ttft_ms` | Float nullable | LLM 首 token 时间，仅 LLM 使用 |
| `tpot_ms` | Float nullable | LLM token 输出间隔，仅 LLM 使用 |
| `input_tokens` | Integer nullable | LLM 输入 token，仅 LLM 使用 |
| `output_tokens` | Integer nullable | LLM 输出 token，仅 LLM 使用 |

页面结构建议补充为：

1. 回放任务信息
2. LLM 比对结论
3. 聚合指标对比
4. 原始执行全链路
5. 回放执行全链路

其中：

- `原始执行全链路` 按时间顺序展示原 execution 内部的 `llm + tool` spans
- `回放执行全链路` 按时间顺序展示 replay 生成的新 execution 内部的 `llm + tool` spans
- `tool` 仅展示，不打分
- `llm` 既参与展示，也参与 comparison

### 10.4 页面结构建议

1. 回放任务信息
2. 新旧 execution 概览
3. 聚合指标对比
4. 总体判定
5. LLM spans 详细对比
6. 完整 trace 链路展示

### 10.5 UI 范式建议

前端不再展示：

- 工具调用基线
- 工具次数容忍度
- 过程阈值
- 结果阈值

前端改为展示：

- LLM count tolerance
- 过程通过数 / 总数
- 最终结果是否通过
- overall_passed

---

## 11. 分阶段实施计划

## 第一阶段：建立新数据模型和 replay 骨架

目标：

- 新建 replay 表
- 新增 replay API
- 新增 replay service
- 新增 ReplayDetail 页面骨架
- 新增 `baseline_source` 选择逻辑

暂时不删旧 comparison 代码。

## 第二阶段：完成 Full Agent Replay 主链

目标：

- replay 能创建新的 execution
- 能等待 execution 完成
- 能根据 `baseline_source` 拉取或读取比较基准
- 能完成 LLM-only comparison

这是 MVP 的核心交付。

## 第三阶段：切换前端主入口

目标：

- ExecutionDetail 以 replay 为主
- 弱化现有 comparison 区块
- 新增 ReplayDetail 完整展示页

## 第四阶段：清理旧 comparison 逻辑

目标：

- 删除 tool comparison 相关服务逻辑
- 删除旧 comparison API
- 删除旧字段
- 删除旧页面中的工具比对 UI

---

## 12. 风险与应对

### 风险一：Full replay 不可完全复现

原因：

- 当前 Agent 是黑盒 HTTP 服务
- 本地并不掌握其完整运行时快照

应对：

- 文案上明确这是“端到端回放验证”，不是 deterministic replay
- 增加 execution request snapshot，提升可解释性

### 风险二：双基准模式增加用户理解成本

应对：

- 页面文案明确区分“回放起点”和“比较基准”
- 在启动弹窗中简短解释两个模式的用途
- 要求用户显式选择比较基准，避免隐式默认造成误解

### 风险三：旧 comparison 和新 replay 并存期会混乱

应对：

- 明确新能力主入口是 replay
- 旧 comparison 仅保留短期兼容，不再继续演进

### 风险四：一次性删旧字段可能影响现网

应对：

- 先停用读取
- 后迁移删除

### 风险五：前端页面切换期用户理解成本高

应对：

- 将“重新比对”统一改名为“启动回放”
- 页面用语统一成“原始执行 / 回放执行 / 比较基准 / LLM 对比”

---

## 13. 推荐的落地决策

本次重构建议采用以下明确决策：

1. **放弃继续建设 tool comparison**
2. **Replay 成为主能力，comparison 成为 replay 的子能力**
3. **MVP 只做 Full Agent Replay**
4. **回放时允许选择比较基准：场景基线或 reference execution trace**
5. **场景基线统一收敛为 LLM baseline**
6. **旧 comparison_results 不作为新主线复用对象**
7. **先并存、后删除旧字段与旧接口**

---

## 14. 后续可扩展方向

以下内容建议在 MVP 完成后再评估：

- `step_fixed_input replay`
- 忽略随机字段规则
- 批量 replay
- replay 结果导出
- 更优匹配算法
- 基于场景基线的批量回归验证

---

## 15. 最终建议

如果当前目标是“为项目建立长期可演进的 Agent 回放验证能力”，那么最值得做的不是继续打磨现有 `tool` 比对，而是：

- 以 **LLM-only** 统一比对模型
- 以 **Full Agent Replay** 作为主产品能力
- 以 **新 replay 数据模型** 替换旧 comparison 设计中心

这条路径和当前需求最一致，也比在旧模型上继续打补丁更容易收敛。
