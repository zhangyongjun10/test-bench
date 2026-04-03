# Agent Trace 链路重放功能设计

**版本**: 2.0
**日期**: 2026-04-02
**更新内容**: 新增 tool span 全量存储、逐步 LLM 比对、replay_comparison_results 表、三维度比对评分

## 需求概述

基于已保存的 Opik/Langfuse Agent 调用链路（Trace），对每一个 LLM span 用指定的新模型重新执行，对比原始执行和重放执行的输出差异和性能指标变化。

**核心规则：**
- 重放只针对 LLM 调用，使用用户指定的 LLM 模型逐步重新执行
- 每个 LLM span 的输入固定使用原始 trace 的 `original_input`，不受前一步重放输出影响（保证每步比对的输入条件一致）
- 工具调用跳过，不重新执行，original_input/output 原样保存用于前端链路展示
- 每个 LLM span 重放完成后立即做语义比对（replay_output vs original_output），记录分数和原因
- 全部完成后，可选与 scenario.baseline_result 做最终结果比对
- 前端展示 llm + tool 交替的完整链路，体现真实执行顺序

## 用例

1. 用户在执行详情页点击"启动重放"
2. 选择用于重放和比对评估的 LLM 模型（可选关联场景以启用 baseline 比对）
3. 系统从 ClickHouse 拉取原始 trace 全量 spans（llm + tool）
4. 按顺序逐个重放每个 LLM span，每步立即做语义比对
5. 全部完成后计算聚合指标，触发最终比对（如有 baseline）
6. 前端展示完整链路对比页，含每步比对分数和原因

## 架构设计

遵循项目现有四层架构：API 路由层 → 业务逻辑层 → 领域层 → 外部客户端。

### 目录结构

```
backend/app/
├── api/
│   └── replay.py                   # 新增：回放接口
├── services/
│   └── replay_service.py           # 新增：回放业务逻辑
├── domain/
│   ├── entities/
│   │   └── replay.py               # 新增：ReplayTask, ReplaySpan, ReplayComparisonResult 实体
│   └── repositories/
│       └── replay_repo.py          # 新增：数据访问层
└── migrations/versions/
    └── XXX_add_replay_tables.py    # 新增：数据库迁移

frontend/src/
├── pages/
│   └── ReplayDetail.tsx            # 新增：重放详情对比页
└── api/
    ├── client.ts                   # 修改：添加 replay API 方法
    └── types.ts                    # 修改：添加 replay 类型定义
```

## 数据模型设计

### ReplayTask（重放任务）

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| id | UUID | 否 | 主键 |
| original_execution_id | UUID | 否 | FK → execution_jobs.id |
| llm_model_id | UUID | 否 | 用于重放调用和比对评估的 LLM 模型 |
| scenario_id | UUID | 是 | FK → scenarios.id，存在则启用 baseline 比对 |
| status | String | 否 | queued/running/completed/failed |
| comparison_status | String | 否 | pending/processing/completed/failed，默认 pending |
| total_llm_spans | int | 否 | 需重放的 LLM span 总数 |
| completed_llm_spans | int | 否 | 已完成重放数量（前端进度展示） |
| aggregated_metrics | JSON | 是 | LLM 性能聚合对比（见下方结构） |
| llm_trace_score | Double | 是 | 所有 LLM span 语义比对均分（0-100） |
| llm_baseline_score | Double | 是 | 最终输出 vs scenario.baseline_result（0-100），无 scenario_id 则为 NULL |
| overall_passed | Boolean | 是 | 两个分数均达阈值则为 true |
| error_message | String | 是 | 失败原因 |
| created_at | DateTime | 否 | |
| started_at | DateTime | 是 | |
| completed_at | DateTime | 是 | |

**聚合指标结构（aggregated_metrics JSON）：**

```python
@dataclass
class AggregatedMetrics:
    # 原始
    original_total_input_tokens: int
    original_total_output_tokens: int
    original_avg_ttft_ms: Optional[float]
    original_avg_tpot_ms: Optional[float]
    # 重放
    replay_total_input_tokens: int
    replay_total_output_tokens: int
    replay_avg_ttft_ms: Optional[float]
    replay_avg_tpot_ms: Optional[float]
```

