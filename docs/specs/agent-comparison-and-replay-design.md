# Agent 比对与回放功能设计

**版本**: 1.0
**日期**: 2026-04-02
**整合自**: agent-regression-comparison-design.md + agent-trace-replay-design.md

---

## 目录

- [1. 功能概览与边界](#1-功能概览与边界)
- [2. 共享基础设施](#2-共享基础设施)
- [3. 回归比对（Regression Comparison）](#3-回归比对regression-comparison)
- [4. 链路回放（Trace Replay）](#4-链路回放trace-replay)
- [5. 数据库迁移清单](#5-数据库迁移清单)
- [6. 关键文件清单](#6-关键文件清单)
- [7. 验收测试要点](#7-验收测试要点)

---

## 1. 功能概览与边界

平台提供两种独立的比对分析能力，解决不同场景的问题：

| 维度 | 回归比对 | 链路回放 |
|------|---------|---------|
| **核心问题** | "这次执行结果是否符合预期基线？" | "换一个 LLM 模型，每步行为和最终结果是否一致？" |
| **触发时机** | Agent 场景执行完成后自动触发 | 用户手动启动重放任务 |
| **比对基准** | 人工设定的 `baseline_tool_calls` + `baseline_result` | 原始 trace 本身（每步 LLM span 输出）+ 可选 baseline |
| **LLM 比对** | 只比最后一个 LLM 输出 vs baseline | 每步 LLM 输出逐步与原始比对 + 最终 vs baseline |
| **过程比对** | tool 调用次数/顺序/输入输出 vs baseline_tool_calls | 不做（输入固定，无意义） |
| **适用场景** | Agent 代码变更后验证功能正确性 | 替换底层 LLM 模型后验证行为稳定性 |

---

## 2. 共享基础设施

两个功能共用以下组件，不重复实现。

### 2.1 比对算法（ComparisonService）

**两阶段策略**（对所有文本比对统一适用）：

1. **JSON 预处理**：内容以 `{` 或 `[` 开头时，去除 Markdown 包裹，解析后用 `sort_keys=True` 重新序列化，消除格式差异；解析失败则使用原文。
2. **算法粗筛**：Levenshtein 编辑距离计算相似度

| 相似度范围 | 处理方式 |
|-----------|---------|
| ≥ 0.9 | 直接满分 1.0，跳过 LLM 调用 |
| < 0.9 | 调用 LLM 做语义验证 |

**LLM 调用控制**：
- `asyncio.Semaphore` 限制最大并发数（MAX_CONCURRENT_LLM = 5）
- 失败自动指数退避重试 3 次，仍失败该项得 0 分
- `enable_llm_verification = false` 时跳过 LLM，只用算法相似度

**超长内容处理**：单个字段超过 8000 字符时截断，截断处加 `[...truncated]` 标记。

### 2.2 前端轮询约定

- 轮询间隔：2 秒
- 最大超时：2 分钟，超时停止轮询，提示用户手动刷新
- 适用：比对状态轮询、重放进度轮询

### 2.3 阈值配置

阈值统一配置在 `scenarios` 表，两个功能共用，不新增全局配置字段：

| 字段 | 默认值 | 回归比对用途 | 回放比对用途 |
|------|--------|------------|------------|
| `process_threshold` | 60.0 | tool 过程比对通过线 | llm_trace_score 通过线 |
| `result_threshold` | 60.0 | LLM 结果比对通过线 | llm_baseline_score 通过线 |

---

## 3. 回归比对（Regression Comparison）

### 3.1 业务目标

Agent 开发人员修改代码后，执行场景测试时自动验证：
1. **过程一致性**：Tool 调用次数、输入输出是否和基线一致
2. **结果一致性**：最终 LLM 输出是否和基线一致

### 3.2 数据库设计

#### 修改 `scenarios` 表（新增字段）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `baseline_tool_calls` | Text (JSON) | NULL | 过程基线：JSON 数组，每个元素 `{name, input, output}` |
| `baseline_result` | Text | NULL | 结果基线：最后一个 LLM 输出文本 |
| `process_threshold` | Double | 60.0 | 过程分数通过阈值 |
| `result_threshold` | Double | 60.0 | 结果分数通过阈值 |
| `tool_count_tolerance` | Integer | 0 | tool 调用次数允许浮动范围。例如：基线 3 次，容忍 1 → 实际 2~4 次均通过第一步 |
| `compare_enabled` | Boolean | true | false 时执行完成后不触发比对 |
| `enable_llm_verification` | Boolean | true | false 时只做算法粗筛，节省 LLM 成本 |

#### 修改 `ExecutionStatus` 枚举

新增：`COMPLETED_WITH_MISMATCH = "completed_with_mismatch"`（执行成功但比对不通过）

#### 新表：`comparison_results`

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `id` | UUID | 否 | 主键 |
| `execution_id` | UUID | 否 | FK → `execution_jobs.id`，索引 |
| `scenario_id` | UUID | 否 | FK → `scenarios.id`，索引 |
| `trace_id` | String | 是 | 关联的 trace ID |
| `process_score` | Double | 是 | 过程分数 0-100，无 baseline_tool_calls 时为 NULL |
| `result_score` | Double | 是 | 结果分数 0-100，无 baseline_result 时为 NULL |
| `overall_passed` | Boolean | 是 | 总体是否通过 |
| `details_json` | Text | 是 | 详细比对结果 JSON（每个 tool/llm 的比对详情） |
| `status` | String | 否 | pending / processing / completed / failed |
| `error_message` | Text | 是 | 比对失败原因 |
| `retry_count` | Integer | 否 | 已重试次数，默认 0 |
| `created_at` | DateTime(tz) | 否 | |
| `updated_at` | DateTime(tz) | 否 | 自动更新 |
| `completed_at` | DateTime(tz) | 是 | |

**details_json 结构：**

```json
{
  "tool_comparisons": [
    {
      "tool_name": "search",
      "baseline_input": "...", "baseline_output": "...",
      "actual_input": "...", "actual_output": "...",
      "similarity": 0.85, "score": 0.9,
      "consistent": true, "reason": "...", "matched": true
    }
  ],
  "llm_comparison": {
    "baseline_output": "...", "actual_output": "...",
    "similarity": 0.92, "score": 0.95,
    "consistent": true, "reason": "..."
  }
}
```

### 3.3 比对逻辑

#### 过程比对（baseline_tool_calls 不为空时执行）

1. **次数检查**：`abs(actual_count - baseline_count) > tool_count_tolerance` → 全部 tool 得 0 分，直接跳到汇总
2. **最优匹配**（贪心算法，不要求顺序）：
   - tool 名称不同直接跳过（得 0 分）
   - 名称相同则计算 `sim = (input_sim + output_sim) / 2`
   - 每个实际 tool 匹配相似度最高的未匹配基线 tool
   - 未匹配到的 tool（双向）得 0 分，计入平均分
3. 对每个匹配对执行两阶段策略（JSON 预处理 + 算法/LLM 评分）
4. `process_score = avg(所有 tool 分数) * 100`

#### 结果比对（baseline_result 不为空时执行）

1. 取 trace 中**最后一个** LLM span 的 output
2. 执行两阶段策略
3. `result_score = score * 100`

#### 汇总判定

| 情况 | overall_passed |
|------|---------------|
| 只有过程比对 | `process_score >= process_threshold` |
| 只有结果比对 | `result_score >= result_threshold` |
| 两者都有 | `process_score >= process_threshold AND result_score >= result_threshold` |
| 无基线 | NULL（不判定） |

`overall_passed = false` → `execution.status = COMPLETED_WITH_MISMATCH`

### 3.4 执行流程

```
场景执行完成（run_execution）
  ↓
如果 scenario.compare_enabled = true 且有 llm_model_id：
  → 后台触发详细比对（BackgroundTasks）
  ↓
比对服务（ComparisonService.detailed_compare）：
  1. 从 spans 提取 tool_spans 和 llm_spans
  2. 执行过程比对（如有 baseline_tool_calls）
  3. 执行结果比对（如有 baseline_result）
  4. 汇总分数，判断 overall_passed
  5. 创建 comparison_results 记录
  6. 更新 execution：comparison_score / comparison_passed / status
```

### 3.5 基线管理

**方式一：从执行一键设置**
- 执行详情页点击"设为基线"
- 自动从该执行的 trace 提取所有 tool span（name/input/output）和最后一个 LLM span output
- 写入 `scenario.baseline_tool_calls` 和 `scenario.baseline_result`

**方式二：手动编辑**
- 场景编辑页直接编辑 JSON，支持微调
- 清空 JSON 即可删除基线（无需专门清除按钮）

### 3.6 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/execution/{id}/comparison` | 获取最新比对详情 |
| POST | `/api/v1/execution/{id}/recompare` | 触发重新比对（后台） |
| POST | `/api/v1/scenario/{id}/set-baseline/{execution_id}` | 将指定执行设为基线 |

### 3.7 前端

**ExecutionDetail.tsx**（新增"比对详情"卡片）：
- 展示 `process_score` / `result_score`，分别标记通过/不通过
- 展示 `overall_passed` 总体结论标签
- Collapse 展开查看每个 tool 和 LLM 的比对详情
- "重新比对"按钮 + "设为基线"按钮
- `status = failed` 时展示错误 Alert

**ScenarioEdit.tsx**（新增基线编辑区域）：
- `baseline_tool_calls` JSON 编辑框
- `baseline_result` 文本编辑框
- `compare_enabled` / `enable_llm_verification` 开关

### 3.8 设计决策

| 决策点 | 结论 |
|--------|------|
| Tool 名称匹配 | 名称不同直接得 0 分，不进入输入输出比对 |
| 匹配算法 | MVP 贪心算法，接口抽象，后续可替换为匈牙利算法 |
| 比对失败时 execution 状态 | 保持 COMPLETED，只将 comparison 标记 failed（执行本身已成功） |
| 基线更新后旧结果 | 旧比对结果不自动重算，用户手动触发重比对 |
| 未匹配 tool 计分 | 得 0 分计入平均，惩罚少调用/多调用行为 |
| 随机字段（UUID/时间戳） | MVP 不处理，后续迭代支持忽略规则配置 |

---

## 4. 链路回放（Trace Replay）

### 4.1 业务目标

对已完成的执行，用指定的新 LLM 模型逐步重新执行每一个 LLM span，验证：
1. **每步稳定性**：给定相同输入，新模型与原模型的输出是否语义一致（`llm_trace_score`）
2. **最终正确性**：新模型的最终输出是否仍满足业务预期（`llm_baseline_score`，可选）

**核心约束**：
- 每步 LLM 输入固定使用原始 trace 的 `original_input`，不受前一步重放输出影响，保证比对条件一致可控
- 工具调用跳过，使用原始输出，只存储用于前端链路展示
- 不做 process_score（tool 次数/顺序）比对——输入固定则 tool 次数由原始 trace 决定，无比对意义

### 4.2 数据库设计

#### 新表：`replay_tasks`

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| id | UUID | 否 | 主键 |
| original_execution_id | UUID | 否 | FK → execution_jobs.id |
| llm_model_id | UUID | 否 | FK → llm_models.id，用于重放调用和比对 |
| scenario_id | UUID | 是 | FK → scenarios.id，存在则启用 baseline 比对 |
| status | String | 否 | queued / running / completed / failed |
| comparison_status | String | 否 | pending / processing / completed / failed，默认 pending |
| total_llm_spans | int | 否 | 需重放的 LLM span 总数 |
| completed_llm_spans | int | 否 | 已完成重放数量（前端进度） |
| aggregated_metrics | JSON | 是 | 原始 vs 重放的 ttft/tpot/tokens 均值对比 |
| llm_trace_score | Double | 是 | 所有 LLM span 比对均分（0-100） |
| llm_baseline_score | Double | 是 | 最终输出 vs baseline（0-100），无 scenario_id 时为 NULL |
| overall_passed | Boolean | 是 | 两个分数均达阈值则为 true |
| error_message | String | 是 | 失败原因 |
| created_at | DateTime | 否 | |
| started_at | DateTime | 是 | |
| completed_at | DateTime | 是 | |

**aggregated_metrics JSON 结构：**

```python
@dataclass
class AggregatedMetrics:
    original_total_input_tokens: int
    original_total_output_tokens: int
    original_avg_ttft_ms: Optional[float]
    original_avg_tpot_ms: Optional[float]
    replay_total_input_tokens: int
    replay_total_output_tokens: int
    replay_avg_ttft_ms: Optional[float]
    replay_avg_tpot_ms: Optional[float]
```

#### 新表：`replay_spans`

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| id | UUID | 否 | 主键 |
| replay_task_id | UUID | 否 | FK → replay_tasks.id |
| original_span_id | String | 否 | 原始 span ID |
| span_type | String | 否 | `llm` / `tool` |
| span_name | String | 否 | span 名称 |
| order | int | 否 | 执行顺序（llm + tool 按 start_time 统一排序） |
| original_input | Text | 是 | 原始输入 |
| original_output | Text | 是 | 原始输出 |
| original_metrics | JSON | 是 | llm span：ttft/tpot/tokens；tool span：duration_ms |
| replay_output | Text | 是 | **仅 llm span**，重放输出；tool span 为 NULL |
| replay_metrics | JSON | 是 | **仅 llm span**，重放指标；tool span 为 NULL |
| comparison_score | Double | 是 | **仅 llm span**，replay vs original 语义分（0-1） |
| comparison_consistent | Boolean | 是 | **仅 llm span** |
| comparison_reason | Text | 是 | **仅 llm span**，比对原因说明 |
| created_at | DateTime | 否 | |
| completed_at | DateTime | 是 | llm span 重放完成时间 |

> tool span 的 `replay_output`、`replay_metrics`、`comparison_*` 字段永远为 NULL，仅 `original_*` 字段有值，用于前端链路展示。

#### 新表：`replay_comparison_results`

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| id | UUID | 否 | 主键 |
| replay_task_id | UUID | 否 | FK → replay_tasks.id，索引 |
| llm_trace_score | Double | 是 | 所有 LLM span 比对均分（0-100） |
| llm_baseline_score | Double | 是 | 最终输出 vs baseline（0-100），无 scenario_id 则为 NULL |
| overall_passed | Boolean | 是 | 总体通过 |
| details_json | Text | 是 | 每个 llm span 的比对详情数组 |
| status | String | 否 | pending / processing / completed / failed |
| error_message | Text | 是 | |
| retry_count | int | 否 | 默认 0 |
| created_at | DateTime | 否 | |
| completed_at | DateTime | 是 | |

**details_json 结构：**

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

### 4.3 执行流程

```
用户在执行详情页点击"启动重放"
  ↓
弹出模态框：选择 LLM 模型（必填）+ 关联场景（可选）→ 确认
  ↓
POST /api/v1/replay/start
  ↓
replay_service.start_replay：
  1. 校验原始 execution 存在且有 trace_id
  2. 从 ClickHouse 拉取原始 trace 全量 spans（llm + tool）
  3. 按 start_time 升序排序
  4. 创建 ReplayTask（status=QUEUED，total_llm_spans=llm span 数量）
  5. 为所有 span 创建 ReplaySpan：
     - llm span：replay_output/metrics/comparison_* 全为 NULL，待填
     - tool span：只存 original 数据，replay 字段永远 NULL
  6. 后台触发 run_replay
  ↓
返回 replay_id，前端跳转到 /replay/{id} 并开始轮询
  ↓
run_replay（后台）：
  status = RUNNING，started_at = now()
  ↓
  按 order 顺序处理每个 ReplaySpan：

    llm span：
      → 取 original_input（固定，不依赖前一步重放输出）
      → 调用指定 LLM 模型，记录 replay_output 和 replay_metrics
      → 立即调用 ComparisonService：replay_output vs original_output
      → 写入 comparison_score / comparison_consistent / comparison_reason
      → completed_llm_spans += 1，更新 ReplayTask 进度

    tool span：
      → 跳过

  ↓
  全部 llm span 处理完：
    → 计算 aggregated_metrics
    → llm_trace_score = avg(所有 llm span comparison_score) * 100
    → status = COMPLETED，comparison_status = processing
    → 后台触发汇总比对任务
  ↓
汇总比对任务（后台）：
  → 创建 ReplayComparisonResult（status=processing）
  → 聚合 details_json（从各 llm span comparison_* 字段）
  → 如果 scenario_id 存在：
      取最后一个 llm span 的 replay_output
      调用 ComparisonService vs scenario.baseline_result
      → 写入 llm_baseline_score
  → 计算 overall_passed：
      有 baseline：llm_trace_score >= process_threshold AND llm_baseline_score >= result_threshold
      无 baseline：llm_trace_score >= process_threshold（默认阈值 60.0）
  → 更新 ReplayComparisonResult status=completed
  → 同步更新 ReplayTask：llm_trace_score / llm_baseline_score / overall_passed / comparison_status=completed
```

### 4.4 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/replay/start` | 启动重放 |
| GET | `/api/v1/replay/{id}` | 任务摘要（含比对分数、进度） |
| GET | `/api/v1/replay/{id}/detail` | 完整 spans（llm+tool 按 order 排序） |
| GET | `/api/v1/replay/{id}/comparison` | 比对详情（details_json 展开） |
| POST | `/api/v1/replay/{id}/recompare` | 重新触发汇总比对 |
| DELETE | `/api/v1/replay/{id}` | 删除重放任务 |

**POST /api/v1/replay/start 请求体：**

```json
{
  "original_execution_id": "uuid",
  "llm_model_id": "uuid",
  "scenario_id": "uuid"
}
```

### 4.5 前端（ReplayDetail.tsx）

**1. 头部信息卡片**
- 重放状态标签、进度条（completed_llm_spans / total_llm_spans）
- 关联原始执行 ID（可跳转）、使用的 LLM 模型、关联场景（如有）

**2. 聚合指标对比卡片**

| 指标 | 原始 | 重放 | 差异 |
|------|------|------|------|
| 总输入 Tokens | xxx | xxx | ±x |
| 总输出 Tokens | xxx | xxx | ±x |
| 平均 TTFT (ms) | xxx | xxx | ±x |
| 平均 TPOT (ms) | xxx | xxx | ±x |

**3. 比对结论卡片**（comparison_status=completed 后展示）
- `llm_trace_score`：xx/100 + 通过/不通过
- `llm_baseline_score`：xx/100（无 scenario_id 时隐藏）
- `overall_passed`：总体结论标签
- "重新比对"按钮

**4. 完整链路卡片**（Collapse，按 order 交替展示 LLM + tool）

```
[LLM] llm_call_1                                    得分：92/100 ✓
  ├── 原始输入：[消息列表...]
  ├── 左栏 原始输出 / 右栏 重放输出
  ├── 左栏 原始指标 / 右栏 重放指标（ttft/tpot/tokens）
  └── 比对结论：consistent=true | reason="语义一致，措辞有细微差异"

[TOOL] search_tool（灰色 · "工具调用 · 使用原始输出"）
  ├── 输入：{"query": "xxx"}
  └── 输出：{"result": "..."}

[LLM] llm_call_2                                    得分：78/100 ✓
  └── ...
```

### 4.6 设计决策

| 决策点 | 结论 | 原因 |
|--------|------|------|
| 工具调用是否重新执行 | 否 | Agent 工具为黑盒；重执行的级联效应让比对意义不清晰 |
| 每步 LLM 输入是否依赖前一步重放输出 | 否，固定用 original_input | 避免误差级联传播，保证每步比对输入条件一致 |
| tool span 是否存入 replay_spans | 是，只存 original | 前端展示完整 llm+tool 交替链路 |
| process_score（tool 次数/顺序） | 不做 | 输入固定时 tool 次数由原始 trace 决定，无比对意义 |
| 每步比对时机 | 每个 LLM span 重放完立即比对 | 进度更实时，单步失败不阻塞整体 |
| 比对结果存储 | 独立 replay_comparison_results 表 | 支持重新比对历史，与 replay_spans 逐步记录解耦 |

---

## 5. 数据库迁移清单

| 迁移文件 | 内容 |
|---------|------|
| `0004_add_comparison_features.py` | 新建 `comparison_results` 表；修改 `scenarios` 表新增 7 个字段；修改 `ExecutionStatus` 枚举新增 `COMPLETED_WITH_MISMATCH` |
| `0005_add_replay_tables.py` | 新建 `replay_tasks`、`replay_spans`、`replay_comparison_results` 三张表 |

---

## 6. 关键文件清单

### 回归比对

| 操作 | 文件路径 | 说明 |
|------|---------|------|
| 修改 | `backend/app/domain/entities/scenario.py` | 新增 baseline + 配置字段 |
| 修改 | `backend/app/domain/entities/execution.py` | 新增 COMPLETED_WITH_MISMATCH 状态 |
| 新建 | `backend/app/domain/entities/comparison.py` | ComparisonResult 实体 |
| 新建 | `backend/app/domain/repositories/comparison_repo.py` | 仓储接口 + SQLAlchemy 实现 |
| 修改 | `backend/app/models/scenario.py` | Pydantic schema 新增字段 |
| 新建 | `backend/app/models/comparison.py` | 比对相关 Pydantic schema |
| 修改 | `backend/app/services/comparison.py` | 扩展 detailed_compare 方法 |
| 修改 | `backend/app/services/execution_service.py` | 执行完成后触发详细比对 |
| 修改 | `backend/app/api/execution.py` | 新增 comparison / recompare 接口 |
| 修改 | `backend/app/api/scenario.py` | 新增 set-baseline 接口 |
| 修改 | `backend/requirements.txt` | 添加 python-Levenshtein |
| 修改 | `frontend/src/api/types.ts` | 新增比对相关类型 |
| 修改 | `frontend/src/api/client.ts` | 新增 getComparison / recompare / setBaseline |
| 修改 | `frontend/src/pages/ExecutionDetail.tsx` | 新增比对详情卡片 + 设为基线按钮 |
| 修改 | `frontend/src/pages/ScenarioEdit.tsx` | 新增基线编辑区域 |

### 链路回放

| 操作 | 文件路径 | 说明 |
|------|---------|------|
| 新建 | `backend/app/domain/entities/replay.py` | ReplayTask / ReplaySpan / ReplayComparisonResult 实体 |
| 新建 | `backend/app/domain/repositories/replay_repo.py` | 仓储接口 + SQLAlchemy 实现 |
| 新建 | `backend/app/models/replay.py` | Pydantic schema |
| 新建 | `backend/app/services/replay_service.py` | 回放业务逻辑（start_replay / run_replay） |
| 新建 | `backend/app/api/replay.py` | 回放 API 路由 |
| 修改 | `frontend/src/api/types.ts` | 新增 replay 相关类型 |
| 修改 | `frontend/src/api/client.ts` | 新增 replay API 方法 |
| 新建 | `frontend/src/pages/ReplayDetail.tsx` | 重放详情对比页 |
| 修改 | `frontend/src/pages/ExecutionDetail.tsx` | 新增"启动重放"按钮 + 模态框 |

---

## 7. 验收测试要点

### 回归比对 - 单元测试

- [ ] Levenshtein 相似度计算正确（完全相同/完全不同/部分相似）
- [ ] JSON 标准化：格式不同内容相同的 JSON 标准化后相同
- [ ] JSON 标准化：正确去除 Markdown 包裹
- [ ] JSON 标准化：解析失败返回原文，不抛异常
- [ ] tool 名称不同直接得 0 分
- [ ] tool 次数差异超过容忍度时 process_score = 0
- [ ] 最优匹配能正确找到最大相似度匹配（顺序不同的内容对能匹配上）
- [ ] 空基线正确处理：未设置的部分自动跳过
- [ ] 多个 LLM 只比对最后一个
- [ ] 汇总分数计算正确（平均分 × 100，单分量正确处理）
- [ ] LLM 重试机制正确（3 次失败后该项得 0 分，比对继续）

### 回归比对 - 集成测试

- [ ] 从执行一键设置基线 → 正确提取并保存到 scenario
- [ ] 手动编辑基线保存 → 正确保存
- [ ] `compare_enabled = false` → 执行完成不触发比对
- [ ] `enable_llm_verification = false` → 跳过 LLM，只用算法相似度
- [ ] 执行完成自动触发比对，结果写入 comparison_results
- [ ] 比对整体出错 → execution 保持 COMPLETED，comparison 标记 failed
- [ ] 阈值配置正确，overall_passed 判断正确
- [ ] 超长 JSON 正确截断，不报错

### 链路回放 - 单元测试

- [ ] tool span 字段填充正确（replay 字段全为 NULL）
- [ ] llm span 每步比对立即写入 comparison_* 字段
- [ ] aggregated_metrics 计算正确（仅基于 llm spans）
- [ ] llm_trace_score = avg(comparison_score) * 100 计算正确
- [ ] 无 scenario_id 时 llm_baseline_score 为 NULL，overall_passed 只基于 llm_trace_score

### 链路回放 - 集成测试

- [ ] 启动重放 → ClickHouse 拉取全量 spans（llm + tool）
- [ ] 每步 LLM 重放使用 original_input（不依赖前一步输出）
- [ ] 每步重放完成后 comparison_* 字段立即写入，前端进度实时更新
- [ ] tool span 跳过处理，original 数据正确保存
- [ ] 有 scenario_id 时触发 baseline 比对，llm_baseline_score 正确写入
- [ ] 重新比对创建新 ReplayComparisonResult 记录，保留历史
- [ ] 前端完整链路卡片中 LLM + tool span 按 order 交替展示

### 手动验收

- [ ] 执行详情页比对详情卡片展示正确（分数、通过状态、每项详情展开）
- [ ] "设为基线"确认后场景基线字段正确更新
- [ ] 场景编辑页基线 JSON 可编辑、可清空
- [ ] 重放详情页进度条实时更新
- [ ] 重放详情页完整链路展示正确（LLM 左右对比栏 + tool 灰色展示）
- [ ] 比对结论卡片在 comparison_status=completed 后正确显示
- [ ] 轮询超时提示用户手动刷新
