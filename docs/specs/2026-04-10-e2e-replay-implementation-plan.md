# 端到端链路回放实施计划

**日期**：2026-04-10  
**状态**：Draft  
**对应设计**：`docs/specs/2026-04-10-trace-replay-design-after-comparison-refactor.md`

## 1. 实施目标

本次实现的目标是新增“端到端链路回放”能力：

> 用户在执行列表操作列点击“链路回放”，系统基于该条历史执行重新触发一次 Agent 完整调用，生成新的 replay execution、新 trace 和 replay comparison。执行详情页只展示该执行触发过的多次回放记录，点击单条回放记录进入 Replay Detail 页面查看完整对照。

必须保持三个功能语义独立：

- `查看 Trace`：只查看已有 execution trace。
- `重新比对`：不重新执行 Agent，只基于已有 trace 换比对模型重新判定。
- `链路回放`：重新执行 Agent，生成新的 execution、session、trace 和比对结果。

## 2. 已确定规则

本实施计划不保留待决策项，以下规则按确定结论实现：

- `reference_execution` 模式下，回放执行的 OpenAI LLM 次数必须与原始执行完全一致，不提供容忍度配置。
- `scenario_baseline` 模式下，回放执行的 OpenAI LLM 次数使用场景配置的 `llm_count_min` / `llm_count_max` 判断。
- 创建回放成功后，前端立即跳转到 Replay Detail 页面。
- 执行列表是发起链路回放的唯一入口，执行详情页只展示回放历史。
- 回放执行必须创建新的 execution、使用新的 `user_session`、生成新的 trace。
- 回放执行不能走普通执行的自动比对逻辑，ReplayService 必须接管回放比对。
- Replay Task 的失败状态统一使用 `failed`，错误原因写入 `error_message`。
- 本期必须新增 `replay_tasks`，不能只依赖 `comparison_results` 表达回放关系。
- 同一次弹窗提交必须使用 `idempotency_key` 去重，防止重复点击创建重复回放。
- 多次有意发起的回放允许并发执行，每次回放使用不同 `idempotency_key`、不同 execution、不同 session。
- 回放比对使用创建 Replay Task 时冻结的基准快照，不读取运行过程中可能变化的场景基线。
- 回放执行使用原始执行的 `original_request` 作为 prompt；如果原始执行没有 `original_request`，拒绝创建回放。

## 3. 并发与一致性规则

### 3.1 重复点击与幂等

前端每次打开回放配置弹窗时生成一个新的 `idempotency_key`，同一次提交重试必须复用该 key。

后端规则：

- `POST /api/v1/replay` 请求体必须包含 `idempotency_key`。
- `replay_tasks.idempotency_key` 必须建立唯一索引。
- 如果同一个 `idempotency_key` 已存在，直接返回已有 Replay Task，不再创建新的 replay execution。
- 用户关闭弹窗后重新打开并再次提交，生成新的 `idempotency_key`，视为一次新的有意回放。

### 3.2 多用户并发创建

同一个 original execution 允许被多个用户同时发起多次回放。

规则：

- 不对 `original_execution_id` 做唯一约束。
- 每个 Replay Task 都生成独立 replay execution。
- 每个 replay execution 都生成独立 `user_session` 和 `trace_id`。
- 回放历史按 `created_at DESC` 展示。

### 3.3 后台任务并发执行

后台任务可能因为重复投递、服务重启或手工恢复被执行多次。

后端必须保证同一个 Replay Task 只会有一个 worker 真正进入执行：

- `run_replay` 开始时必须使用数据库行锁或条件更新抢占任务。
- 只有 `status = queued` 的 Replay Task 可以切换到 `running`。
- 如果任务已经是 `running`、`pulling_trace`、`comparing`、`completed` 或 `failed`，新的 worker 直接退出。
- 状态切换必须在事务中完成。

### 3.4 事务边界

创建回放必须分成两个明确阶段：

1. 同一个数据库事务内创建 Replay Task、replay execution、baseline snapshot，并绑定关系。
2. 事务提交成功后再投递后台任务。

如果事务失败：

- 不创建 Replay Task。
- 不创建 replay execution。
- API 返回失败。

如果事务成功但后台任务投递失败：

- Replay Task 保持 `queued`。
- 前端仍跳转 Replay Detail。
- 后续由恢复任务扫描 `queued` 状态并重新投递。

