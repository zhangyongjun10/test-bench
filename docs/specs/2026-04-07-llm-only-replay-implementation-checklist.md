# LLM-Only Replay Refactor Implementation Checklist

**版本**: 1.0  
**日期**: 2026-04-07  
**对应方案**: [2026-04-07-llm-only-replay-refactor-plan.md](E:/项目/model/test-bench/docs/specs/2026-04-07-llm-only-replay-refactor-plan.md)

---

## 1. 范围确认

- [ ] 确认本期主目标为 `Full Agent Replay`
- [ ] 确认本期不建设 `tool` 比对新能力
- [ ] 确认 replay 的执行起点固定为 `original_execution_id`
- [ ] 确认 replay 的比较基准由 `baseline_source` 显式选择
- [ ] 确认 `baseline_source` 只支持：
  - [ ] `scenario_baseline`
  - [ ] `reference_execution`

---

## 2. 数据库 Migration

### 2.1 `scenarios` 表

- [ ] 新增 `baseline_llm_calls` 字段
- [ ] 保留 `baseline_result`，明确语义为最终 LLM 基线输出
- [ ] 新增 `baseline_trace_id` 字段
- [ ] 新增 `baseline_updated_at` 字段
- [ ] 新增 `llm_count_tolerance` 字段
- [ ] 保留或确认 `compare_enabled` 是否继续复用

### 2.2 `execution_jobs` 表

- [ ] 新增 `request_snapshot_json` 字段
- [ ] 新增 `run_source` 字段
- [ ] 新增 `parent_execution_id` 字段

### 2.3 新表 `replay_tasks`

- [ ] 新建 `replay_tasks`
- [ ] 创建主键
- [ ] 创建 `original_execution_id` 外键
- [ ] 创建 `scenario_id` 外键
- [ ] 创建 `new_execution_id` 外键
- [ ] 新增 `baseline_source` 字段
- [ ] 新增 `llm_model_id` 字段
- [ ] 新增 `status` 字段
- [ ] 新增 `comparison_status` 字段
- [ ] 新增 `overall_passed` 字段
- [ ] 新增 `error_message` 字段
- [ ] 新增时间字段
- [ ] 为 `original_execution_id` 建索引
- [ ] 为 `new_execution_id` 建索引

### 2.4 新表 `replay_comparison_results`

- [ ] 新建 `replay_comparison_results`
- [ ] 创建主键
- [ ] 创建 `replay_task_id` 外键
- [ ] 新增 `process_passed_count`
- [ ] 新增 `process_total_count`
- [ ] 新增 `result_passed`
- [ ] 新增 `overall_passed`
- [ ] 新增 `details_json`
- [ ] 新增 `aggregated_metrics_json`
- [ ] 新增 `status`
- [ ] 新增 `error_message`
- [ ] 新增时间字段
- [ ] 为 `replay_task_id` 建索引

### 2.5 旧字段清理准备

- [ ] 标记以下字段为废弃但暂不删除：
  - [ ] `baseline_tool_calls`
  - [ ] `process_threshold`
  - [ ] `result_threshold`
  - [ ] `tool_count_tolerance`
  - [ ] `compare_process`
  - [ ] `compare_result`
  - [ ] `enable_llm_verification`

---

## 3. 后端实体与模型

### 3.1 枚举定义

- [ ] 新增 `ReplayBaselineSource` 枚举
- [ ] 新增 `ReplayTaskStatus` 枚举
- [ ] 新增 `ReplayComparisonStatus` 枚举
- [ ] 如需要，新增 `ExecutionRunSource` 枚举

### 3.2 领域实体

- [ ] 更新 `Scenario` 实体，增加 `baseline_llm_calls`
- [ ] 更新 `Scenario` 实体，增加 `llm_count_tolerance`
- [ ] 更新 `ExecutionJob` 实体，增加 replay 相关字段
- [ ] 新增 `ReplayTask` 实体
- [ ] 新增 `ReplayComparisonResult` 实体

### 3.3 Pydantic 模型

- [ ] 新增 `CreateReplayRequest`
- [ ] 新增 `ReplayTaskResponse`
- [ ] 新增 `ReplayComparisonResponse`
- [ ] 新增 `ExecutionReplaySummaryResponse`
- [ ] 新增 `ReplayListResponse`，如果本期需要列表页
- [ ] 给 `baseline_source` 使用枚举约束

---

## 4. 仓储层