---

### ReplaySpan（单个步骤记录，llm + tool 全量存储）

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| id | UUID | 否 | 主键 |
| replay_task_id | UUID | 否 | FK → replay_tasks.id |
| original_span_id | String | 否 | 原始 span ID |
| span_type | String | 否 | `llm` / `tool` |
| span_name | String | 否 | span 名称 |
| order | int | 否 | 执行顺序（llm + tool 统一按 start_time 排序） |
| original_input | Text | 是 | 原始输入（消息列表 JSON 或工具参数） |
| original_output | Text | 是 | 原始输出 |
| original_metrics | JSON | 是 | llm span：ttft/tpot/tokens；tool span：duration_ms |
| replay_output | Text | 是 | **仅 llm span**：重放输出；tool span 为 NULL |
| replay_metrics | JSON | 是 | **仅 llm span**：重放 ttft/tpot/tokens；tool span 为 NULL |
| comparison_score | Double | 是 | **仅 llm span**：replay_output vs original_output 语义分（0-1） |
| comparison_consistent | Boolean | 是 | **仅 llm span**：是否语义一致 |
| comparison_reason | Text | 是 | **仅 llm span**：比对原因说明 |
| created_at | DateTime | 否 | |
| completed_at | DateTime | 是 | llm span 重放完成时间 |

**字段填充规则：**
- `tool span`：`replay_output`、`replay_metrics`、`comparison_*` 三类字段永远为 NULL，仅用于前端链路展示
- `llm span`：所有字段均填充

---

### ReplayComparisonResult（回放比对结果，支持重新比对历史）

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| id | UUID | 否 | 主键 |
| replay_task_id | UUID | 否 | FK → replay_tasks.id，索引 |
| llm_trace_score | Double | 是 | 所有 LLM span 比对均分（0-100） |
| llm_baseline_score | Double | 是 | 最终输出 vs baseline（0-100），无 scenario_id 则为 NULL |
| overall_passed | Boolean | 是 | 总体通过 |
| details_json | Text | 是 | 每个 llm span 的比对详情数组（span_name, score, consistent, reason） |
| status | String | 否 | pending/processing/completed/failed |
| error_message | Text | 是 | 比对失败原因 |
| retry_count | int | 否 | 已重试次数，默认 0 |
| created_at | DateTime | 否 | |
| completed_at | DateTime | 是 | |

**details_json 结构（数组）：**

```json
[
  {
    "span_name": "llm_call_1",
    "order": 1,
    "original_output": "...",
    "replay_output": "...",
    "score": 0.92,
    "consistent": true,
    "reason": "语义一致，措辞有细微差异"
  }
]
```

---

## API 接口设计

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v1/replay/start` | 启动重放任务 |
| GET | `/api/v1/replay/{id}` | 获取重放任务摘要（含比对分数） |
| GET | `/api/v1/replay/{id}/detail` | 获取完整 spans 列表（llm+tool 按 order 排序） |
| GET | `/api/v1/replay/{id}/comparison` | 获取比对详情（details_json 展开） |
| POST | `/api/v1/replay/{id}/recompare` | 重新触发比对（后台任务） |
| DELETE | `/api/v1/replay/{id}` | 删除重放任务 |

### POST `/api/v1/replay/start` 请求体

```json
{
  "original_execution_id": "uuid",
  "llm_model_id": "uuid",
  "scenario_id": "uuid"
}
```

`scenario_id` 可选，存在时启用 `llm_baseline_score` 比对。

响应：

```json
{
  "code": 0,
  "data": {
    "replay_id": "uuid"
  }
}
```

---

## 执行流程

```
用户在执行详情页点击"启动重放"
  ↓
选择 LLM 模型（可选关联场景）→ 确认启动
  ↓
POST /api/v1/replay/start
  ↓
