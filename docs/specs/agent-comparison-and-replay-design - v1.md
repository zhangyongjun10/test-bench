# Agent 回放功能设计


## 1. 链路回放（Trace Replay）

### 1.1 业务目标

对已完成的执行，用指定的新 LLM 模型逐步重新执行每一个 LLM span，验证：
1. **每步稳定性**：给定相同输入，新模型与原模型的输出是否语义一致（`llm_trace_score`）
2. **最终正确性**：新模型的最终输出是否仍满足业务预期（`llm_baseline_score`，可选）

**核心约束**：
- 每步 LLM 输入固定使用原始 trace 的 `original_input`，不受前一步重放输出影响，保证比对条件一致可控
- 工具调用跳过，使用原始输出，只存储用于前端链路展示
- 不做 process_score（tool 次数/顺序）比对——输入固定则 tool 次数由原始 trace 决定，无比对意义


### 1.2 执行流程

```
用户提交重放请求 (原始执行ID + LLM模型ID)
    │
    ▼
从 ClickHouse 拉取原始 trace 全量 spans
    │
    ▼
拉取失败? ──是──→ 标记任务 failed 结束
    │ 否
    ▼
LLM span 数量 > 上限(100)? ──是──→ 标记任务 failed 结束
    │ 否
    ▼
创建 replay_tasks 记录 (status=queued)
预生成所有 spans 到 replay_spans (tool 只存原始数据)
    │
    ▼
后台启动 → status=running
    │
    ┌─────────────────────────────────────────────────────┐
    │  逐一遍历每个 LLM span (按原始顺序)                  │
    │        │                                           │
    │        ▼                                           │
    │   使用原始 input 调用新 LLM 模型                     │
    │        │                                           │
    │        ▼                                           │
    │   记录重放输出 + 性能指标(ttft/tokens)           
    │        │                                           │
    │        ▼                                           │
    │   立即比对：重放输出 vs 原始输出 → 两阶段评分          │
    │        │                                           │
    │        ▼                                           │
    │   写入 replay_spans (comparison_score/consistent)    │
    │        │                                           │
    │        ▼                                           │
    │   completed_llm_spans += 1                          │
    │        │                                           │
    │   ┌─────────────────────────────────────────────┐  │
    │   │ 还有 LLM span? ──是──→ 回到循环开始继续下一个  │  │
    │   └─────────────────────────────────────────────┘  │
    └─────────────────────────────────────────────────────┘
              │ 全部完成
              ▼
计算 aggregated_metrics (原始 vs 重放 性能对比)
llm_trace_score = avg(所有 span 分数) × 100
    │
    ▼
有 scenario_id + baseline_result? ──否──→ llm_baseline_score = NULL
    │ 是
    ▼
取最后一个重放输出 vs baseline → 两阶段比对 → llm_baseline_score
    │
    ▼
汇总判定 overall_passed (两个分数均达标则通过)
    │
    ▼
创建 replay_comparison_results 记录 → 写入全部比对详情
标记 replay_task → status=completed
    │
    ▼
结束
```

**流程说明：**
1. 用户从原始执行页面启动重放，选择目标 LLM 模型
2. 从 ClickHouse 拉取原始 trace，提前校验失败则立即返回
3. 预先生成所有 `replay_spans` 记录，tool span 只存原始数据用于展示
4. **逐一遍历**每个 LLM span：用原始输入调用新模型 → 输出立即比对 → 更新进度
5. 全部完成后计算聚合指标和总分，如有场景基线则额外比对最终输出
6. 写入 `replay_comparison_results` 完成任务

**关键特性：**
- 单步失败不终止：单个 LLM span 调用失败得 0 分，继续执行后续步骤
- 进度实时更新：前端轮询可看到 `completed_llm_spans / total_llm_spans`
- 输入固定：每步都使用原始 `original_input`，不依赖前一步重放输出，保证比对条件一致

**疑问难点：**
- LLM-as-Judge根据语义来判断比对输出是否一致，用temperature=0，减少输出随机性

### 1.3 数据库设计

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

**计算方式：**
仅统计 **LLM spans**，tool spans 不参与计算：