### 4.1 Replay 仓储

- [ ] 新增 `replay_repo.py`
- [ ] 定义 `ReplayTaskRepository`
- [ ] 定义 `ReplayComparisonRepository`
- [ ] 实现 SQLAlchemy 版本

### 4.2 Execution 仓储补充

- [ ] 支持按 `parent_execution_id` 查询
- [ ] 支持回放生成的新 execution 关联查询

---

## 5. 场景基线能力改造

### 5.1 设置基线

- [ ] 改造 `set-baseline` 逻辑，只提取 LLM spans
- [ ] 从 trace 中提取全部 LLM spans 生成 `baseline_llm_calls`
- [ ] 提取最后一个 LLM span 生成 `baseline_result`
- [ ] 将来源 execution 的 `trace_id` 写入 `baseline_trace_id`
- [ ] 将本次覆盖时间写入 `baseline_updated_at`
- [ ] 不再提取 `tool_calls`

### 5.2 场景增改查

- [ ] 创建场景时支持 `baseline_llm_calls`
- [ ] 创建场景时支持 `llm_count_tolerance`
- [ ] 更新场景时支持 `baseline_llm_calls`
- [ ] 更新场景时支持 `llm_count_tolerance`
- [ ] 前后端统一停止依赖 `baseline_tool_calls`

---

## 6. Replay 服务主链

### 6.1 创建 Replay 任务

- [ ] 新建 `ReplayService`
- [ ] 实现 `create_replay_task`
- [ ] 校验 `original_execution_id` 存在
- [ ] 校验 `baseline_source` 合法
- [ ] 若 `baseline_source = scenario_baseline`，校验场景存在基线
- [ ] 创建 `replay_task(status=queued)`

### 6.2 发起真实执行

- [ ] 基于 `original_execution_id` 创建新的 execution
- [ ] 给新 execution 写入 `run_source=replay`
- [ ] 给新 execution 写入 `parent_execution_id`
- [ ] 如有需要，写入 `request_snapshot_json`
- [ ] 后台触发真实 Agent 执行

### 6.3 等待执行完成

- [ ] 轮询或等待新 execution 状态完成
- [ ] 区分 `completed` / `completed_with_mismatch` / `failed`
- [ ] execution 失败时将 replay 标记为 `failed`

### 6.4 拉取对比数据

- [ ] 拉取 replay 生成的新 execution trace
- [ ] 当 `baseline_source = reference_execution` 时拉取原 execution trace
- [ ] 当 `baseline_source = scenario_baseline` 时读取场景基线数据

---

## 7. LLM-Only Comparison 服务

### 7.1 新 comparison 主线

- [ ] 新建或重构 comparison 服务为 LLM-only
- [ ] 停止新的 replay 主线读取 `tool spans`
- [ ] 保留 `tool spans` 仅用于页面链路展示

### 7.2 基准提取器

- [ ] 实现 `scenario_baseline` 基准提取器
- [ ] 实现 `reference_execution` 基准提取器
- [ ] 统一输出为：
  - [ ] `baseline_llm_calls`
  - [ ] `baseline_result`

### 7.3 LLM span 提取

- [ ] 从 trace 中筛选 `span_type = llm`
- [ ] 按时间排序
- [ ] 提取 `name / input / output`
- [ ] 提取最后一个 LLM span 作为结果输出

### 7.4 过程比对

- [ ] 实现 LLM count tolerance 校验
- [ ] 实现 LLM span 匹配逻辑
- [ ] 实现高相似度直通
- [ ] 实现低相似度 LLM 语义校验
- [ ] 记录每个 LLM span 的比较详情

### 7.5 结果比对

- [ ] 比较最后一个 LLM span 输出
- [ ] 返回 `result_passed`
- [ ] 写入原因说明

### 7.6 总体判定

- [ ] count 超容忍度 -> fail
- [ ] final result fail -> fail
- [ ] 否则 overall pass

---

## 8. 聚合指标对比

- [ ] 复用 trace 中的 token/TTFT/TPOT 数据
- [ ] 统计原始侧总 input tokens
- [ ] 统计原始侧总 output tokens
- [ ] 统计原始侧平均 TTFT
- [ ] 统计原始侧平均 TPOT
- [ ] 统计 replay 侧总 input tokens
- [ ] 统计 replay 侧总 output tokens
- [ ] 统计 replay 侧平均 TTFT
- [ ] 统计 replay 侧平均 TPOT
- [ ] 写入 `aggregated_metrics_json`

