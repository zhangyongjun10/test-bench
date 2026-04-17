# 多场景执行设计方案

**日期**：2026-04-16  
**状态**：Draft  
**范围**：测试执行页的单次执行与并发执行支持多选场景

## 1. 背景

当前测试执行入口只支持一次选择一个场景：

- 单次执行：`POST /api/v1/execution`，请求体包含 `agent_id`、`scenario_id`、`llm_model_id`。
- 并发执行：`POST /api/v1/execution/concurrent`，请求体包含 `input`、`concurrency`、`scenario_id`、`llm_model_id`、`agent_id`。
- 前端新建执行弹窗中，先选择 Agent，再从该 Agent 下的场景中单选一个场景。
- 并发执行当前以一个 `batch_id` 聚合同一场景下的多条 execution。
- `execution_jobs.batch_id` 已存在，可以作为批量提交的聚合标识复用。

新需求是：

> 单次执行和并发执行都可以多选场景执行。

这不是简单把 `scenario_id` 改成数组。多场景会影响执行记录数量、并发语义、批次状态、会话隔离、Trace 归属、列表展示和失败处理，因此需要按“批量执行编排”来设计。

## 2. 目标

本期目标：

- 单次执行模式下，用户可以选择多个场景，一次提交后每个场景各执行一次。
- 并发执行模式下，用户可以选择多个场景，一次提交后每个场景按用户填写的并发数执行。
- 每一条实际调用仍然落成一条独立 `execution_jobs` 记录。
- 每一条 execution 都使用独立 `user_session = exec_<execution_id.hex>`，保证会话隔离。
- 每一条 execution 都有独立 `trace_id`，避免 Trace 串扰。
- 同一次提交下创建的 execution 使用同一个 `batch_id` 聚合。
- 前端能够明确提示预计创建多少条 execution，避免用户误触发大量任务。
- 保留现有单场景 API 的兼容性，避免影响已有功能和回放链路。

本期不做：

- 不支持一次选择多个 Agent。
- 不支持跨 Agent 混选场景。
- 不改变 LLM-only 比对规则。
- 不改变链路回放语义。
- 不新增批次管理页面。
- 不新增独立的批量执行任务表。
- 不设计独立的批量执行任务状态机。
- 不把多场景执行结果合并成一条 execution。

## 3. 术语

### 3.1 执行批次

执行批次表示用户在新建执行弹窗中点击一次“确定”后产生的一组 execution。

批次通过 `batch_id` 关联，不要求本期新增独立批次表。

### 3.2 子执行

子执行是批次中的单条 `execution_jobs` 记录。每个子执行对应一次真实 Agent HTTP 调用。

### 3.3 单次多场景

如果用户选择 `N` 个场景，单次执行会创建 `N` 条 execution。

```text
总执行数 = 场景数量
```

### 3.4 并发多场景

如果用户选择 `N` 个场景，并发数为 `C`，并发执行会为每个场景创建 `C` 条 execution。

```text
总执行数 = 场景数量 × 每个场景并发数
```

这里的并发数保持当前产品语义：它表示“每个场景重复并发调用的次数”，不是整个批次的全局最大并行 worker 数。

## 4. 核心设计结论

### 4.1 新增统一批量创建入口

本期只新增：

```text
POST /api/v1/execution/batch
```

保留现有入口：

```text
POST /api/v1/execution
POST /api/v1/execution/concurrent
GET /api/v1/execution/concurrent/{batch_id}
```

兼容策略：

- 旧的单次执行接口继续只创建一个场景的一条 execution。
- 旧的并发执行接口继续支持一个场景的并发执行。
- 新前端弹窗可以统一调用 `/execution/batch`，即使只选择一个场景也可以走新入口。
- 旧接口后续可以内部复用批量执行服务，但不要求第一阶段立即替换。
- 本期不新增批次查询 API。
- 本期不实现批次状态查询或批次进度查询。

### 4.2 后端负责读取场景 prompt

多场景执行时，前端不再传 `input` 作为执行 prompt。