| 指标 | 计算方法 |
|------|---------|
| `original_total_input_tokens` | 原始所有 LLM span 的 `input_tokens` 求和 |
| `original_total_output_tokens` | 原始所有 LLM span 的 `output_tokens` 求和 |
| `original_avg_ttft_ms` | 原始所有 LLM span 的 `ttft_ms` 算术平均，有值才计算，全为空则为 `null` |
| `original_avg_tpot_ms` | 原始所有 LLM span 的 `tpot_ms` 算术平均，有值才计算，全为空则为 `null` |
| `replay_total_input_tokens` | 重放所有 LLM span 的 `input_tokens` 求和 |
| `replay_total_output_tokens` | 重放所有 LLM span 的 `output_tokens` 求和 |
| `replay_avg_ttft_ms` | 重放所有 LLM span 的 `ttft_ms` 算术平均 |
| `replay_avg_tpot_ms` | 重放所有 LLM span 的 `tpot_ms` 算术平均 |

**术语说明：**
- **TTFT (Time To First Token)**：首包延迟，从发送请求到收到第一个 token 的时间，单位毫秒
- **TPOT (Tokens Per Output Time)**：输出每个 token 的平均间隔时间 = (总输出时间 - TTFT) / (输出 tokens 数 - 1)，单位毫秒，值越小吞吐越高

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





### 1.4 API

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

### 1.5 前端（ReplayDetail.tsx）

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

### 1.6 设计决策

| 决策点 | 结论 | 原因 |
|--------|------|------|
| 工具调用是否重新执行 | 否 | Agent 工具为黑盒；重执行的级联效应让比对意义不清晰 |
| 每步 LLM 输入是否依赖前一步重放输出 | 否，固定用 original_input | 避免误差级联传播，保证每步比对输入条件一致 |
| tool span 是否存入 replay_spans | 是，只存 original | 前端展示完整 llm+tool 交替链路 |
| process_score（tool 次数/顺序） | 不做 | 输入固定时 tool 次数由原始 trace 决定，无比对意义 |
| 每步比对时机 | 每个 LLM span 重放完立即比对 | 进度更实时，单步失败不阻塞整体 |
| 比对结果存储 | 独立 replay_comparison_results 表 | 支持重新比对历史，与 replay_spans 逐步记录解耦 |
| 单个 LLM span 失败 | 该 span 得 0 分，记录错误，继续执行后续 | 不因为单步失败终止整个重放任务，保证能拿到部分结果用于分析 |
| 拉取原始 trace 失败 | 立即标记任务失败，不进入队列 | 尽早失败，避免资源浪费 |
| 超长 trace 保护 | LLM span 数量超过上限（建议 100）拒绝启动 | 防止单次重放耗时过长占满资源 |
| 整体超时控制 | 单次重放任务超时（建议 30 分钟）自动终止 | 避免僵尸任务占用资源 |

### 2 完整端到端重放模式（Full Agent Replay）

#### 2.1 业务目标

对已有的执行场景，**使用相同的初始用户prompt，重新完整启动一次Agent执行**，真实调用所有LLM和工具，验证：
1. **路径稳定性**：最终执行路径（tool调用序列）是否和原始/基线一致
2. **结果正确性**：最终输出是否和原始/基线一致

**适用场景**：
- 架构重构后全链路回归验证
- Agent提示词工程修改后验证整体行为
- 依赖库版本升级后验证功能正确性

#### 2.2 执行流程

```
用户启动完整端到端重放 → 指定LLM模型 + 比对基准
    │
    ▼
从原始执行/scenario获取启动参数：user_prompt + system_prompt + tools配置
    │
    ▼
创建 replay_task → replay_mode = full_agent，status = queued
    │
    ▼
后台提交完整新Agent执行任务 → 关联到 replay_task.full_execution_id
    │
    ▼
等待Agent执行完成（真实调用所有LLM + 工具）
    │
    ▼
从ClickHouse拉取新执行的完整trace（所有tool + LLM spans）
    │
    ▼
比对：
	1. tool和llm的span调用次数比对，差异过大标记异常
    2. 过程比对：新trace spans vs 基准（原始或基线）
    3. 结果比对：最终LLM输出 vs 基准最终输出
    │
    ▼
计算过程分 + 结果分 → 判定 overall_passed
    │
    ▼
计算 aggregated_metrics（原始 vs 完整重放 性能对比）
    │
    ▼
创建 replay_comparison_results → 写入比对详情
标记 replay_task → status = completed
    │
    ▼
结束
```

**比对基准选择：**
- 如果从**原始执行页面**启动 → 基准 = 原始执行的trace
- 如果从**场景页面**启动 → 基准 = 场景基线 `baseline_tool_calls` + `baseline_result`

#### 2.3 比对算法（完全复用回归比对）

