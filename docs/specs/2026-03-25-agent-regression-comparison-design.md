# 实现计划：Agent 回归测试过程结果自动化比对评估

**版本**: 1.1
**日期**: 2026-04-02
**更新内容**: 补充与 Trace 回放比对的功能边界说明

## Context

**问题背景**：当前 TestBench 平台已经支持 Agent 执行测试和简单的 LLM 输出比对，但缺少对**执行过程（tool 调用）** 的详细比对能力。需要实现完整的过程+结果双维度比对评估，用于 Agent 回归测试。

**业务目标**：
- Agent 开发人员修改代码后，运行回归测试自动验证：
  1. **过程一致性**：Tool 调用次数、输入输出是否和基线一致
  2. **结果一致性**：最终 LLM 输出是否和基线一致
- 给出详细的比对分数、原因，支持可视化展示

**与 Trace 回放比对的功能边界**：

| 对比维度 | 回归比对（本文档）| Trace 回放比对 |
|---------|-----------------|--------------|
| 触发时机 | Agent 场景执行完成后自动触发 | 用户手动启动重放任务后触发 |
| 比对基准 | `scenario.baseline_tool_calls` + `baseline_result`（人工设定） | 原始 trace 本身（每步 llm span 输出） |
| LLM 比对维度 | 只比最后一个 LLM 输出 vs baseline | 每步 LLM 输出逐步与原始比对 + 最终 vs baseline |
| 过程比对 | tool 调用次数/顺序/输入输出 vs baseline_tool_calls | 不做（replay 输入固定，无意义） |
| 核心问题 | "这次执行结果是否符合预期基线？" | "换一个 LLM 模型，每步行为和最终结果是否一致？" |

**澄清后的需求确认**：
- ✅ 触发方式：执行完成自动比对 + 支持手动重新比对
- ✅ 存储：新建独立表存储详细比对结果，与 execution_id 关联
- ✅ **基线来源**：支持两种方式：
  - 方式一：**从执行一键设置**：在执行详情页点击"设为基线"，自动从 trace 提取 tool_calls 和最后 LLM 输出
  - 方式二：**手动编辑**：在场景编辑页面直接编辑 JSON 基线，支持自定义微调
  - `baseline_tool_calls` 存过程，`baseline_result` 存结果
- ✅ 比对策略：先算法粗筛（编辑距离相似度），高相似度跳过 LLM 节省成本，低相似度用 LLM 验证
- ✅ 评分：`process_score` (0-100) + `result_score` (0-100) 分开展示
- ✅ 多轮处理：所有 tool 和 llm span 全部比对
- ✅ **阈值配置**：每个场景单独配置过程和结果阈值
- ✅ 前端展示：展开查看每个调用详情、展示总体结论、重新比对按钮
- ✅ **状态处理**：执行成功但比对不通过时，新增 `COMPLETED_WITH_MISMATCH` 状态
- ✅ **匹配策略**：不要求 tool 调用顺序，使用最优匹配（每个实际 tool 匹配最相似的基线 tool）
- ✅ **多个 LLM**：多轮对话只比对最后一个 LLM 输出
- ✅ **JSON 标准化**：JSON 格式输入输出自动解析并重格式化，消除格式差异对相似度的影响
- ✅ **空基线处理**：如果未设置过程基线，跳过过程比对只做结果比对；如果未设置结果基线，跳过结果比对只做过程比对
- ✅ 错误处理：LLM 调用失败自动重试 3 次，仍失败标记失败，允许手动重试

## 数据库设计

### 修改 `scenarios` 表（新增字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `baseline_tool_calls` | Text (JSON) | 过程基线：JSON 数组，每个元素 `{name, input, output}` |
| `baseline_result` | Text | 结果基线：最后一个 LLM 输出 |
| `process_threshold` | Double | 过程分数通过阈值，默认 60.0 |
| `result_threshold` | Double | 结果分数通过阈值，默认 60.0 |
| `tool_count_tolerance` | Integer | tool 调用次数允许浮动范围，默认 0（必须完全一致）。例如：基线 3 次，容忍 1 → 实际 2~4 次都通过第一步 |
| `compare_enabled` | Boolean | 是否启用自动比对，默认 `true`。false 表示执行完成后不触发比对 |
| `enable_llm_verification` | Boolean | 是否启用 LLM 语义验证，默认 `true`。false 表示只做算法粗筛，节省LLM成本 |