后端必须根据 `scenario_ids` 查询场景，并把每个场景当前 prompt 写入对应 execution 的 `original_request`。

原因：

- 防止前端传入的 prompt 与场景不一致。
- 防止多场景时 `input` 字段无法表达多个 prompt。
- 方便后续追溯每条 execution 实际执行的请求快照。

### 4.3 创建 execution 后再执行

批量接口需要先同步创建所有子 execution，再投递后台任务。

好处：

- API 返回后，列表立刻能看到所有 `queued` 记录。
- `batch_id` 状态查询能立刻知道总数。
- 每条 execution 的 `id` 可以提前生成，从而稳定生成 `user_session = exec_<execution_id.hex>`。
- 即使后台任务尚未开始，也不会出现批次状态 total 为 0 的短暂错觉。

### 4.4 每条子执行独立会话

无论单次多场景还是并发多场景，每条 execution 都必须独立生成：

- `id`
- `user_session`
- `trace_id`

规则：

```text
user_session = exec_<execution_id.hex>
```

不能用 `batch_id` 作为 session，因为同一批次中可能包含多个场景、多次并发调用。如果共用 session，会把历史上下文串到下一条执行里。

### 4.5 单次模式也使用 batch_id

通过新批量入口创建的执行都写入 `batch_id`。

即使用户只选了一个场景、选择了单次执行，也可以写入 `batch_id`。这样前端可以统一处理“本次提交创建了哪些 execution”。

旧的 `/api/v1/execution` 单条执行接口保持 `batch_id = null`，避免改变旧数据语义。

### 4.6 本期不设计批量任务状态机

本期没有独立的“批量执行任务”。

也就是说，不会新增类似下面这样的持久化状态：

```text
execution_batches.status = queued / running / completed / failed
```

真实状态仍然只存在于单条 execution 上：

```text
execution_jobs.status
```

`batch_id` 的职责只是分组：

- 表示这些 execution 来自同一次用户提交。
- 方便日志排查或后续扩展。
- 支持未来补充批次详情能力。

如果后续产品需要“批次列表”“批次详情”“批次级重试”“批次级取消”“批次级删除”，那就应该新增 `execution_batches` 表，并正式设计批量任务状态机。本期不引入这一层，避免把单条 execution 的语义复杂化。

## 5. API 设计

### 5.1 创建批量执行

```text
POST /api/v1/execution/batch
```

请求体：

```json
{
  "agent_id": "uuid",
  "scenario_ids": ["uuid-1", "uuid-2"],
  "llm_model_id": "uuid",
  "mode": "single",
  "concurrency": 1
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_id` | uuid | 是 | 本次执行使用的 Agent |
| `scenario_ids` | uuid[] | 是 | 选中的场景列表，至少 1 个 |
| `llm_model_id` | uuid nullable | 否 | 比对模型；为空时只执行不自动比对 |
| `mode` | string | 是 | `single` / `concurrent` |
| `concurrency` | int | 否 | 并发模式下每个场景创建多少条 execution；单次模式固定按 1 处理 |

响应：

```json
{
  "batch_id": "uuid",
  "mode": "single",
  "scenario_count": 2,
  "per_scenario_runs": 1,
  "total_executions": 2,
  "execution_ids": ["execution-uuid-1", "execution-uuid-2"],
  "message": "Batch execution started"
}
```

### 5.2 本期不提供批次查询接口

本期只提供批量创建接口，不提供任何批次查询接口。

创建批量执行成功后，前端只需要：

- 根据返回的 `execution_ids` 知道本次创建了哪些 execution。
- 刷新现有执行列表。
- 继续按单条 execution 查看状态、Trace 和比对结果。

因此本期不需要批次聚合状态字段，也不需要定义批次级状态。

如果后续要做批次详情页，再补充批次查询接口。届时也应明确它是“聚合查询接口”，不是“批量任务状态接口”。

## 6. 后端执行流程

### 6.1 创建批次