replay_service.start_replay：
  1. 获取原始 execution，校验 trace_id 存在
  2. 从 ClickHouse 拉取原始 trace 全量 spans（llm + tool）
  3. 按 start_time 升序排序
  4. 创建 ReplayTask（status=QUEUED，total_llm_spans=llm span 数量）
  5. 为所有 span 创建 ReplaySpan：
     - llm span → replay_output/metrics/comparison_* 字段全为 NULL，待填
     - tool span → 只存 original 数据，replay 字段永远 NULL
  6. 后台任务触发 run_replay
  ↓
返回 replay_id，前端跳转到重放详情页并开始轮询
  ↓
run_replay 后台异步执行：
  ↓
  status = RUNNING，started_at = now()
  ↓
  按 order 顺序处理每个 ReplaySpan：

    llm span：
      → 取 original_input（固定不变，不依赖前一步重放输出）
      → 调用指定 LLM 模型
      → 写入 replay_output 和 replay_metrics（ttft/tpot/tokens）
      → 立即调用 ComparisonService（复用现有服务）：
          replay_output vs original_output
          → 写入 comparison_score / comparison_consistent / comparison_reason
      → completed_llm_spans += 1，更新 ReplayTask 进度

    tool span：
      → 跳过，不执行任何操作

  ↓
  全部 llm span 处理完：
    → 计算 aggregated_metrics（仅基于 llm spans 的原始 vs 重放均值）
    → llm_trace_score = avg(所有 llm span comparison_score) * 100
    → status = COMPLETED，comparison_status = processing
    → 后台触发比对任务
  ↓
比对任务（后台）：
  → 创建 ReplayComparisonResult 记录（status=processing）
  → 汇总 details_json（从各 llm span 的 comparison_* 字段聚合）
  → 如果 scenario_id 存在：
      取最后一个 llm span 的 replay_output
      调用 ComparisonService vs scenario.baseline_result
      → 写入 llm_baseline_score
  → 计算 overall_passed：
      有 baseline：llm_trace_score >= process_threshold AND llm_baseline_score >= result_threshold
      无 baseline：llm_trace_score >= process_threshold
  → 更新 ReplayComparisonResult status=completed
  → 同步更新 ReplayTask：llm_trace_score / llm_baseline_score / overall_passed / comparison_status=completed
  ↓
前端轮询 /api/v1/replay/{id} 获取状态
  ↓
comparison_status=completed 后展示完整比对结果
```

---

## 阈值配置

复用 `scenarios` 表的现有字段，不新增阈值字段：

| 回放比对维度 | 复用的阈值字段 | 含义 |
|---|---|---|
| `llm_trace_score` | `scenarios.process_threshold` | 衡量每步 LLM 输出的稳定性 |
| `llm_baseline_score` | `scenarios.result_threshold` | 衡量最终结果是否满足业务预期 |

无关联 scenario 时，`overall_passed` 仅基于 `llm_trace_score`，阈值使用系统默认值 60.0。

---

## 前端设计

### 页面结构（ReplayDetail.tsx）

**1. 头部信息卡片**
- 重放状态标签、进度条（completed_llm_spans / total_llm_spans）
- 关联原始执行 ID（可点击跳转）
- 使用的 LLM 模型名称
- 关联场景名称（如有）

**2. 聚合指标对比卡片**

| 指标 | 原始 | 重放 | 差异 |
|------|------|------|------|
| 总输入 Tokens | xxx | xxx | ±x |
| 总输出 Tokens | xxx | xxx | ±x |
| 平均 TTFT (ms) | xxx | xxx | ±x |
| 平均 TPOT (ms) | xxx | xxx | ±x |

**3. 比对结论卡片**（`comparison_status=completed` 后展示）

- `llm_trace_score`：xx/100 + 通过/不通过标签
- `llm_baseline_score`：xx/100 + 通过/不通过标签（无 scenario_id 时隐藏）
- `overall_passed`：总体结论标签（绿色通过 / 红色不通过）
- "重新比对"按钮（触发 POST recompare，前端轮询刷新）

**4. 完整链路卡片**（Collapse 列表，按 order 排序，llm + tool 交替展示）

```
[LLM] llm_call_1                                    得分：92/100 ✓
  ├── 原始输入：[消息列表...]
  ├── 左栏 原始输出：...     右栏 重放输出：...
  ├── 左栏 原始指标          右栏 重放指标（ttft/tpot/tokens）
  └── 比对结论：consistent=true | reason="语义一致，措辞有细微差异"