### 3.5 卡住任务恢复

本期必须实现一个轻量恢复机制。

恢复规则：

- 服务启动时扫描 `queued` 状态 Replay Task 并重新投递。
- 服务启动时扫描 `running`、`pulling_trace`、`comparing` 且 `updated_at` 超过 30 分钟未更新的 Replay Task。
- 对超时任务，将 Replay Task 标记为 `failed`，`error_message = "回放任务超时，请重新发起链路回放"`。
- 不自动重跑已经进入 `running` 后超时的任务，避免重复调用 Agent。

### 3.6 基准快照

创建 Replay Task 时必须冻结本次比对基准，写入 `baseline_snapshot_json`。

`scenario_baseline` 模式快照内容：

```json
{
  "source": "scenario_baseline",
  "baseline_output": "...",
  "expected_min": 3,
  "expected_max": 4,
  "scenario_id": "uuid"
}
```

`reference_execution` 模式快照内容：

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

创建快照失败时拒绝创建 Replay Task：

- 场景基线为空。
- 原始执行 trace 拉取失败。
- 原始执行没有可提取的最终 OpenAI LLM 输出。

回放完成后，比对只读取 `baseline_snapshot_json`，不再读取可能已经变化的场景基线或原始 trace 作为判定基准。

### 3.7 删除与关联约束

本期采用保护性删除策略：

- 如果 execution 被任何 Replay Task 作为 `original_execution_id` 引用，禁止删除该 execution。
- 如果 execution 被任何 Replay Task 作为 `replay_execution_id` 引用，禁止删除该 execution。
- 如果 comparison 被 Replay Task 的 `comparison_id` 引用，禁止单独删除该 comparison。
- 如果 Agent 被任何 Replay Task 引用，禁止删除该 Agent。
- 如果 Scenario 被任何 Replay Task 引用，禁止删除该 Scenario。
- 如果 LLM Model 被任何 Replay Task 引用，禁止删除该 LLM Model。
- 后续需要删除回放历史时，必须先提供独立的 Replay Task 删除能力，本期不实现。

### 3.8 回放与重新比对并发

Replay Task 未完成时：

- 禁止对该 Replay Task 发起 `POST /api/v1/replay/{id}/recompare`。
- Replay Detail 页面隐藏或禁用“重新比对回放结果”按钮。

Replay Task 完成后：

- 允许多次重新比对。
- 每次重新比对创建一条新的 comparison。
- Replay Task 的 `comparison_id` 指向最新完成的 comparison。
- 如果多个重新比对请求并发完成，`comparison_id` 指向 `completed_at` 最新的一条。

## 4. 最终用户流程

### 4.1 发起回放

```text
测试执行列表
  ->
操作列点击“链路回放”
  ->
打开回放配置弹窗
  ->
选择比对模型
  ->
选择比较基准：和场景基线比较 / 和当前执行比较
  ->
提交
  ->
创建 Replay Task + Replay Execution
  ->
后台重新调用 Agent
  ->
跳转 Replay Detail
```

### 4.2 查看回放历史

```text
执行详情页
  ->
回放历史卡片 / Tab
  ->
展示该 execution 作为 original_execution 触发过的 Replay Tasks
  ->
点击某条“查看详情”
  ->
进入 Replay Detail
```

### 4.3 查看单次回放详情

```text
Replay Detail
  ->
展示 Replay Task 摘要
  ->
展示原始执行和回放执行
  ->
展示回放比对结果
  ->
根据 baseline_source 展示 Trace 区域
  ->
展示 LLM 次数对比和最终输出对比
```

Trace 区域规则：

- `scenario_baseline`：展示“基线快照 + 回放 Trace”，不拉取、不展示原始 Trace。
- `reference_execution`：展示“原始 Trace + 回放 Trace”双栏对照。

## 5. 后端实施

### 5.1 数据库 Migration

#### 5.1.1 增强 `execution_jobs`

新增字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `run_source` | string | `manual` | `manual` / `replay` |
| `parent_execution_id` | uuid nullable | null | 回放执行指向原始执行 |
| `request_snapshot_json` | text nullable | null | 执行时请求快照 |

必须创建索引：

- `idx_execution_jobs_parent_execution_id`
- `idx_execution_jobs_run_source`

#### 5.1.2 新增 `replay_tasks`