### 修改 `ExecutionStatus` 枚举

新增状态：
- `COMPLETED_WITH_MISMATCH = "completed_with_mismatch"` - 执行成功完成但比对不通过

### 新表：`comparison_results`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键，自动生成 |
| `execution_id` | UUID | 外键 → `execution_jobs.id`，索引 |
| `scenario_id` | UUID | 外键 → `scenarios.id`，索引（方便按场景查询比对历史）|
| `trace_id` | String | 关联的 trace ID |
| `process_score` | Double | 过程分数 0-100 |
| `result_score` | Double | 结果分数 0-100 |
| `overall_passed` | Boolean | 总体是否通过 |
| `details_json` | Text | 详细比对结果 JSON（包含每个 tool/llm 的比对详情）|
| `status` | String | 比对状态：pending/processing/completed/failed |
| `error_message` | Text | 错误信息（比对失败时）|
| `retry_count` | Integer | 已重试次数，默认 0 |
| `created_at` | DateTime(tz) | 创建时间 |
| `updated_at` | DateTime(tz) | 更新时间，自动更新 |
| `completed_at` | DateTime(tz) | 比对完成时间 |

**遵循现有项目约定**：
- UUID 主键
- 软删除不需要（删除重建即可，保留历史）
- `created_at`/`updated_at` 自动时间戳

> 注：比对阈值每个场景单独配置（存在 `scenarios` 表），不需要全局配置

## 实现步骤（按分层架构）

### 1. 领域实体层
**新建** `backend/app/domain/entities/comparison.py`
- 定义 `ComparisonStatus` 常量类
- 定义 `ComparisonResult` SQLAlchemy 实体

### 2. 仓储层
**新建** `backend/app/domain/repositories/comparison_repo.py`
- 抽象接口 `ComparisonRepository`（ABC）
- `SQLAlchemyComparisonRepository` 实现
- 核心方法：
  - `create()` - 创建比对记录
  - `get_by_execution_id()` - 获取最新比对结果
  - `update()` - 更新比对状态和结果

### 3. Pydantic 模型层
**修改** `backend/app/models/execution.py`
- 新增 `SingleToolComparison` - 单个 Tool 比对结果 schema
- 新增 `SingleLLMComparison` - 单个 LLM 比对结果 schema
- 新增 `DetailedComparisonResponse` - 完整比对详情响应

### 4. 服务层 - 核心比对逻辑
**修改扩展现有的** `backend/app/services/comparison.py`
- 新增 `ComparisonService.detailed_compare()` 方法实现完整比对：
  1. 从 trace 提取所有 `tool` span 和 `llm` span
  2. **过程比对**（如果 `baseline_tool_calls` 不为空）：
     - 第一步：比对 tool 次数与 `scenario.baseline_tool_calls` 中的基线次数
     - 计算次数差异：`abs(actual_count - baseline_count)`
     - 如果差异 > `scenario.tool_count_tolerance` → 全部 tool 得 0 分
     - 如果差异在容忍范围内 → **最优匹配不要求顺序**：
       - 计算每对 `(实际 tool, 基线 tool)` 的相似度
       - 使用贪心算法找到总相似度最大的匹配（每个实际最多配一个基线，每个基线最多配一个实际）
       - 未匹配到的 tool 得 0 分
     - **对每个匹配对，使用两阶段策略**：
       - **JSON 预处理**：如果输入输出看起来是 JSON（以 `{` 或 `[` 开头）：
       - 去除 Markdown 包裹（```json 和 ```）
       - 尝试解析 JSON
       - 解析成功：用标准格式重新序列化（sort_keys=True，统一key顺序和空格），消除格式差异
       - 解析失败：使用原始文本，不中断比对
       - 算法粗筛：编辑距离计算相似度 = `(input_sim + output_sim) / 2`
       - `>= 0.9` → 满分 1.0，跳过 LLM
       - `< 0.9` → 调用 LLM 验证语义一致性
  3. **结果比对**（如果 `baseline_result` 不为空）：
     - 提取 trace 中**最后一个** llm span 的输出
     - **JSON 预处理**：同上面，如果是 JSON 先标准化
     - 同样两阶段策略：算法粗筛 → 需要时 LLM 验证
  4. **汇总分数**：
     - 如果只有过程比对：`process_score = avg(tool_scores) * 100`，`result_score = null`
     - 如果只有结果比对：`process_score = null`，`result_score = (single_llm_score) * 100`
     - 如果都有：`process_score = avg(tool_scores) * 100`，`result_score = (single_llm_score) * 100`
  5. **判断通过**：
     - 只有过程：`overall_passed = (process_score >= scenario.process_threshold)`
     - 只有结果：`overall_passed = (result_score >= scenario.result_threshold)`
     - 都有：`overall_passed = (process_score >= scenario.process_threshold) && (result_score >= scenario.result_threshold)`
  6. **存储结果**：保存到 `comparison_results` 表
  7. **更新 execution**：
     - `execution.comparison_score = 平均分`（只有一个就用那个分数）
     - `execution.comparison_passed = overall_passed`
     - 如果 `overall_passed = false`，设置 `execution.status = COMPLETED_WITH_MISMATCH`
     - 如果 `overall_passed = true`，设置 `execution.status = COMPLETED`

