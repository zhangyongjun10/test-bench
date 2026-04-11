# 链路回放设计梳理：端到端重新执行版

**日期**：2026-04-10  
**状态**：Draft  
**关联历史文档**：

- `docs/specs/2026-04-07-llm-only-replay-refactor-plan.md`
- `docs/specs/2026-04-07-llm-only-replay-implementation-checklist.md`

## 1. 设计结论

本项目里的“链路回放”应定义为：

> 基于一次已有执行，重新触发一次 Agent 的完整 HTTP 调用，生成一条新的 execution 和新的 trace，然后将新 execution 的 LLM 调用次数、最终输出与选定基准进行比对。

因此需要明确区分三个动作：

- **查看 Trace**：只展示某条 execution 已经产生的 trace，不会重新执行 Agent。
- **重新比对**：不重新执行 Agent，只基于同一条 execution trace 换一个比对模型重新算 comparison。
- **链路回放**：必须重新执行 Agent，产生新的 execution、独立 session、新 trace 和新的比对结果。

后续页面和接口命名必须避免把“查看 Trace”和“链路回放”混用。

本期还必须明确并发和一致性边界：

- 同一个 original execution 允许并发发起多次链路回放。
- 同一次弹窗提交使用 `idempotency_key` 去重，避免重复点击创建重复回放。
- 每个 Replay Task 冻结自己的基准快照，后续场景基线变化不影响已创建的回放。
- 后台任务必须通过数据库状态抢占，避免同一个 Replay Task 被重复执行。
- 回放执行不走普通执行的自动比对逻辑，回放比对只能由 ReplayService 创建。

## 2. 当前已完成基础

当前执行后比对流程已经重构出了一些可复用能力：

- 每次执行会创建独立的 `execution_jobs`。
- 每次执行会生成独立 `user_session`，格式为 `exec_<execution_id.hex>`。
- Agent 调用已经统一为 OpenClaw 请求格式：

```json
{
  "model": "openclaw:main",
  "messages": [
    { "role": "user", "content": "场景 prompt" }
  ],
  "user": "exec_xxx"
}
```

- Trace 拉取已经支持 Opik / ClickHouse。
- Trace API 已经返回 `provider`、`input_tokens`、`output_tokens`。
- 比对逻辑已经收敛为 LLM-only：
  - 只统计 `provider=openai` 的 LLM spans。
  - 先检查 LLM 调用次数。
  - 再做最终输出算法粗筛。
  - 算法粗筛不通过时才调用 LLM 做语义判断。
- 同一 execution 已支持多次 comparison history。

这些能力在回放实现中复用，但当前缺少一个真正的 Replay 主实体来表达“由某次执行触发的新执行”。

## 3. 核心概念

### 3.1 原始执行 Original Execution

用户选择要回放的那次历史执行。

它提供：

- 被测 Agent。
- 测试场景。
- 场景 prompt。
- 原始 trace。
- 原始最终输出。
- 可选：作为 reference baseline 的 LLM 调用次数和最终输出。

### 3.2 回放执行 Replay Execution

链路回放重新触发 Agent 后生成的新 execution。

它必须满足：

- 使用同一个 Agent。
- 使用同一个测试场景 prompt。
- 使用新的 execution id。
- 使用新的独立 `user_session`。
- 使用新的 trace id。
- 真实调用 Agent HTTP 接口。
- 完成后正常拉取 trace、提取指标、执行 LLM-only 比对。

Replay Execution 本质上仍是 `execution_jobs` 中的一条记录，但需要能回指原始执行。

### 3.3 回放任务 Replay Task

Replay Task 用来表达“这次回放动作”的生命周期。

它连接：

- 原始执行 `original_execution_id`。
- 回放执行 `replay_execution_id`。
- 比较基准 `baseline_source`。
- 比对模型 `llm_model_id`。
- 回放状态与错误信息。
- 幂等键 `idempotency_key`。
- 基准快照 `baseline_snapshot_json`。

如果没有 Replay Task，页面只能看到两条普通 execution，无法知道它们之间的“回放关系”。