字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | uuid | 主键 |
| `original_execution_id` | uuid | 原始执行 |
| `replay_execution_id` | uuid nullable | 回放生成的新执行 |
| `scenario_id` | uuid | 场景 |
| `agent_id` | uuid | Agent |
| `baseline_source` | string | `scenario_baseline` / `reference_execution` |
| `baseline_snapshot_json` | text | 创建回放时冻结的比对基准 |
| `idempotency_key` | string | 防重复提交键 |
| `llm_model_id` | uuid | 比对模型 |
| `status` | string | queued / running / pulling_trace / comparing / completed / failed |
| `comparison_id` | uuid nullable | 当前回放比对结果 |
| `overall_passed` | bool nullable | 是否通过 |
| `error_message` | text nullable | 错误信息 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |
| `started_at` | datetime nullable | 开始时间 |
| `completed_at` | datetime nullable | 完成时间 |

必须创建索引：

- `idx_replay_tasks_original_execution_id`
- `idx_replay_tasks_replay_execution_id`
- `idx_replay_tasks_status`
- `idx_replay_tasks_created_at`
- `uq_replay_tasks_idempotency_key`

#### 5.1.3 增强 `comparison_results`

新增字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `source_type` | string | `execution_auto` | `execution_auto` / `recompare` / `replay` |
| `replay_task_id` | uuid nullable | null | 来源为 replay 时指向 Replay Task |
| `baseline_source` | string nullable | null | replay 比对使用的基准来源 |

必须创建索引：

- `idx_comparison_results_replay_task_id`
- `idx_comparison_results_source_type`

### 5.2 领域实体与模型

新增或更新：

- `app/domain/entities/replay.py`
- `app/models/replay.py`
- `app/models/execution.py`
- `app/models/comparison.py`

必须新增枚举：

```python
class ReplayBaselineSource(str, Enum):
    SCENARIO_BASELINE = "scenario_baseline"
    REFERENCE_EXECUTION = "reference_execution"

class ReplayTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PULLING_TRACE = "pulling_trace"
    COMPARING = "comparing"
    COMPLETED = "completed"
    FAILED = "failed"
```

### 5.3 Repository

新增：

- `app/domain/repositories/replay_repo.py`

能力：

- `create`
- `get_by_id`
- `list_by_original_execution_id`
- `update`
- `set_replay_execution`
- `set_comparison`
- `mark_failed`
- `get_by_idempotency_key`
- `try_mark_running`
- `list_recoverable_queued`
- `mark_stale_tasks_failed`

### 5.4 ReplayService

新增：

- `app/services/replay_service.py`

核心方法：

```python
async def create_replay(request: CreateReplayRequest) -> ReplayTask
async def run_replay(replay_task_id: UUID) -> None
async def recompare_replay(replay_task_id: UUID, llm_model_id: UUID) -> ComparisonResult
async def recover_replay_tasks() -> None
```

`create_replay` 职责：

- 校验原始执行存在。
- 校验原始执行状态允许回放。
- 校验 Agent / Scenario / LLMModel 存在。
- 校验 `baseline_source`。
- 校验 `idempotency_key`。
- 如果 `idempotency_key` 已存在，直接返回已有 Replay Task。
- 构造并冻结 `baseline_snapshot_json`。
- 创建 Replay Task。
- 创建 Replay Execution。
- 绑定 `replay_task.replay_execution_id`。
- 投递后台任务。

`run_replay` 职责：

- 标记 Replay Task 为 running。
- 抢占任务失败时直接退出。
- 复用现有 ExecutionService 执行 replay execution。
- 等待 replay execution 完成。
- 标记 pulling_trace / comparing。
- 根据 `baseline_source` 选择比对基准。
- 写入 comparison。
- 标记 completed / failed。

### 5.5 ExecutionService 改造

需要支持“基于原始执行创建 replay execution”。

必须新增方法：

```python
async def create_replay_execution(
    original_execution: ExecutionJob,
    llm_model_id: UUID,
) -> ExecutionJob
```

字段规则：

- `agent_id = original_execution.agent_id`
- `scenario_id = original_execution.scenario_id`
- `llm_model_id = request.llm_model_id`
- `run_source = "replay"`
- `parent_execution_id = original_execution.id`
- `user_session = f"exec_{new_execution_id.hex}"`
- `trace_id = uuid4()`
- `status = queued`
- `original_request = original_execution.original_request`
- `request_snapshot_json` 记录本次实际请求体和 baseline snapshot 摘要

