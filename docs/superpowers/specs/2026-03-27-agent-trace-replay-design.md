# Agent Trace 链路重放功能设计

## 需求概述

基于已保存的 Opik/Langfuse Agent 调用链路（Trace），重新执行每一步 LLM 调用，对比原始执行和重放执行的输出差异和性能指标变化。

**核心规则：**
- 只重放 LLM 调用
- 工具调用跳过，直接使用原始 trace 保存的输出
- 对比输出内容、TTFT、TPOT、token 数量等指标

## 用例

1. 用户在原始执行详情页点击"启动重放"
2. 选择用于重放的 LLM 模型
3. 系统异步遍历原始 trace 中所有 LLM span，按顺序重放
4. 保存每个步骤的重放结果和指标
5. 在对比页面展示原始 vs 重放的差异

## 架构设计

遵循项目现有四层架构：API 路由层 → 业务逻辑层 → 领域层 → 外部客户端。

### 目录结构

```
backend/app/
├── api/
│   └── replay.py                 # 新增：回放接口
├── services/
│   └── replay_service.py         # 新增：回放业务逻辑
├── domain/
│   ├── entities/
│   │   └── replay.py             # 新增：ReplayTask, ReplaySpan 实体
│   └── repositories/
│       └── replay_repo.py        # 新增：数据访问层
└── migrations/versions/
    └── XXX_add_replay_tables.py  # 新增：数据库迁移

frontend/src/
├── pages/
│   └── ReplayDetail.tsx          # 新增：重放详情对比页
└── api/
    ├── client.ts                 # 修改：添加 replay API 方法
    └── types.ts                  # 修改：添加 replay 类型定义
```

## 数据模型设计

### ReplayTask（重放任务）

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| id | UUID | 否 | 主键 |
| original_execution_id | UUID | 否 | 关联原始执行 |
| llm_model_id | UUID | 否 | 用于重放的 LLM 模型 |
| status | Enum | 否 | 状态：queued/running/completed/failed |
| total_llm_spans | int | 否 | 总共需要重放的 LLM span 数量 |
| completed_llm_spans | int | 否 | 已完成重放的数量 |
| aggregated_metrics | JSON | 是 | 聚合对比指标 |
| error_message | String | 是 | 错误信息 |
| created_at | DateTime | 否 | 创建时间 |
| started_at | DateTime | 是 | 开始时间 |
| completed_at | DateTime | 是 | 完成时间 |

### ReplaySpan（单个重放步骤结果）

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| id | UUID | 否 | 主键 |
| replay_task_id | UUID | 否 | 关联重放任务 |
| original_span_id | String | 否 | 原始 span ID |
| span_name | String | 否 | span 名称 |
| order | int | 否 | 执行顺序 |
| original_input | Text | 是 | 原始输入 |
| original_output | Text | 是 | 原始输出 |
| original_metrics | JSON | 是 | 原始指标 (ttft_ms, tpot_ms, input_tokens, output_tokens) |
| replay_output | Text | 是 | 重放输出 |
| replay_metrics | JSON | 是 | 重放指标 |
| created_at | DateTime | 否 | 创建时间 |
| completed_at | DateTime | 是 | 完成时间 |

### 聚合指标结构

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

## API 接口设计

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v1/replay/start` | 启动重放任务 |
| GET | `/api/v1/replay/{id}` | 获取重放任务摘要 |
| GET | `/api/v1/replay/{id}/detail` | 获取重放任务详情（含所有 spans）|
| DELETE | `/api/v1/replay/{id}` | 删除重放任务 |

### POST `/api/v1/replay/start` 请求体

```json
{
  "original_execution_id": "uuid",
  "llm_model_id": "uuid"
}
```

响应：

```json
{
  "success": true,
  "data": {
    "replay_id": "uuid"
  }
}
```

## 执行流程

```
用户在执行详情页点击"启动重放"
  ↓
选择 LLM 模型 → 确认启动
  ↓
POST /api/v1/replay/start
  ↓
replay_service.start_replay
  ↓
  1. 获取原始 execution
  2. 从原始 execution 获取 spans（从 ClickHouse 拉取）
  3. 过滤出所有 span_type = 'llm' 的 spans
  4. 创建 ReplayTask，状态 = QUEUED
  5. 为每个 llm span 创建 ReplaySpan
  6. 后台任务触发 run_replay
  ↓
返回 replay_id 给前端，前端跳转到重放详情页
  ↓
run_replay 异步执行
  ↓
  更新状态 = RUNNING
  ↓
  按 order 顺序逐个处理 ReplaySpan:
    - 从原始 span 获取 input
    - 使用配置的 LLM 模型重新调用
    - 记录 replay_output 和 replay_metrics (ttft, tokens, 延迟)
    - 增加 completed_llm_spans 计数
    - 更新进度
  ↓
  全部完成后，计算 AggregatedMetrics
  ↓
  更新状态 = COMPLETED
  ↓
前端轮询 /api/v1/replay/{id} 获取状态
  ↓
完成后，加载详情并展示对比
```

## 前端设计

### 页面结构（ReplayDetail.tsx）

1. **头部信息卡片** - 重放任务状态、进度、关联原始执行、使用的 LLM
2. **聚合指标对比卡片** - 表格对比：
   | 指标 | 原始 | 重放 | 差异 |
   |------|------|------|------|
   | 总输入 Tokens | xxx | xxx | ±x |
   | 总输出 Tokens | xxx | xxx | ±x |
   | 平均 TTFT (ms) | xxx | xxx | ±x |
   | 平均 TPOT (ms) | xxx | xxx | ±x |

3. **分步对比** - 每个 LLM span 一个折叠面板：
   - 标题：span 名称 + 原始 vs 重放 tokens + 耗时
   - 分两栏：
     - 左栏：**原始** - 输入 → 输出 → 指标
     - 右栏：**重放** - 输入（相同）→ 重放输出 → 重放指标

### 入口修改

- 在 `ExecutionDetail.tsx` （原始执行详情）添加"启动重放"按钮
- 点击按钮弹出模态框，选择用于重放的 LLM 模型
- 确认后跳转到 `replay/{id}` 页面

## 数据库迁移

- 新建迁移脚本创建两张表：`replay_tasks` 和 `replay_spans`
- 外键关联：
  - `replay_tasks.original_execution_id` → `execution_jobs.id`
  - `replay_tasks.llm_model_id` → `llm_models.id`
  - `replay_spans.replay_task_id` → `replay_tasks.id`

## 遵循现有设计模式

- 复用现有的 `llm_client.py` 进行 LLM 调用
- 复用现有的指标收集方式
- 复用 FastAPI BackgroundTasks 进行异步执行
- 复用现有的仓储模式
- 前端遵循现有的 Ant Design 风格

## 范围边界

**本次实现包含：**
- 后端数据模型、API、业务逻辑
- 数据库迁移
- 前端重放详情对比页
- 从原始执行详情页启动重放入口

**本次实现不包含：**
- 工具调用重放（需求明确要求跳过）
- 输出内容差异自动比对（可以后续扩展，当前只做展示）
- 多轮次对比（只对比一次原始 vs 一次重放）