### 3.4 基准快照 Baseline Snapshot

创建 Replay Task 时必须冻结本次比对基准，写入 `baseline_snapshot_json`。

`scenario_baseline` 模式快照：

```json
{
  "source": "scenario_baseline",
  "baseline_output": "...",
  "expected_min": 3,
  "expected_max": 4,
  "scenario_id": "uuid"
}
```

`reference_execution` 模式快照：

```json
{
  "source": "reference_execution",
  "baseline_output": "...",
  "expected_min": 3,
  "expected_max": 3,
  "original_execution_id": "uuid",
  "original_trace_id": "019d..."
}
```

回放比对只能读取该快照，不再读取可能已经变化的场景基线或原始 trace 作为判定基准。

### 3.5 比较基准 Baseline

回放执行完成后，需要明确和谁比较。

本期固定支持两种基准：

- `scenario_baseline`：和场景维护的基线输出比较。
- `reference_execution`：和原始执行的 trace / 输出比较。

二者语义不同：

- `scenario_baseline` 回答“回放结果是否符合场景预期”。
- `reference_execution` 回答“回放结果是否复现原始执行表现”。

## 4. 目标链路

### 4.1 用户触发回放

```text
用户在执行列表的操作列点击“链路回放”
  ->
选择比对模型
  ->
选择比较基准：场景基线 / 原始执行
  ->
提交创建 Replay Task
```

### 4.2 后端创建回放任务

```text
校验 original_execution 存在
  ->
校验 original_execution 已完成且有 scenario / agent
  ->
校验 baseline_source 合法
  ->
构造 baseline_snapshot_json
  ->
创建 replay_tasks(status=queued)
```

### 4.3 后端创建新的执行

```text
基于 original_execution 创建新的 execution_jobs
  ->
agent_id = original_execution.agent_id
scenario_id = original_execution.scenario_id
llm_model_id = 本次选择的比对模型
parent_execution_id = original_execution.id
run_source = "replay"
user_session = exec_<new_execution_id.hex>
trace_id = 新 trace id
status = queued
original_request = original_execution.original_request
  ->
replay_tasks.replay_execution_id = new_execution.id
```

### 4.4 真实调用 Agent

```text
复用 ExecutionService.run_execution(auto_compare=False)
  ->
按 OpenClaw 请求格式调用 Agent
  ->
user 使用 replay execution 自己的 user_session
  ->
等待 Agent 返回
  ->
写入 original_request / original_response
  ->
通过 run_id / trace_id 拉取真实 trace
```

回放执行必须和原始执行会话隔离，避免带历史上下文。

回放执行必须使用原始执行的 `original_request` 作为 prompt。如果原始执行没有 `original_request`，拒绝创建回放。

`auto_compare=False` 时：

- 只执行 Agent 调用、trace 拉取、指标提取和 execution 状态更新。
- 不创建普通自动比对 comparison。
- 回放 comparison 只能由 ReplayService 根据 `baseline_source` 和 `baseline_snapshot_json` 创建。
- 用户显式触发链路回放时，不受 `scenario.compare_enabled` 影响，回放完成后必须执行 replay comparison。

### 4.5 回放比对

```text
拉取 replay execution trace
  ->
提取 provider=openai 的 LLM spans
  ->
判断最终 OpenAI LLM 文本输出是否出现
  ->
根据 baseline_source 提取基准
  ->
执行 LLM-only comparison
  ->
写入 comparison_results
  ->
更新 replay_tasks 状态
  ->
更新 replay execution.comparison_passed
```

## 5. 数据模型设计

### 5.1 `execution_jobs` 增强