```text
接收 batch request
  ->
校验 Agent 存在
  ->
校验 LLM Model 存在
  ->
校验 scenario_ids 非空且不重复
  ->
查询所有 Scenario
  ->
校验所有 Scenario 都属于当前 Agent
  ->
计算 total_executions
  ->
校验 total_executions 不超过系统上限
  ->
生成 batch_id
  ->
同步创建所有 execution_jobs(status=queued)
  ->
投递后台批次执行任务
  ->
返回 batch_id 和 execution_ids
```

### 6.2 子执行字段规则

每条子执行写入：

| 字段 | 规则 |
|------|------|
| `id` | 后端提前生成 uuid |
| `agent_id` | 请求中的 Agent |
| `scenario_id` | 当前子执行对应的场景 |
| `llm_model_id` | 请求中的比对模型 |
| `user_session` | `exec_<execution_id.hex>` |
| `run_source` | `normal` |
| `batch_id` | 本次提交生成的批次 ID |
| `trace_id` | 新 uuid |
| `status` | `queued` |
| `original_request` | 当前场景 prompt 的快照 |
| `request_snapshot_json` | 批次模式、场景名、run_index、batch_id 等追溯信息 |

`request_snapshot_json` 示例：

```json
{
  "source": "multi_scenario_batch",
  "mode": "concurrent",
  "batch_id": "uuid",
  "scenario_id": "uuid",
  "scenario_name": "天气查询",
  "run_index": 2,
  "per_scenario_runs": 3,
  "total_executions": 6,
  "prompt_snapshot": "查询深圳今天天气"
}
```

### 6.3 批次后台执行

批次后台任务不再依赖前端传入 prompt，而是执行已创建好的 execution。

```text
run_batch(batch_id)
  ->
读取 batch_id 下所有 queued execution
  ->
按配置的最大后台并行数调度
  ->
每条 execution 调用 ExecutionService.run_execution(execution_id)
```

建议新增系统配置：

```text
batch_execution_max_total = 100
batch_execution_max_parallel = 10
```

说明：

- `batch_execution_max_total` 限制一次提交最多创建多少条 execution。
- `batch_execution_max_parallel` 限制后端同一批次最多同时跑多少条 Agent 调用。
- 用户填写的 `concurrency` 表示每个场景创建多少条 execution。
- 系统配置的 `batch_execution_max_parallel` 是保护后端和 OpenClaw 的真实并行上限。

如果 `total_executions > batch_execution_max_parallel`，超出的 execution 保持排队，在批次后台任务中按信号量逐步执行。

### 6.4 ExecutionService 调整点

当前 `ExecutionService.run_execution` 会重新读取 `scenario.prompt` 作为请求内容。

多场景批量执行建议调整为：

```text
实际 prompt = execution.original_request or scenario.prompt
```

原因：

- 批量创建时已经冻结场景 prompt。
- 如果用户在 execution 排队期间修改了场景 prompt，已经创建的 execution 不应被影响。
- 回放执行也依赖 `original_request` 表示当时真实请求。

边界：

- 旧数据没有 `original_request` 时，继续 fallback 到 `scenario.prompt`。
- 新批量创建的 execution 必须在创建时写入 `original_request`。

## 7. 前端交互设计

### 7.1 新建执行弹窗

保留当前入口：

```text
测试执行列表 -> 新建执行
```

弹窗字段调整为：

- 执行方式：单次执行 / 并发执行
- Agent：单选
- 测试场景：多选
- 比对模型：单选
- 每个场景并发数：仅并发执行时展示

测试场景选择规则：

- 未选择 Agent 前，场景选择禁用。
- 选择 Agent 后，只展示该 Agent 下的场景。
- 支持多选、清空、搜索。
- 切换 Agent 时清空已选场景。

### 7.2 预计执行数提示

弹窗底部展示：

```text
已选择 3 个场景，每个场景执行 5 次，预计创建 15 条执行记录。
```

当预计执行数超过系统上限时：

```text
本次预计创建 150 条执行记录，超过系统上限 100 条，请减少场景或并发数。
```