**修改** `backend/app/services/execution_service.py`
- 在 `run_execution()` 完成后，如果 `scenario.compare_process = True`，自动触发详细比对

**新增依赖**：`python-Levenshtein` → 添加到 `requirements.txt`

### 5. API 层
**修改** `backend/app/api/execution.py`
- 新增 `GET /{execution_id}/comparison` - 获取详细比对结果
- 新增 `POST /{execution_id}/recompare` - 触发重新比对（后台任务）

**新增** `backend/app/api/scenario.py`
- 新增 `POST /{scenario_id}/set-baseline/{execution_id}` - 将指定执行设为该场景的基线

### 6. 数据库迁移
**新建** `backend/migrations/versions/0004_add_comparison_features.py`
- 自动生成迁移文件后检查结构正确

### 7. 前端修改
**修改** `frontend/src/api/types.ts`
- 新增 TypeScript 接口：`SingleToolComparison`, `SingleLLMComparison`, `DetailedComparisonResult`

**修改** `frontend/src/api/client.ts`
- 新增 `getComparison(executionId)` 方法
- 新增 `recompare(executionId)` 方法
- 新增 `setBaseline(scenarioId, executionId)` 方法

**修改** `frontend/src/pages/ExecutionDetail.tsx`
- 新增状态：`comparisonDetail`, `comparisonLoading`
- 在加载执行详情后，如果已完成，加载比对详情
- 在 "全链路回放" 卡片后新增 "比对详情" 卡片：
  - 展示 `process_score`, `result_score`，分别标记通过/不通过
  - 展示 `overall_passed` 总体结论标签
  - 使用 `Collapse` 组件展开查看：
   - Panel 1: Tool 调用比对，列出每个 tool 的结果（标注匹配/未匹配/无基线）
   - Panel 2: LLM 输出比对，展示比对结果
  - 右上角"重新比对"按钮，点击触发重新比对，然后刷新结果
  - 右上角"设为基线"按钮，点击后确认设置
  - 如果 `status = failed`，展示错误 Alert，提示用户重试

**修改** `frontend/src/pages/ScenarioEdit.tsx`
- 新增基线编辑区域：
  - `baseline_tool_calls` - JSON 编辑框
  - `baseline_result` - 文本编辑框
  - 用户可以手动编辑修改基线内容
- 新增状态：`comparisonDetail`, `comparisonLoading`
- 在加载执行详情后，如果已完成，加载比对详情
- 在 "全链路回放" 卡片后新增 "比对详情" 卡片：
  - 展示 `process_score`, `result_score`，分别标记通过/不通过
  - 展示 `overall_passed` 总体结论标签
  - 使用 `Collapse` 组件展开查看：
    - Panel 1: Tool 调用比对，列出每个 tool 的结果
    - Panel 2: LLM 输出比对，列出每个 llm 的结果
  - 右上角"重新比对"按钮，点击触发重新比对，然后刷新结果
  - 如果 `status = failed`，展示错误 Alert，提示用户重试

## 比对策略详细设计

### 算法粗筛相似度计算
```python
from Levenshtein import distance

def levenshtein_similarity(a: str, b: str) -> float:
    """计算 0-1 相似度，1 完全相同"""
    d = distance(a, b)
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1 - (d / max_len)
```

**阈值：**
| 相似度范围 | 处理方式 |
|-----------|---------|
| ≥ 0.9 | 直接给 1.0 分，跳过 LLM |
| < 0.9 | 调用 LLM 验证 |