| 步骤 | 算法 |
|------|------|
| **配对** | 贪心最优匹配：每个实际span找最相似的未匹配基准span，名称不同直接跳过 |
| **打分** | 每对匹配走两阶段策略（JSON预处理 → Levenshtein粗筛 → 低分触发LLM语义验证） |
| **计分** | process_score = 所有配对平均分 × 100，未配对得0分 |
| **结果** | 最后一个LLM输出单独比对得 result_score |

**应对路径不一致：**
- 多调用/少调用 → 未配对得0分，拉低平均分 → 不通过，符合预期
- 顺序不同但内容都匹配 → 能正常配对，不影响得分 → 通过
- 完全分叉 → 大量0分 → 低分不通过

#### 2.4 设计决策

| 决策点 | 结论 | 原因 |
|--------|------|------|
| 执行方式 | 完整重新运行Agent，真实调用所有工具 | 端到端验证就是要验证全链路能否正确执行 |
| 配对算法 | 复用回归比对的贪心最优匹配 | 已经解决了路径不一致问题，无需重新实现 |
| 新执行独立存储 | 重放任务关联新的 `full_execution_id` | 保留完整执行trace，便于事后排查问题 |
| 两种模式并存 | step_fixed_input 和 full_agent 都支持，用户选择 | 不同场景需求不同：纯模型比对用fixed，全链路验证用full |

---

#### 2.5 数据库设计修改

**`replay_tasks` 表新增字段：**

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `replay_mode` | String | 否 | `step_fixed_input`（逐step固定输入，默认）/ `full_agent`（完整端到端） |
| `full_execution_id` | UUID | 是 | 完整重放产生的新执行job ID，FK → `execution_jobs.id` |


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
| 修改 | `frontend/src/pages/ExecutionDetail.tsx` | 新增"启动重放"按钮 + 模态框，支持选择重放模式 |

### 完整端到端重放

| 操作 | 文件路径 | 说明 |
|------|---------|------|
| 修改 | `backend/app/domain/entities/replay.py` | 新增 `replay_mode`、`full_execution_id` 字段 |
| 修改 | `backend/app/models/replay.py` | Pydantic schema 新增字段 |
| 修改 | `backend/app/services/replay_service.py` | 增加 full_agent 模式执行分支 |
| 修改 | `backend/app/api/replay.py` | 启动接口支持 replay_mode 参数 |
| 修改 | `frontend/src/pages/ReplayDetail.tsx` | 展示完整重放的执行信息，支持跳转新执行 |

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
- [ ] 单个 LLM span 调用失败 → 该 span 得 0 分，记录错误，继续执行后续 spans，不终止整个任务

### 链路回放 - 集成测试

- [ ] 启动重放 → ClickHouse 拉取全量 spans（llm + tool）
- [ ] ClickHouse 拉取失败 → 立即标记任务失败，不进入队列
- [ ] LLM span 数量超过限制 → 启动时拒绝，提示用户
- [ ] 整体超时 → 自动终止任务，标记失败
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
- [ ] 删除重放任务功能可用

### 完整端到端重放 - 集成测试

- [ ] 从原始执行页面启动完整重放 → 正确创建新执行，比对基准为原始trace
- [ ] 从场景页面启动完整重放 → 比对基准为场景基线
- [ ] 路径不一致时 → 贪心配对正确，未配对得0分，总分正确计算
- [ ] 多个同名工具 → 能正确匹配相似度最高的配对
- [ ] `full_execution_id` 关联正确，可跳转到新执行详情页

## 8. 后续迭代计划（不包含在 MVP 实现中）

### 8.1 资源控制
- **单用户并发限制**：限制单个用户同时运行的重放任务数量（建议 2-3 个），防止资源耗尽
- **自动数据清理**：支持配置自动清理超过 N 天的已完成/失败重放任务，节省存储空间

### 8.2 功能增强
- **批量比对**：支持对一个场景下的多个最近执行批量触发回归比对
- **忽略字段配置**：支持配置 JSONPath 忽略 tool 输入中的可变字段（如时间戳、UUID），减少误报
- **比对结果导出**：支持导出比对详情为 JSON/CSV，方便分析分享
- **忽略随机内容模式匹配**：自动识别常见的随机格式（UUID、时间戳）并忽略差异

### 8.3 可观测性
- 添加业务 metrics：比对成功率、平均比对耗时、重放任务成功率、重放平均耗时
- 慢任务日志：超过 5 分钟的比对/重放记录警告日志

### 8.4 UX 改进
- 支持一键复制比对结果
- 分数接近阈值时给出"临界"提示