注意：

- 回放执行必须重新生成 session，不能复用原始执行 session。
- 回放执行必须重新调用 Agent，不能复用原始响应。
- 回放 prompt 必须使用 `original_execution.original_request`。
- 如果 `original_execution.original_request` 为空，拒绝创建回放。

必须拆分执行和比对：

```python
async def run_execution(
    execution_id: UUID,
    *,
    auto_compare: bool = True,
) -> None
```

回放调用规则：

- ReplayService 调用 `run_execution(replay_execution.id, auto_compare=False)`。
- `auto_compare=False` 时只执行 Agent 调用、trace 拉取、指标提取和 execution 状态更新。
- `auto_compare=False` 时不得创建普通 `comparison_results`。
- replay comparison 只能由 ReplayService 根据 `baseline_source` 和 `baseline_snapshot_json` 创建。
- 用户显式发起链路回放时，不受 `scenario.compare_enabled` 影响，回放完成后必须执行 replay comparison。

### 5.6 ComparisonService 改造

当前 comparison 是和场景基线比较。回放需要支持两种基准：

#### `scenario_baseline`

使用 `baseline_snapshot_json`：

- `baseline_output = baseline_snapshot.baseline_output`
- `expected_min = baseline_snapshot.expected_min`
- `expected_max = baseline_snapshot.expected_max`

#### `reference_execution`

固定逻辑：

- 从 `baseline_snapshot_json` 读取原始执行 OpenAI LLM 次数。
- 从 `baseline_snapshot_json` 读取原始执行最终 LLM 输出。
- replay execution trace 作为 actual。
- replay execution 的 OpenAI LLM 次数必须与 original execution 完全一致。
- 本期不读取场景的 `llm_count_min/max`，也不提供容忍度配置。

必须新增方法：

```python
async def compare_replay(
    replay_task: ReplayTask,
    original_execution: ExecutionJob,
    replay_execution: ExecutionJob,
    scenario: Scenario,
    trace_spans: list[Span],
    llm_model: LLMModel,
) -> ComparisonResult
```

必须抽象基准构造器：

```python
class ComparisonBaseline:
    expected_min: int
    expected_max: int
    baseline_output: str
    source: str
```

基准构造规则：

- `scenario_baseline`：`expected_min = scenario.llm_count_min`，`expected_max = scenario.llm_count_max`。
- `reference_execution`：`expected_min = expected_max = original_openai_llm_count`。

### 5.7 API

新增文件：

- `app/api/replay.py`

接口：

```text
POST /api/v1/replay
GET /api/v1/replay/{replay_task_id}
GET /api/v1/execution/{execution_id}/replays?page=1&page_size=20
POST /api/v1/replay/{replay_task_id}/recompare?llm_model_id=...
```

保留现有：

```text
GET /api/v1/execution/{execution_id}/trace
GET /api/v1/execution/{execution_id}/comparisons
POST /api/v1/execution/{execution_id}/recompare
```

### 5.8 API 请求响应细节

`POST /api/v1/replay` 请求体：

```json
{
  "original_execution_id": "uuid",
  "baseline_source": "reference_execution",
  "llm_model_id": "uuid",
  "idempotency_key": "uuid"
}
```

`POST /api/v1/replay` 返回后，`replay_execution_id` 必须已经存在。

`GET /api/v1/execution/{execution_id}/replays` 必须分页返回：

```json
{
  "total": 12,
  "items": []
}
```

排序规则：

- `created_at DESC`

### 5.9 Trace API 增强

本期必须补充：

- `start_time_ms`
- `end_time_ms`
- `token_total`
- `has_tool_calls`
- `is_final_output_span`
- `llm_index`

本期不实现：

- `display_messages`

说明：

- `display_messages` 仍由前端沿用现有解析逻辑。
- `is_final_output_span` 由后端使用最终输出识别规则计算。
- `llm_index` 只对 `provider=openai` 的 LLM spans 编号。

## 6. 前端实施

### 6.1 API Client 与类型

新增类型：

- `ReplayTask`
- `ReplayDetail`
- `CreateReplayRequest`
- `ReplayBaselineSource`
- `ReplayTaskStatus`

新增 API：