---

## 9. API 清单

### 9.1 新增接口

- [ ] `POST /api/v1/replay`
- [ ] `GET /api/v1/replay/{id}`
- [ ] `GET /api/v1/replay/{id}/comparison`
- [ ] `POST /api/v1/replay/{id}/recompare`
- [ ] `GET /api/v1/execution/{id}/replays`

### 9.1.1 `GET /api/v1/execution/{id}/replays` 返回字段

- [ ] `id`
- [ ] `original_execution_id`
- [ ] `new_execution_id`
- [ ] `baseline_source`
- [ ] `status`
- [ ] `comparison_status`
- [ ] `overall_passed`
- [ ] `llm_model_id`
- [ ] `llm_model_name`
- [ ] `created_at`
- [ ] `started_at`
- [ ] `completed_at`
- [ ] `error_message`

### 9.1.2 `GET /api/v1/replay/{id}` 详情字段补充

- [ ] `task` 基本信息
- [ ] `original_execution` 基本信息
- [ ] `new_execution` 基本信息
- [ ] `summary`
- [ ] `aggregated_metrics`
- [ ] `llm_comparisons`
- [ ] `result_comparison`
- [ ] `original_trace.trace_id`
- [ ] `original_trace.spans`
- [ ] `replay_trace.trace_id`
- [ ] `replay_trace.spans`

### 9.2 接口校验

- [ ] `baseline_source` 必填
- [ ] `llm_model_id` 可选
- [ ] `scenario_baseline` 模式下无基线时返回明确错误
- [ ] `reference_execution` 模式下原 execution 无 trace 时返回明确错误

### 9.3 保留接口

- [ ] 保留 `GET /api/v1/execution/{id}`
- [ ] 保留 `GET /api/v1/execution/{id}/trace`
- [ ] 保留 `POST /api/v1/scenario/{id}/set-baseline/{execution_id}`

### 9.4 废弃接口

- [ ] 标记 `GET /api/v1/execution/{id}/comparison` 为废弃
- [ ] 标记 `POST /api/v1/execution/{id}/recompare` 为废弃

---

## 10. 前端类型与 API Client

### 10.1 类型

- [ ] 新增 `ReplayBaselineSource` union type
- [ ] 新增 `CreateReplayRequest`
- [ ] 新增 `ReplayTask`
- [ ] 新增 `ReplayComparisonResult`
- [ ] 新增 `ExecutionReplaySummary`
- [ ] 新增 `ReplayDetailResponse`
- [ ] 新增 `ReplayTrace`
- [ ] 新增 `ReplayTraceSpan`
- [ ] 新增聚合指标类型

### 10.2 文案映射

- [ ] 新增 `baseline_source` 到中文标签的映射
- [ ] 使用“跟当前执行比较”作为 `reference_execution` 展示文案

### 10.3 API Client

- [ ] 新增 `replayApi.create`
- [ ] 新增 `replayApi.get`
- [ ] 新增 `replayApi.getComparison`
- [ ] 新增 `replayApi.recompare`

---

## 11. 前端页面改造

### 11.1 ExecutionList

- [ ] 在测试执行列表每条记录的“操作”列新增“回放”或“启动回放”入口
- [ ] 增加启动回放弹窗
- [ ] 弹窗中加入 LLM 模型选择
- [ ] 弹窗中加入比较基准选择
- [ ] 比较基准设为必选
- [ ] `scenario_baseline` 模式下无基线时禁用提交或给出提示
- [ ] 不允许自动兜底切换比较基准
- [ ] 如有状态限制，在操作列禁用按钮并展示原因
- [ ] 启动成功后跳转 ReplayDetail 或保留列表页并提示

### 11.2 ExecutionDetail

- [ ] 保留原有“重新比对”入口
- [ ] 保留“设为基线”入口
- [ ] 新增“查看回放详情”入口
- [ ] 点击后可展开回放记录列表，或打开抽屉/折叠区
- [ ] 支持查询当前 execution 关联的多次 replay 记录
- [ ] 每条 replay 记录展示状态、比较基准、创建时间、结果摘要、模型名
- [ ] 每条 replay 记录支持跳转到 ReplayDetail
- [ ] 每条 replay 记录支持跳转到 replay 生成的新 execution
- [ ] 当前阶段不要求在详情页新增“启动回放”入口