必须新增字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_source` | string | `manual` / `replay` |
| `parent_execution_id` | uuid nullable | 如果是 replay execution，指向原始 execution |
| `request_snapshot_json` | text nullable | 执行时请求快照，方便追溯 |

说明：

- 普通执行：`run_source = manual`，`parent_execution_id = null`。
- 回放执行：`run_source = replay`，`parent_execution_id = original_execution_id`。

### 5.2 新表 `replay_tasks`

必须新增独立表：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | uuid | 回放任务 ID |
| `original_execution_id` | uuid | 原始执行 |
| `replay_execution_id` | uuid nullable | 回放生成的新执行 |
| `scenario_id` | uuid | 场景 |
| `agent_id` | uuid | Agent |
| `baseline_source` | string | `scenario_baseline` / `reference_execution` |
| `baseline_snapshot_json` | text | 创建回放时冻结的比对基准 |
| `idempotency_key` | string | 防重复提交键 |
| `llm_model_id` | uuid | 本次用于比对的模型 |
| `status` | string | queued / running / pulling_trace / comparing / completed / failed |
| `comparison_id` | uuid nullable | 本次回放生成的比对结果 |
| `overall_passed` | bool nullable | 回放比对是否通过 |
| `error_message` | text nullable | 错误信息 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |
| `started_at` | datetime nullable | 开始时间 |
| `completed_at` | datetime nullable | 完成时间 |

Replay Task 是产品上的“回放记录”，Execution 是技术上的“真实执行记录”。

约束：

- `idempotency_key` 必须唯一。
- `original_execution_id` 不唯一，同一原始执行允许创建多条 Replay Task。

### 5.3 `comparison_results` 复用策略

当前 comparison 已经能表达 LLM-only 比对结果，本期继续复用，并且必须补充来源字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `source_type` | string | `execution_auto` / `recompare` / `replay` |
| `replay_task_id` | uuid nullable | 如果来源是 replay，指向 replay task |
| `baseline_source` | string nullable | 本次比对使用的基准来源 |

Replay Task 必须通过 `comparison_id` 指向当前回放比对结果；Comparison 也必须通过 `replay_task_id` 反向标识来源。

## 6. API 设计

### 6.1 创建链路回放

```text
POST /api/v1/replay
```

请求：

```json
{
  "original_execution_id": "uuid",
  "baseline_source": "reference_execution",
  "llm_model_id": "uuid",
  "idempotency_key": "uuid"
}
```

响应：

```json
{
  "id": "replay_task_uuid",
  "original_execution_id": "uuid",
  "replay_execution_id": "uuid",
  "status": "queued"
}
```

幂等规则：

- 如果 `idempotency_key` 已存在，返回已有 Replay Task。
- 如果 `idempotency_key` 不存在，创建新的 Replay Task 和 replay execution。

### 6.2 获取回放详情

```text
GET /api/v1/replay/{replay_task_id}
```

返回：

- Replay Task 基本信息。
- 原始 execution 摘要。
- 回放 execution 摘要。
- 当前 comparison 结果。
- 回放 trace 摘要。
- `baseline_source = reference_execution` 时额外返回原始 trace 摘要。
- `baseline_source = scenario_baseline` 时返回基线快照摘要，不要求返回原始 trace 摘要。

### 6.3 获取某次执行的回放历史

```text
GET /api/v1/execution/{execution_id}/replays?page=1&page_size=20
```

分页返回该 execution 作为 `original_execution_id` 触发过的所有 replay tasks，按 `created_at DESC` 排序。

### 6.4 获取回放 Trace

复用现有接口：

```text
GET /api/v1/execution/{replay_execution_id}/trace
```

Replay Detail 页面按 `baseline_source` 决定需要拉取哪些 trace：

- `scenario_baseline`：只拉回放执行 trace；基线来自 `baseline_snapshot_json.baseline_output`，没有原始 trace 对照。
- `reference_execution`：同时拉原始执行 trace 和回放执行 trace，用于链路复现对照。

无论哪种模式，回放比对判定都只能读取 `baseline_snapshot_json`，Trace 拉取只服务于页面展示和用户排查。

### 6.5 重新比对回放结果

如果用户只想换比对模型，不重新执行 Agent：

```text
POST /api/v1/replay/{replay_task_id}/recompare?llm_model_id=...
```

语义：

- 不创建新的 replay execution。
- 不重新调用 Agent。
- 基于 replay execution 的 trace 和 Replay Task 的 `baseline_snapshot_json` 追加一条 comparison。
- 更新 replay task 当前 comparison 指针。

如果用户想重新跑 Agent，应再次创建新的 Replay Task。

## 7. 比对规则

### 7.1 LLM Span 范围

统一只统计：

```text
span_type == "llm" && provider == "openai"
```

原因：

- `litellm` span 是聚合层，容易和真实模型调用重复。
- 页面展示、LLM 次数检查、最终输出提取必须一致。

Tool span 只用于链路展示，不参与通过/未通过判定。

### 7.2 `reference_execution` 基准

当 `baseline_source = reference_execution`：

```text
baseline_trace = original_execution.trace
actual_trace = replay_execution.trace
```

比对内容：

- 原始执行 OpenAI LLM 次数 vs 回放执行 OpenAI LLM 次数。
- 原始执行最终 LLM 输出 vs 回放执行最终 LLM 输出。

这种模式下不使用场景配置的 `llm_count_min/max`，也不提供 LLM 次数容忍度配置。实际比对读取 `baseline_snapshot_json` 中冻结的 `expected_min` / `expected_max`。

本期固定规则：

```text
expected_min = original_openai_llm_count
expected_max = original_openai_llm_count
```

也就是说，回放执行的 OpenAI LLM 次数必须与原始执行完全一致，次数不一致则判定为未通过，并且不进入最终输出语义判断。

### 7.3 `scenario_baseline` 基准

当 `baseline_source = scenario_baseline`：

```text
baseline_output = scenario.baseline_result
expected_min = scenario.llm_count_min
expected_max = scenario.llm_count_max
actual_trace = replay_execution.trace
```

比对内容：

- 回放执行 OpenAI LLM 次数是否落在场景配置范围。
- 回放执行最终 LLM 输出是否和场景基线语义一致。

实际比对读取创建 Replay Task 时冻结的 `baseline_snapshot_json`。如果场景基线在回放运行过程中被修改，不影响已经创建的 Replay Task。

### 7.4 最终 LLM 输出识别

最终输出识别规则：

```text
OpenAI LLM span 的 output 可提取 assistant 文本
并且 output 不包含 tool_calls / function_call
```

如果一条 Assistant message 同时有 content 和 tool_calls：

- 页面 Messages 中要同时展示文本和工具调用。
- 该 span 不应被当成最终输出，因为它仍在请求工具调用。

如果一条 Assistant message 只有 content 且无 tool_calls：

- 作为最终输出候选。

### 7.5 判定流程

```text
提取 actual_openai_llm_spans
  ->