前端需要在提交前拦截，后端也必须再次校验。

### 7.3 提交后行为

提交成功后：

- 关闭弹窗。
- 刷新执行列表。
- 提示“已创建 X 条执行记录”。
- 不强制跳转批次详情页，因为本期没有新增批次详情页面。

后续如果新增批次详情页，可以改为：

```text
提交成功 -> 跳转 /execution/batches/{batch_id}
```

### 7.4 执行列表展示

本期仍按 execution 粒度展示列表。

多场景批量执行后，列表会出现多条记录：

- 每个场景单次执行一条。
- 每个场景并发执行多条。

建议增加或优化：

- 增加 `batch_id` 简短标识或“批次”Tag。
- 同一批次的执行可以展示相同批次标识。
- 保留现有回放标识。
- 保留按 Agent / 场景筛选。

本期不做批次折叠。如果列表数量过多，后续再设计“批次视图”。

## 8. 并发与一致性

### 8.1 场景和 Agent 一致性

后端必须校验所有 `scenario_ids` 都属于请求中的 `agent_id`。

如果有任意场景不属于该 Agent：

- 整个批次拒绝创建。
- 不创建任何 execution。
- 返回明确错误，例如“所选场景与 Agent 不匹配”。

### 8.2 部分失败处理

批次中的 execution 彼此独立。

如果某条 execution 调用失败：

- 该 execution 标记为 `failed`。
- 其他 execution 继续执行。
- 后续如果提供批次详情页，可以再按 `batch_id` 聚合展示这些 execution 的结果。

不因为一条 execution 失败而取消整个批次。

### 8.3 后台任务重启

本期可以沿用现有后台任务机制，不强制引入任务队列。

但设计上需要承认一个边界：

- 如果服务在 API 创建 execution 后、后台任务执行完成前重启，部分 queued execution 可能停留在 `queued`。

建议后续补恢复任务：

```text
服务启动时扫描 batch_id 不为空且 status=queued 的 normal execution
  ->
按 batch_id 重新投递 run_batch
```

如果本期要加强稳定性，可以把恢复任务纳入实现范围。

### 8.4 重复提交

当前普通执行没有幂等机制，本期可以先通过前端提交中禁用按钮减少重复提交。

如果后续需要强幂等，建议新增 `execution_batches` 表，并增加：

```text
idempotency_key unique
```

本期不建议只把 idempotency_key 放到 `request_snapshot_json` 里做弱查询，因为 JSON 字段无法提供可靠唯一约束。

### 8.5 执行上限

必须设置后端上限，避免一次提交压垮 Agent 或 OpenClaw。

推荐默认：

```text
batch_execution_max_total = 100
batch_execution_max_parallel = 10
```

如果用户选择 20 个场景，并发数 10，总计 200 条 execution，后端必须拒绝。

## 9. 数据库设计

### 9.1 本期推荐

本期不新增表，复用现有：

```text
execution_jobs.batch_id
execution_jobs.request_snapshot_json
execution_jobs.original_request
execution_jobs.user_session
execution_jobs.trace_id
```

原因：

- 当前项目已经有 `batch_id`。
- 执行列表本来就是按 execution 展示。
- 本期目标是让多场景执行能跑通，不新增批次管理页面。

### 9.2 后续增强

如果后续需要批次列表、批次详情、强幂等、批次级删除、批次级重试，建议新增 `execution_batches` 表。

候选字段：

| 字段 | 说明 |
|------|------|
| `id` | 批次 ID |
| `agent_id` | Agent |
| `llm_model_id` | 比对模型 |
| `mode` | single / concurrent |
| `scenario_count` | 场景数量 |
| `per_scenario_runs` | 每个场景执行次数 |
| `total_executions` | 总 execution 数 |
| `status` | 批次状态 |
| `idempotency_key` | 防重复提交 |
| `request_snapshot_json` | 批次请求快照 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

## 10. 测试计划

### 10.1 后端单元测试

需要覆盖：