### 11.3 ReplayDetail 页面

- [ ] 新建页面
- [ ] 展示 replay task 基本信息
- [ ] 展示原 execution 与新 execution
- [ ] 展示 baseline source
- [ ] 展示 comparison status
- [ ] 展示 overall pass/fail
- [ ] 展示聚合指标对比
- [ ] 展示过程对比明细
- [ ] 展示最终结果对比明细
- [ ] 支持跳转到新 execution 详情
- [ ] 展示原始执行全链路
- [ ] 展示回放执行全链路
- [ ] 全链路中按时间顺序展示 `llm + tool` spans
- [ ] `tool spans` 仅展示不参与打分

### 11.4 路由

- [ ] 新增 replay 详情路由
- [ ] 如需要，新增 replay 列表路由

---

## 12. 旧逻辑隔离与清理

### 12.1 先隔离

- [ ] 新 replay 主线不再依赖 `baseline_tool_calls`
- [ ] 新 replay 主线不再依赖 `process_threshold/result_threshold`
- [ ] 新 replay 主线不再依赖 `tool_count_tolerance`
- [ ] 新 replay 主线不再依赖 `enable_llm_verification` 开关语义

### 12.2 后清理

- [ ] 删除旧 tool comparison 服务逻辑
- [ ] 删除旧 tool comparison UI
- [ ] 删除旧 comparison API
- [ ] 删除旧字段 migration

---

## 13. 测试清单

### 13.1 单元测试

- [ ] `baseline_source` 枚举校验
- [ ] `scenario_baseline` 基准提取
- [ ] `reference_execution` 基准提取
- [ ] LLM span 提取
- [ ] LLM count tolerance 判断
- [ ] LLM 匹配算法
- [ ] 最终结果比较
- [ ] overall 判定逻辑
- [ ] 聚合指标计算

### 13.2 集成测试

- [ ] 创建 replay task 成功
- [ ] `scenario_baseline` 模式回放成功
- [ ] `reference_execution` 模式回放成功
- [ ] 无场景基线时报错正确
- [ ] 原 execution trace 拉取失败时报错正确
- [ ] replay 生成的新 execution 关联正确
- [ ] replay comparison 结果落库正确

### 13.3 前端联调

- [ ] 启动回放弹窗展示正确
- [ ] 比较基准必选校验正确
- [ ] ReplayDetail 页面展示正确
- [ ] 跳转链路正确
- [ ] 异常提示文案清晰

---

## 14. 建议实施顺序

### Phase 1: 基线链路先收口

- [ ] 完成 migration
- [ ] 给 `scenarios` 增加 `baseline_llm_calls`
- [ ] 给 `scenarios` 增加 `baseline_trace_id`
- [ ] 给 `scenarios` 增加 `baseline_updated_at`
- [ ] 改造 `set-baseline` 为 LLM-only
- [ ] 场景详情接口返回基线追踪字段
- [ ] 前端可展示当前基线来源 trace_id 和最后更新时间

### Phase 2: Replay 数据模型落地

- [ ] 完成 replay 相关 migration
- [ ] 完成实体 / 枚举 / Pydantic 模型
- [ ] 完成 replay repo

### Phase 3: Replay 主链打通

- [ ] 完成 replay service 主链
- [ ] 完成 LLM-only comparison
- [ ] 完成 `scenario_baseline` 与 `reference_execution` 两种基准提取

### Phase 4: API 与前端接入

- [ ] 完成 replay API
- [ ] 完成前端类型与 client
- [ ] 完成 ExecutionDetail 启动回放弹窗
- [ ] 完成 ReplayDetail 页面

### Phase 5: 测试与旧逻辑清理

- [ ] 补单元测试
- [ ] 补集成测试
- [ ] 清理旧 comparison 主线

---

## 15. 完成判定

以下条件全部满足，视为本次重构 MVP 完成：

- [ ] 用户可从 execution 详情页发起一次端到端回放
- [ ] 当前场景基线可反查 `baseline_trace_id`
- [ ] 当前场景基线可查看 `baseline_updated_at`
- [ ] 用户必须显式选择比较基准
- [ ] 系统支持 `scenario_baseline`
- [ ] 系统支持 `reference_execution`
- [ ] replay 会生成新的 execution
- [ ] replay 完成后能输出 LLM-only comparison 结果
- [ ] 前端可查看 replay 详情和结论
- [ ] 新主线不再依赖 tool comparison