提取 final_actual_output
  ->
如果没有最终输出：失败
  ->
根据 baseline_source 确定 expected_min / expected_max / baseline_output
  ->
LLM 次数检查
  ->
如果次数不通过：失败，不进入语义判断
  ->
算法粗筛相似度
  ->
如果达到直通阈值：通过
  ->
调用比对模型做语义判断
  ->
写入最终结果
```

## 8. 页面设计

### 8.1 执行列表页

执行列表页是“链路回放”的唯一发起入口。

操作列新增：

- `详情`：进入执行详情。
- `删除`：删除执行。
- `链路回放`：重新触发一次 Agent 完整调用。

`链路回放` 点击后打开配置弹窗：

- 原始执行：当前行 execution。
- 比对模型：必选。
- 比较基准：必选。
  - 和场景基线比较。
  - 和当前执行比较。

提交后：

```text
POST /api/v1/replay
  ->
创建 Replay Task
  ->
创建 replay execution
  ->
后台重新调用 Agent
  ->
页面提示“已创建回放任务”
```

提交后的跳转策略：

- 创建 Replay Task 成功后立即跳转到 Replay Detail。

操作按钮可用性：

- 原 execution 必须已完成或已完成但比对未通过。
- 原 execution 必须有关联 Agent 和场景。
- 如果选择 `scenario_baseline`，场景必须已有基线输出。
- 运行中、排队中、失败且无有效请求信息的 execution 不允许触发回放。

### 8.2 执行详情页

执行详情页不负责发起链路回放，只负责查看该 execution 的详情和回放历史。

执行详情页保留：

- 查看当前 execution 的 trace。
- 查看当前 execution 的 comparison history。
- 设置为场景基线。
- 重新比对当前 execution。

执行详情页新增：

- “回放历史”模块。

回放历史模块调用：

```text
GET /api/v1/execution/{execution_id}/replays?page=1&page_size=20
```

分页展示当前 execution 作为 `original_execution_id` 触发过的所有 Replay Task。

每条回放记录展示：

- 回放时间。
- 回放状态。
- 比较基准。
- 比对模型。
- 是否通过。
- 回放 execution id。
- Replay Detail 入口。

这里展示的是“回放任务列表”，不是 comparison history。

### 8.3 回放详情页 Replay Detail

Replay Detail 是回放能力的主页面，但展示布局必须根据 `baseline_source` 区分。

通用布局：

1. 回放任务摘要。
2. 原始执行 vs 回放执行。
3. 当前回放比对结论。
4. LLM 调用次数对比。
5. 最终输出对比。
6. 错误与日志区域。

当 `baseline_source = scenario_baseline`：

- 页面展示“场景基线快照 vs 回放执行结果”。
- 左侧或上方展示 `baseline_snapshot_json` 中冻结的基线输出和期望 LLM 次数范围。
- 右侧或下方展示回放执行 Trace。
- 不展示原始 Trace 双栏，因为判定基准不是原始执行链路。

当 `baseline_source = reference_execution`：

- 页面展示“原始执行 vs 回放执行”。
- 展示原始 Trace 与回放 Trace 双栏。
- LLM 次数对比使用 `baseline_snapshot_json.expected_min = baseline_snapshot_json.expected_max = original_openai_llm_count`。

Replay Detail 轮询规则：

- `queued`、`running`、`pulling_trace`、`comparing` 状态下每 2 秒刷新一次。
- `completed` 或 `failed` 后停止轮询。
- 前端轮询最长 5 分钟，超时后提示“回放仍在后台执行，可稍后刷新查看”。

### 8.4 Trace 展示

Replay Detail 的 Trace 区域有两种形态：

- `scenario_baseline`：单 Trace 布局，只展示回放执行 Trace，旁边展示基线快照卡片。
- `reference_execution`：双 Trace 布局，左侧原始执行 Trace，右侧回放执行 Trace。

每个 Trace 内部：

- 默认展示 tool spans + `provider=openai` LLM spans。
- LLM / Tool 用不同颜色区分。
- LLM 显示 token：`total(input+output)`。
- LLM 展开后分为 `Messages` 和 `Details`。
- Tool 展开后展示工具输入输出。

## 9. 状态机

### 9.1 Replay Task 状态

```text
queued
  ->