```ts
replayApi.create(payload)
replayApi.get(id)
replayApi.listByExecution(executionId)
replayApi.recompare(id, llmModelId)
```

### 6.2 执行列表页

文件：

- `frontend/src/pages/ExecutionList.tsx`

改造：

- 操作列新增 `链路回放`。
- 点击后打开回放配置弹窗。
- 弹窗选择比对模型。
- 弹窗选择比较基准。
- 弹窗打开时生成新的 `idempotency_key`。
- 提交调用 `POST /api/v1/replay`。
- 成功后立即跳转 Replay Detail。
- 提交中禁用确认按钮，防止重复点击。

按钮禁用规则：

- 只有 `completed` 和 `completed_with_mismatch` 状态允许点击。
- 执行缺少 Agent / Scenario 时禁用。
- Agent、Scenario 或比对模型列表加载失败时禁用。
- 如果选择场景基线但场景无基线，提交前拦截并提示“请先设置场景基线”。
- 如果选择当前执行比较，但原执行 trace 无法提取最终 OpenAI LLM 输出，后端拒绝创建并返回明确错误。

### 6.3 执行详情页

文件：

- `frontend/src/pages/ExecutionDetail.tsx`

改造：

- 不新增“发起回放”按钮。
- 新增“回放历史”卡片或 tab。
- 调用 `GET /api/v1/execution/{execution_id}/replays?page=1&page_size=20`。
- 展示多次 Replay Task。
- 回放历史超过 20 条时分页展示。
- 单条记录提供 `查看详情`，跳转 Replay Detail。

展示字段：

- 回放状态。
- 比较基准。
- 比对模型。
- 是否通过。
- 创建时间。
- 完成时间。
- 回放 execution id。

### 6.4 Replay Detail 页面

新增文件：

- `frontend/src/pages/ReplayDetail.tsx`

新增路由：

```text
/replays/:replayTaskId
```

页面结构：

1. Replay Task 摘要。
2. 原始执行 / 回放执行对照。
3. 比对结果摘要。
4. LLM 调用次数对比。
5. 最终输出对比。
6. Trace 区域。

Trace 区域必须按 `baseline_source` 切换：

- `scenario_baseline`：展示基线快照卡片和回放执行 Trace。基线快照卡片显示冻结的基线输出、期望 LLM 次数范围、算法粗筛阈值等信息。
- `reference_execution`：展示原始执行 Trace 和回放执行 Trace 双栏。该模式用于排查链路复现差异。

`scenario_baseline` 模式不应该为了页面展示额外拉取原始 Trace；原始执行只作为“本次回放由哪条执行触发”的来源展示。

轮询规则：

- 当 Replay Task 状态为 `queued`、`running`、`pulling_trace`、`comparing` 时，每 2 秒刷新一次 Replay Detail。
- 状态进入 `completed` 或 `failed` 后停止轮询。
- 轮询最长 5 分钟；超过 5 分钟仍未结束时停止前端轮询，并提示“回放仍在后台执行，可稍后刷新查看”。

本期必须抽取 Trace 展示共享组件：

- `TraceReplayPanel`
- `TraceSpanCard`
- `LLMMessageViewer`

执行详情页和 Replay Detail 必须复用同一套 Trace 展示组件，避免两套解析逻辑分叉。

## 7. 测试计划

### 7.1 后端单元测试

新增：

- 创建 replay task 成功。
- 原执行不存在时失败。
- 原执行未完成时失败。
- 选择场景基线但基线为空时失败。
- replay execution 使用新的 user_session。
- replay execution 的 `parent_execution_id` 指向原执行。
- `reference_execution` 模式要求 replay OpenAI LLM 次数与原执行 OpenAI LLM 次数完全一致。
- `reference_execution` 模式不读取场景 `llm_count_min/max`。
- `scenario_baseline` 模式使用场景配置作为基准。
- 相同 `idempotency_key` 重复提交只创建一个 Replay Task。
- 同一个 original execution 不同 `idempotency_key` 可创建多个 Replay Task。
- 重复执行同一个 `run_replay` 时只有一个 worker 能抢占成功。
- `baseline_snapshot_json` 创建后，场景基线变化不影响本次回放比对。
- 删除被 Replay Task 引用的 execution 时失败。
- 删除被 Replay Task 引用的 Agent / Scenario / LLM Model 时失败。
- replay execution 调用 `run_execution(auto_compare=False)` 时不会创建普通自动比对结果。
- 即使 `scenario.compare_enabled = false`，链路回放仍会执行 replay comparison。