- 单次模式选择 1 个场景时创建 1 条 execution。
- 单次模式选择 N 个场景时创建 N 条 execution。
- 并发模式选择 N 个场景、并发数 C 时创建 N × C 条 execution。
- 每条 execution 都使用唯一 `user_session`。
- 每条 execution 都使用唯一 `trace_id`。
- 所有子 execution 都写入同一个 `batch_id`。
- 所有子 execution 都写入自己的 `scenario_id`。
- 后端拒绝跨 Agent 的场景。
- 后端拒绝空 `scenario_ids`。
- 后端拒绝超过 `batch_execution_max_total` 的请求。
- 子 execution 使用 `original_request` 中冻结的 prompt 执行。

### 10.2 后端集成测试

需要覆盖：

- `POST /api/v1/execution/batch` 返回 `batch_id` 和完整 `execution_ids`。
- 旧的 `/api/v1/execution` 行为不变。
- 旧的 `/api/v1/execution/concurrent` 行为不变或兼容复用新逻辑。
- 批次中部分 execution 失败时，其他 execution 不受影响。

### 10.3 前端测试

需要覆盖：

- 选择 Agent 后，场景多选列表只展示该 Agent 的场景。
- 切换 Agent 后清空已选场景。
- 单次模式下隐藏并发数字段。
- 并发模式下展示“每个场景并发数”。
- 预计执行数实时变化。
- 超过上限时禁用提交。
- 提交 payload 使用 `scenario_ids` 数组。
- 提交成功后刷新执行列表。

## 11. 实施步骤

### Phase 1：后端批量模型与接口

- 新增 `CreateExecutionBatchRequest`。
- 新增 `ExecutionBatchResponse`。
- 新增 `POST /api/v1/execution/batch`。

### Phase 2：批量执行服务

- 新增 `ExecutionBatchService`，负责批次创建和调度。
- 批次创建时同步创建所有 execution。
- 批次后台任务按 `batch_execution_max_parallel` 控制真实并行。
- 子 execution 复用 `ExecutionService.run_execution`。

### Phase 3：ExecutionService 冻结 prompt

- `create_execution` 时写入 `original_request`。
- `run_execution` 优先使用 `execution.original_request`。
- 旧数据 fallback 到 `scenario.prompt`。

### Phase 4：兼容旧并发入口

- `/execution/concurrent` 可以内部转换为单场景 batch 请求。
- `/execution/concurrent/{batch_id}` 暂时保持现有行为，不新增新的 batch 查询接口。
- 保持前端旧调用不立即失效。

### Phase 5：前端多选改造

- `ExecutionFormValues.scenario_id` 改为 `scenario_ids`。
- 场景 Select 改为 `mode="multiple"`。
- 并发字段文案改为“每个场景并发数”。
- 新增预计执行数提示。
- 提交时调用 `executionApi.createBatch`。

### Phase 6：收尾与文档

- 补齐测试。
- 更新 `CHANGELOG.md`。
- 手工验证单场景、单次多场景、并发多场景。

## 12. 验收标准

完成后需要满足：

- 单次执行可以一次选择多个场景。
- 并发执行可以一次选择多个场景。
- 选择多个场景时，每个场景都会生成独立 execution。
- 并发执行时，总 execution 数等于 `场景数量 × 每个场景并发数`。
- 每条 execution 的 session 都不同。
- 每条 execution 的 trace 都不同。
- 同一次提交的 execution 有相同 batch_id。
- 执行列表能看到所有子 execution。
- 旧的单场景执行和旧的并发执行不受影响。
- 任何跨 Agent 场景混选都会被后端拒绝。
- 超过批量执行上限时前后端都会拦截。

## 13. 待确认点

以下点需要在开发前确认：

- 批量执行上限默认值是否采用 `100`。
- 批次真实后台并行上限默认值是否采用 `10`。
- 本期是否需要服务启动后恢复 `queued` 批量 execution。
- 执行列表是否需要展示 `batch_id` 标识，还是只保留普通 execution 行。
- 新前端是否统一改走 `/execution/batch`，还是只有多场景时走新接口。