running
  ->
pulling_trace
  ->
comparing
  ->
completed
```

失败时：

```text
queued/running/pulling_trace/comparing
  ->
failed
```

### 9.2 Replay Execution 状态

继续复用现有 execution 状态：

- queued
- running
- pulling_trace
- comparing
- completed
- completed_with_mismatch
- failed

Replay Task 状态和 Replay Execution 状态不完全等价：

- Replay Task 描述回放任务整体。
- Replay Execution 描述那次真实 Agent 调用。

### 9.3 并发状态保护

同一个 Replay Task 可能因为重复投递、服务重启恢复或人工触发被多个 worker 同时执行。

保护规则：

- `run_replay` 开始时必须通过数据库行锁或条件更新抢占任务。
- 只有 `status = queued` 的 Replay Task 可以切换为 `running`。
- 抢占失败的 worker 必须直接退出。
- 状态切换必须在事务内完成。

服务启动恢复规则：

- 扫描 `queued` 状态 Replay Task 并重新投递。
- 扫描 `running`、`pulling_trace`、`comparing` 且 `updated_at` 超过 30 分钟未更新的 Replay Task。
- 超时任务标记为 `failed`，错误信息为“回放任务超时，请重新发起链路回放”。
- 不自动重跑已经进入 `running` 后超时的任务，避免重复调用 Agent。

## 10. 异常处理

### 10.1 Agent 调用失败

- Replay Execution 标记为 failed。
- Replay Task 标记为 failed。
- 记录错误信息。

### 10.2 Trace 拉取不到

- Replay Execution 保留 Agent 原始响应。
- Replay Task 标记为 failed。
- 页面展示“回放执行完成，但未拉取到 Trace”。

### 10.3 LLM 次数不符合

- Replay Task completed。
- Comparison completed。
- overall_passed = false。
- 页面说明“LLM 调用次数检查未通过，未进入最终输出语义判断。”

### 10.4 比对模型超时

- Replay Execution 不受影响。
- Comparison failed。
- Replay Task 标记为 failed。
- 用户可对 replay execution 重新比对。

### 10.5 删除约束

本期采用保护性删除：

- 如果 execution 被 Replay Task 作为 `original_execution_id` 引用，禁止删除该 execution。
- 如果 execution 被 Replay Task 作为 `replay_execution_id` 引用，禁止删除该 execution。
- 如果 comparison 被 Replay Task 的 `comparison_id` 引用，禁止单独删除该 comparison。
- 如果 Agent 被 Replay Task 引用，禁止删除该 Agent。
- 如果 Scenario 被 Replay Task 引用，禁止删除该 Scenario。
- 如果 LLM Model 被 Replay Task 引用，禁止删除该 LLM Model。
- 本期不实现 Replay Task 删除能力。

## 11. 和当前重新比对的关系

必须保持语义清晰：

| 功能 | 是否重新调用 Agent | 是否生成新 execution | 是否生成新 trace | 使用场景 |
|------|-------------------|---------------------|-----------------|----------|
| 重新比对 | 否 | 否 | 否 | 换模型重新判断同一结果 |
| 链路回放 | 是 | 是 | 是 | 验证 Agent 重新执行后的链路是否一致 |

用户如果说“重新比对”，系统只换比对模型。

用户如果说“链路回放”，系统必须重新触发 Agent 完整调用。

## 12. 落地顺序

### Phase 1：数据模型

- `execution_jobs` 增加 `run_source`、`parent_execution_id`、`request_snapshot_json`。
- 新增 `replay_tasks`。
- Repository / Entity / Pydantic 模型补齐。

### Phase 2：后端主链路

- 新增 `ReplayService`。
- 新增 `POST /api/v1/replay`。
- 创建 replay task 时同步创建 replay execution。
- 后台复用 `ExecutionService.run_execution`。
- 回放完成后写入 comparison。

### Phase 3：前端入口

- 执行列表操作列增加“链路回放”按钮。
- 增加回放配置弹窗。
- 增加回放历史列表。
- 增加 Replay Detail 页面。

### Phase 4：Trace 对照体验

- Replay Detail 支持按基准模式切换 Trace 展示。
- `scenario_baseline` 使用基线快照 + 回放 Trace。
- `reference_execution` 使用原始 Trace / 回放 Trace 双栏。
- LLM span 标记最终输出。
- 展示 LLM 次数对比和 token 聚合。

### Phase 5：增强与清理

- 支持对 replay execution 重新比对。
- comparison 记录 `source_type` / `replay_task_id`。
- 清理旧文档里已经不适用的 tool comparison 设计。

## 13. 当前决策

1. 链路回放就是端到端重新执行 Agent。
2. 每次链路回放都必须生成新的 execution、独立 session 和新的 trace。
3. 回放任务需要独立 `replay_tasks` 承载，不能只靠 comparison history 表达。
4. 重新比对和链路回放是两个不同功能，不能混用。
5. 回放比对继续使用 LLM-only 规则。
6. LLM 次数统计继续只看 `provider=openai`。
7. Tool spans 只展示，不参与最终判定。
8. 回放详情页需要按 `baseline_source` 展示链路：场景基线模式只展示回放链路，参考执行模式展示原始链路和回放链路。
9. 同一次提交通过 `idempotency_key` 保证幂等，不同提交允许并发创建多条回放。
10. 回放比对使用创建任务时冻结的 `baseline_snapshot_json`。