### 7.2 后端集成测试

新增：

- `POST /api/v1/replay` 返回 replay task。
- `GET /api/v1/execution/{id}/replays` 返回多条回放记录。
- `GET /api/v1/execution/{id}/replays` 支持分页和总数。
- `GET /api/v1/replay/{id}` 返回原执行、回放执行、比对结果。
- replay 后台任务失败时记录 error_message。
- 服务启动恢复 queued Replay Task。
- 超过 30 分钟未更新的运行中 Replay Task 被标记为 failed。

### 7.3 前端类型检查

运行：

```text
npx tsc --noEmit
```

### 7.4 手工验收

验收场景：

- 在执行列表点击“链路回放”，能创建新回放任务。
- 新回放任务会产生新的 execution。
- 新 execution 的 `user_session` 与原 execution 不同。
- 回放完成后，详情页回放历史能看到记录。
- 点击回放历史记录能进入 Replay Detail。
- Replay Detail 能按 `baseline_source` 展示 Trace 区域。
- `scenario_baseline` 模式只展示基线快照和回放 trace。
- `reference_execution` 模式展示原始 trace 和回放 trace 双栏。
- LLM 次数按 `provider=openai` 统计。
- `reference_execution` 模式下，原始执行 3 次 OpenAI LLM，则回放执行也必须是 3 次才通过次数检查。
- 重新比对 replay 不会重新执行 Agent。
- 快速双击“确认回放”不会创建两条回放任务。
- 两个用户同时对同一执行发起回放，会产生两条彼此独立的回放任务。

## 8. 实施顺序

### Phase 1：Replay 数据模型

- Migration：`execution_jobs` 增强。
- Migration：新增 `replay_tasks`。
- Entity / Model / Repository。
- 基础 API 返回真实 Replay Task 结构。

### Phase 2：Replay 后端主链

- `ReplayService.create_replay`。
- 创建 replay execution。
- 后台执行 replay execution。
- Replay Task 状态流转。
- 失败处理。

### Phase 3：Replay 比对

- `scenario_baseline` 模式。
- `reference_execution` 模式。
- comparison 与 replay task 关联。
- replay recompare。

### Phase 4：执行列表入口

- 操作列新增“链路回放”。
- 回放配置弹窗。
- 提交创建 replay。
- 跳转 Replay Detail。

### Phase 5：详情页回放历史

- 执行详情页新增回放历史模块。
- 展示多次回放。
- 跳转 Replay Detail。
- `scenario_baseline` 回放详情只展示基线快照和回放 Trace。
- `reference_execution` 回放详情展示原始 Trace 和回放 Trace 双栏。

### Phase 6：Replay Detail

- 页面骨架。
- 任务摘要。
- 原始执行 / 回放执行对照。
- 比对结果。
- `scenario_baseline` 的基线快照 + 回放 Trace 展示。
- `reference_execution` 的双 Trace 展示。

### Phase 7：收尾

- 抽取 Trace 展示组件。
- 补齐测试。
- 更新 CHANGELOG。
- 更新旧文档状态说明。

## 9. 验收标准

本功能完成时必须满足：

- 执行列表操作列可以触发端到端链路回放。
- 每次链路回放都会重新调用 Agent。
- 每次链路回放都会生成新的 execution。
- 新 execution 使用新的独立 `user_session`。
- 执行详情页能查看该 execution 触发过的多次回放记录。
- 单次回放详情页能按 `baseline_source` 正确展示 Trace 区域。
- `scenario_baseline` 模式不展示原始 Trace，只展示基线快照和回放 Trace。
- `reference_execution` 模式展示原始 Trace 和回放 Trace 双栏。
- 回放比对仍遵守 LLM-only 规则。
- `reference_execution` 模式 LLM 次数必须完全一致，不存在容忍度配置。
- 快速重复提交同一个 `idempotency_key` 不会创建重复回放。
- 同一个 original execution 支持多个不同 Replay Task 并发执行。
- 创建 Replay Task 后修改场景基线，不影响该回放任务的比对基准。
- `重新比对` 与 `链路回放` 在 UI、API、数据模型上语义清晰，不混用。