### LLM 比对 Prompt 设计

**Tool 调用比对：**
```
你是一个工具调用比对专家。请判断实际工具调用和基线工具调用的语义一致性。

工具名称: {tool_name}

基线输入:
{baseline_input}

基线输出:
{baseline_output}

实际输入:
{actual_input}

实际输出:
{actual_output}

请判断：
1. 实际调用和基线在功能意图上是否一致？输入参数是否达到相同目的？输出是否表达相同结果？
2. 给一个一致性分数 0 到 1，0 表示完全不一致，1 表示完全一致。

请严格输出 JSON 格式，不要有其他内容：
{
  "consistent": true/false,
  "score": 0.x,
  "reason": "一两句话解释原因"
}
```

### 重试机制
```python
MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        return await llm_client.compare(prompt)
    except Exception as e:
        if attempt == MAX_RETRIES - 1:
            # 最后一次失败，返回失败
            return 0.0, False, f"LLM 比对失败：已重试 {MAX_RETRIES} 次，错误: {str(e)}"
        # 指数退避等待
        await asyncio.sleep(2 ** attempt)
```

### 附加设计决策（团队讨论结论）

| 决策点 | 结论 |
|--------|------|
| **Tool 名称匹配** | tool 名称不同直接得 0 分，不进行后续比对。只有名称相同才会比对输入输出 |
| **匹配算法** | MVP 使用贪心算法，接口抽象，后续可替换为匈牙利算法（二分图最大权匹配） |
| **异步处理** | 使用 FastAPI BackgroundTasks 处理比对，前端轮询状态，不需要 WebSocket |
| **前端轮询超时** | 轮询间隔 2 秒，最大超时 2 分钟，超时后停止轮询，提示用户手动刷新 |
| **LLM 并发控制** | 使用 `asyncio.Semaphore` 限制同时进行的 LLM 调用数量，避免服务过载；MVP 单进程限制足够，不需要分布式并发控制 |
| **比对历史** | 每次重新比对创建新记录，保留历史，API 只返回最新结果给前端 |
| **超长 JSON 处理** | 总长度限制，优先截断 output 保留 input，截断处添加 `[...truncated]` 标记 |
| **随机字段（UUID/时间戳）** | MVP 不处理，后续迭代支持忽略规则 |
| **LLM 返回格式错误** | 和其他失败一样重试 3 次，仍失败则该 tool 得 0 分，不影响整个比对 |
| **Tool 数量差异展示** | Panel 标题显示 `(匹配数/基线总数)`，未匹配/多余都在列表中标注，得 0 分 |
| **未匹配 tool 计分** | 未匹配得 0 分，计入平均分。这个惩罚是合理的，因为少调用/多调用就是不一致 |
| **基线更新后旧结果** | 基线更新后，旧的比对结果保持不变，不自动重新比对，用户可手动触发重比对 |
| **enable_llm_verification** | 新增配置项，默认启用，用户可关闭以节省 LLM 成本，只做算法粗筛 |
| **比对失败状态** | 如果整个比对过程出错（非分数不通过），execution 保持 `COMPLETED`（因为执行成功），只将 comparison 标记为 `failed` |
| **compare_enabled = false** | 执行完成后不触发比对，execution 正常完成，不生成比对记录 |
| **清除基线** | 用户可手动清空JSON保存即可，不需要专门的清除按钮 |
| **保留分数展示** | 保留 0-100 分数展示，不只给通过/不通过，提供更多信息 |

## 执行方式

- **比对触发**：execution 完成后，如果 `scenario.compare_enabled = True`，自动后台触发比对
- **重新比对**：用户点击"重新比对"按钮，后台新建比对任务，前端轮询
- **基线设置**：支持"从执行一键设置"和"手动编辑"两种方式，一键设置后可手动微调

## 关键文件清单