[TOOL] search_tool（灰色，标注"工具调用 · 使用原始输出"）
  ├── 输入：{"query": "xxx"}
  └── 输出：{"result": "..."}

[LLM] llm_call_2                                    得分：78/100 ✓
  └── ...
```

### 入口修改（ExecutionDetail.tsx）

- 新增"启动重放"按钮
- 点击弹出模态框：选择 LLM 模型（必填）+ 关联场景（可选）
- 确认后跳转到 `/replay/{id}` 页面

---

## 数据库迁移

新建迁移脚本，创建三张表：

```
replay_tasks
replay_spans
replay_comparison_results
```

外键关联：
- `replay_tasks.original_execution_id` → `execution_jobs.id`
- `replay_tasks.llm_model_id` → `llm_models.id`
- `replay_tasks.scenario_id` → `scenarios.id`（nullable）
- `replay_spans.replay_task_id` → `replay_tasks.id`
- `replay_comparison_results.replay_task_id` → `replay_tasks.id`

---

## 设计决策记录

| 决策点 | 结论 | 原因 |
|--------|------|------|
| 工具调用是否重新执行 | 否，使用原始 trace 输出 | Agent 工具为黑盒，且重执行的级联效应让比对意义不清晰 |
| 每步 LLM 输入是否依赖前一步重放输出 | 否，固定使用 original_input | 避免误差级联传播，保证每步比对的输入条件一致可控 |
| tool span 是否存入 replay_spans | 是，只存 original 数据 | 前端需展示完整 llm + tool 交替链路，体现真实执行顺序 |
| process_score（tool 次数/顺序比对）| 不做 | 输入固定则 tool 次数由原始 trace 决定，比对无意义 |
| 比对阈值 | 复用 scenarios.process_threshold / result_threshold | 避免新增冗余配置字段 |
| 每步比对时机 | 每个 LLM span 重放完立即比对 | 不等全部完成再批量比对，进度更实时，单步失败不阻塞整体 |
| 比对结果存储 | 独立 replay_comparison_results 表 | 支持重新比对历史，与 replay_spans 的逐步记录解耦 |

---

## 与回归比对（comparison_results）的关系

| 对比维度 | 回归比对（comparison_results） | 回放比对（replay_comparison_results） |
|---------|-------------------------------|--------------------------------------|
| 触发时机 | 场景执行完成后自动触发 | 重放任务完成后触发 |
| 比对对象 | actual trace vs scenario baseline | replay trace vs original trace + baseline |
| LLM 比对维度 | 只比最后一个 LLM 输出 vs baseline | 每步 LLM 输出 vs 原始输出（逐步）+ 最终 vs baseline |
| 过程比对 | tool 调用次数/顺序/输入输出 vs baseline_tool_calls | 不做（输入固定则无意义） |
| 核心问题 | "这次执行结果是否符合预期？" | "换一个 LLM 模型，每步行为和最终结果是否一致？" |

---

## 范围边界

**本次实现包含：**
- 后端：ReplayTask / ReplaySpan / ReplayComparisonResult 数据模型、API、业务逻辑
- 后端：每步 LLM 重放 + 立即比对（复用 ComparisonService）
- 后端：tool span 全量存储，仅用于展示
- 后端：数据库迁移
- 前端：重放详情对比页（完整链路展示 + 比对结论）
- 前端：从执行详情页启动重放入口（选模型 + 可选关联场景）

**不包含：**
- 工具调用重新执行
- 多次重放结果横向对比（只展示最近一次）
- 重放历史列表页（从执行详情进入即可）