| 操作 | 文件路径 | 说明 |
|------|---------|------|
| 修改 | `backend/app/domain/entities/scenario.py` | 新增 `baseline_tool_calls`, `baseline_result`, `process_threshold`, `result_threshold`, `tool_count_tolerance`, `compare_enabled`, `enable_llm_verification` 字段 |
| 修改 | `backend/app/domain/entities/execution.py` | 新增 `COMPLETED_WITH_MISMATCH` 状态 |
| 新建 | `backend/app/domain/entities/comparison.py` | `ComparisonResult` 实体 |
| 新建 | `backend/app/domain/repositories/comparison_repo.py` | 比对结果仓储 |
| 修改 | `backend/app/models/scenario.py` | Pydantic schema 新增字段 |
| 修改 | `backend/app/models/execution.py` | 新增比对详情响应 schema |
| 新建 | `backend/app/models/comparison.py` | 比对相关 schema（分离关注点）|
| 修改 | `backend/app/services/comparison.py` | 扩展详细比对逻辑 |
| 修改 | `backend/app/services/execution_service.py` | 执行流程集成详细比对 |
| 修改 | `backend/app/api/execution.py` | 新增获取详情和重新比对 API |
| 新增 | `backend/app/api/scenario.py` | 新增设为基线 API |
| 修改 | `backend/requirements.txt` | 添加 `python-Levenshtein` 依赖 |
| 新建 | `backend/migrations/versions/0004_add_comparison_features.py` | Alembic 迁移：新建 comparison_results 表 + 修改 scenarios 表 + 新增字段 |
| 修改 | `frontend/src/api/types.ts` | 新增 TypeScript 类型定义 |
| 修改 | `frontend/src/api/client.ts` | 新增 API 方法 |
| 修改 | `frontend/src/pages/ExecutionDetail.tsx` | 新增比对详情展示 + 设为基线按钮 |
| 修改 | `frontend/src/pages/ScenarioEdit.tsx` | 新增基线手动编辑区域 |

## 验收测试要点

### 单元测试
- [ ] 算法相似度计算正确（完全相同/完全不同/部分相似）
- [ ] JSON 标准化正确：格式不同内容相同的 JSON 标准化后相同
- [ ] JSON 标准化正确：能正确去除 Markdown 包裹
- [ ] JSON 标准化正确：解析失败返回原文，不抛异常
- [ ] tool 名称不同直接得 0 分
- [ ] tool 次数差异超过容忍度时 process_score = 0
- [ ] tool 次数差异在容忍范围内时正常继续比对
- [ ] 最优匹配能正确找到最大相似度匹配（顺序不同内容对能匹配上）
- [ ] 空基线正确处理：未设置的部分自动跳过，只比对有基线的部分
- [ ] 多个 LLM 只比对最后一个
- [ ] 汇总分数计算正确（平均分 × 100，单分量正确处理）
- [ ] 重试机制正确（失败自动重试，3次失败标记失败）
- [ ] LLM 格式错误重试失败后，该 tool 得 0 分，比对继续

### 集成测试
- [ ] 从执行一键设置基线 → 正确提取 tool_calls 和最后 LLM 输出 → 正确保存到 scenario
- [ ] 手动编辑基线保存 → 正确保存到 scenario
- [ ] `compare_enabled = false` → 执行完成不触发比对
- [ ] `enable_llm_verification = false` → 所有比对都跳过 LLM，只用算法相似度
- [ ] 执行完成后自动触发比对，结果存入 `comparison_results` 表
- [ ] 前端能获取详细比对结果并正确展示
- [ ] 比对失败（整个过程出错）→ execution 保持 COMPLETED，comparison 标记 failed
- [ ] 比对失败后前端显示错误，点击重新比对能重试 → 新建比对记录
- [ ] 阈值配置正确，overall_passed 判断正确
- [ ] 高相似度文本跳过 LLM，低相似度调用 LLM 验证
- [ ] 超长 JSON 正确截断，不报错
- [ ] 轮询超时正确停止，提示用户手动刷新

### 手动验证
- [ ] 在执行详情页面能看到比对详情卡片
- [ ] 能展开查看每个 tool 调用的比对详情（分数、通过状态、原因）
- [ ] 能展开查看每个 LLM 输出的比对详情
- [ ] 重新比对按钮可用，点击后能刷新结果
- [ ] 比对过程中 loading 状态正确
- [ ] 轮询超时提示正确，用户可手动刷新
- [ ] 执行详情页能点击"设为基线" → 确认后正确设置
- [ ] 场景编辑页能手动编辑基线 JSON（包括清空）→ 保存正确
- [ ] 场景编辑页能关闭 LLM 验证 → 保存正确
- [ ] Tool 数量差异正确显示（匹配数/总数），未匹配标注清晰
- [ ] enable_llm_verification = false 能正确保存，比对时不调用 LLM
