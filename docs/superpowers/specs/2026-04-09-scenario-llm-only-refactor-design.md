# Scenario LLM-Only Refactor Design

**版本**: 1.0  
**日期**: 2026-04-09  
**作者**: Claude  
**状态**: Draft

---

## 概述

本次重构将场景模型从"工具+LLM"双比对模式改为**纯LLM比对模式**，移除所有工具调用比对相关字段，新增LLM调用次数范围校验。

## 背景

- 当前系统同时支持工具调用比对和LLM比对，逻辑复杂
- 新的回放设计只需要LLM-Only比对
- 需要简化场景配置，只保留必要的LLM比对参数
- 本次重构涉及**数据库 → 后端服务 → 前端页面**全链路修改，不只是类型定义

---

## 需求变更

| 操作 | 位置 | 字段/配置 | 说明 |
|------|------|-----------|------|
| **API层移除** | scenario create/update | `process_threshold` | 过程通过阈值 |
| **API层移除** | scenario create/update | `result_threshold` | 结果通过阈值 |
| **API层移除** | scenario create/update | `tool_count_tolerance` | 工具次数容忍度 |
| **API层移除** | scenario create/update | `baseline_tool_calls` | 工具调用基线(JSON) |
| **API层移除** | scenario create/update | `compare_process` | 是否启用过程比对开关 |
| **API层移除** | scenario create/update | `compare_result` | 是否启用结果比对开关 |
| **API层移除** | scenario create/update | `enable_llm_verification` | 是否启用LLM验证开关 |
| **新增** | scenarios 表 | `llm_count_min` | 最小允许LLM调用次数 |
| **新增** | scenarios 表 | `llm_count_max` | 最大允许LLM调用次数 |
| **新增** | llm_models 表 | `comparison_prompt` | 结果比对prompt模板，人工维护 |
| **修改逻辑** | set-baseline | baseline_tool_calls | 不再提取和写入 tool_calls（保留字段但不写入新数据）|
| **前端修改** | ScenarioList | 创建/编辑表单 | 移除旧配置项，新增LLM调用次数范围输入 |
| **前端修改** | LLMList | 创建/编辑表单 | 新增比对Prompt输入框 |

**规则固定后**：
- 始终做LLM次数范围校验
- 始终做最后一个LLM输出结果比对（由LLM直接判定）
- 不再支持工具调用比对

---

## 数据库设计

### `scenarios` 表变更

```sql
-- 新增字段
ALTER TABLE scenarios ADD COLUMN llm_count_min INTEGER NOT NULL DEFAULT 0;
ALTER TABLE scenarios ADD COLUMN llm_count_max INTEGER NOT NULL DEFAULT 999;

-- 以下字段标记为废弃，保留不删除
-- baseline_tool_calls
-- process_threshold
-- result_threshold
-- tool_count_tolerance
-- compare_process
-- compare_result
-- enable_llm_verification
```

**默认值**：
- `llm_count_min = 0`：允许0次LLM调用（极少情况）
- `llm_count_max = 999`：允许最多999次LLM调用

**约束规则**：
- 两者必须为非负整数
- `llm_count_min <= llm_count_max`（后端校验+前端校验）
- 如果前端传入非法范围，后端返回明确错误
- 历史数据/手工修改如果出现 `min > max`，比对时默认不通过并记录错误

**默认prompt落点**：
- 数据库migration阶段自动给所有现有LLM记录填充默认prompt
- 创建新LLM时，后端自动填充默认prompt到 `comparison_prompt`
- 唯一真源：`llm_models.comparison_prompt` 数据库字段

---

## 新比对结果结构 (`details_json`)

新结构（LLM-Only模式）：

```typescript
{
  llm_count_check: {
    expected_min: number
    expected_max: number
    actual_count: number
    passed: boolean
  }
  final_output_comparison: {
    baseline_output: string
    actual_output: string
    consistent: boolean
    reason: string
  }
  // tool_comparisons 始终为空数组
  tool_comparisons: []
}
```

**现有字段兼容**：
- `process_score`: 保留为 `null`（无过程比对）
- `result_score`: 保留为 `null`（不用分数，直接LLM判定）
- `overall_passed`: `llm_count_check.passed AND final_output_comparison.consistent`
- `tool_comparisons`: 始终为空数组 `[]`
- `llm_comparison`: 保留为 `null`（不再使用旧结构）

**新结构存储在 `details_json`**：
```typescript
{
  llm_count_check: {
    expected_min: number
    expected_max: number
    actual_count: number
    passed: boolean
  }
  final_output_comparison: {
    baseline_output: string
    actual_output: string
    consistent: boolean
    reason: string
  }
  tool_comparisons: []
}
```

**Pydantic API 契约更新**：
`DetailedComparisonResponse` 保留原有字段（兼容旧数据），但语义变化：
- `tool_comparisons` 始终为空数组
- `llm_comparison` 始终为 null
- `process_score`/`result_score` 始终为 null

**前端详情页适配**：不再展示过程分数、结果分数、工具比对折叠面板、相似度分数，只展示：
1. LLM调用次数检查结果（期望范围 vs 实际次数 是否通过）
2. 最终输出比对结果（consistent + reason）

---

## 执行规则明确

**问题**：没有选择LLM模型时如何处理？

**规则**：
- `execution.llm_model_id` **创建时即为必填**，必须选择才能创建执行
- 只要 `scenario.compare_enabled = True` 就一定会执行比对
- 不再支持"退化为算法相似度"模式
- **重新比对**也必须选LLM才能发起
- 如果 `scenario.compare_enabled = False` → 比对不执行，`overall_passed = null`

---

## set-baseline 流程变更

**规则**：
- 不再提取 `tool_calls` 写入 `scenario.baseline_tool_calls`
- **不主动清空历史值**：该字段数据库保留，已有数据保持原值不变，新set-baseline操作也不修改该字段
- 只提取 `last_llm_output` 写入 `scenario.baseline_result`（保持现有逻辑不变）
- 新设计不依赖工具基线，所以不需要提取

---

## 后端设计

### 1. 领域实体 (`app/domain/entities/scenario.py`)

```python
class Scenario(Base):
    __tablename__ = "scenarios"

    # ... 现有字段不变 ...

    # 新字段：LLM调用次数范围
    llm_count_min = Column(Integer, nullable=False, default=0)
    llm_count_max = Column(Integer, nullable=False, default=999)

    # 已废弃字段（保留向后兼容）
    baseline_tool_calls = Column(Text)  # deprecated: 不再存储工具调用基线
    process_threshold = Column(Double, nullable=False, default=60.0)  # deprecated
    result_threshold = Column(Double, nullable=False, default=60.0)  # deprecated
    tool_count_tolerance = Column(Integer, nullable=False, default=0)  # deprecated
    compare_result = Column(Boolean, nullable=False, default=True)  # deprecated
    compare_process = Column(Boolean, nullable=False, default=False)  # deprecated
    enable_llm_verification = Column(Boolean, nullable=False, default=True)  # deprecated
    compare_enabled = Column(Boolean, nullable=False, default=True)  # 保留，仍用于控制是否启用自动比对
```

### 2. Pydantic 模型 (`app/models/scenario.py`)

**`ScenarioCreate`**:
- 移除四个废弃字段
- 新增 `llm_count_min` 和 `llm_count_max`，默认值 `0` 和 `999`

**`ScenarioUpdate`**:
- 移除四个废弃字段
- 新增 `llm_count_min` 和 `llm_count_max` 可选字段

**`ScenarioResponse`**:
- 移除四个废弃字段 + 三个开关字段
- 新增 `llm_count_min` 和 `llm_count_max`

### 3. 比对逻辑变更（ComparisonService.detailed_compare）

**LLM次数校验**：
```python
# 从trace中提取所有LLM spans
llm_spans = [s for s in trace_spans if s.span_type == 'llm']
actual_count = len(llm_spans)

# 校验范围
llm_count_check = {
    'expected_min': scenario.llm_count_min,
    'expected_max': scenario.llm_count_max,
    'actual_count': actual_count,
    'passed': scenario.llm_count_min <= actual_count <= scenario.llm_count_max
}

if not llm_count_check['passed']:
    overall_passed = False
```

**结果比对**：
- 基线最后一个输出：直接使用场景已存储的 `baseline_result` 字段（set-baseline时已经提取好了）
- 回放最后一个输出：`llm_spans[-1].output`（从回放trace提取所有LLM，取最后一个）
- 从选中的LLM模型配置读取 `comparison_prompt` 模板
- 填入参数调用LLM，直接获取 `{"consistent": boolean, "reason": string}`
- 不使用相似度阈值，完全信任LLM判定结果

**结果结构**：
```python
details = {
    'llm_count_check': llm_count_check,
    'final_output_comparison': {
        'baseline_output': baseline_output,
        'actual_output': actual_output,
        'consistent': consistent,
        'reason': reason,
    },
    'tool_comparisons': [],  # 始终为空，不再支持工具比对
}
```

**overall_passed 判定**：
```python
overall_passed = llm_count_check['passed'] and consistent
```

**process_score / result_score**：
- 始终为 `None`，因为不再使用分数阈值机制
- 数据库字段保留，兼容现有结构

**不再做**：
- 过程中每个LLM逐一比对
- 工具调用任何形式比对
- 基于相似度分数的阈值判断
- "高相似度跳过LLM"优化

**Prompt配置**：
判定一致性的prompt作为LLM模型配置的一部分，由人工维护（和现有其他提示词配置方式一致）：

```
请判断下面【基线输出】和【实际输出】的核心语义是否一致：

基线输出:
{{baseline_result}}

实际输出:
{{actual_result}}

要求：
1. 核心语义一致（回答问题结论相同、解决同一个问题、满足相同需求）→ consistent = true
2. 核心语义不一致 → consistent = false
3. 请简要说明判定原因
4. 以JSON格式输出：{"consistent": boolean, "reason": string}
```

比对服务从选中的LLM模型配置中读取这个prompt模板，填入参数后调用LLM。这样prompt可随时调整，无需改代码。

### 数据库变更：`llm_models` 表新增字段

```sql
ALTER TABLE llm_models ADD COLUMN comparison_prompt TEXT;
```

**默认值：** 使用默认比对prompt，已有LLM记录会自动填充默认值。

---

### 后端设计更新

#### 领域实体 (`app/domain/entities/llm.py`)

```python
class LLMModel(Base):
    """LLM 比对模型配置"""

    __tablename__ = "llm_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    provider = Column(String(50), nullable=False)
    model_id = Column(String(255), nullable=False)
    base_url = Column(String(2048))
    api_key_encrypted = Column(Text, nullable=False)
    temperature = Column(Double, nullable=False, default=0.0)
    max_tokens = Column(Integer, nullable=False, default=1024)
    comparison_prompt = Column(Text)  # 结果比对prompt模板
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime(timezone=True))
```

#### Pydantic模型更新 (`app/models/llm.py`)

需要更新 `LLMModelCreate` / `LLMModelUpdate` / `LLMModelResponse`：
- 新增 `comparison_prompt` 可选字段
- 默认值使用上文的默认比对prompt

---

### 前端设计更新

#### TypeScript类型 (`frontend/src/api/types.ts`)

```typescript
export interface LLMModel {
  id: string
  name: string
  provider: string
  model_id: string
  base_url?: string
  temperature: number
  max_tokens: number
  comparison_prompt?: string  // 新增
  is_default: boolean
  created_at: string
  updated_at: string
}
```

#### LLM模型创建/编辑表单

**新增表单项：**
- "比对Prompt" - 多行文本框，编辑比对prompt模板
- 默认填充默认prompt模板

---

**前端变更：** 在LLM模型创建/编辑表单中新增"比对Prompt"文本框，供人工编辑维护。

---

## 前端设计

### 1. TypeScript 类型 (`frontend/src/api/types.ts`)

```typescript
export interface Scenario {
  // ... 其他字段不变 ...
  llm_count_min: number
  llm_count_max: number
  compare_enabled: boolean  // 保留
  // 以下字段移除：
  // baseline_tool_calls
  // process_threshold
  // result_threshold
  // tool_count_tolerance
  // compare_result
  // compare_process
  // enable_llm_verification
}
```

### 2. 场景创建/编辑表单

**移除表单项**：
- 过程通过阈值
- 结果通过阈值
- 工具次数容忍度
- 工具调用基线 (JSON)
- 启用过程比对 复选框
- 启用结果比对 复选框
- 启用LLM验证 复选框

**新增表单项**：
- LLM调用次数范围：最小值输入框 + 最大值输入框
- 默认值：最小值 `0`，最大值 `999`

---

## 比对流程变化

### 旧流程
```
工具次数检查 -> 逐个工具比对 -> 逐个LLM比对 -> 最终结果比对
```

### 新流程
```
LLM调用次数范围检查 ↓
次数不通过 → 整体不通过
次数通过 → 提取最后一个LLM输出 → 调用LLM做语义判定 ↓
判定不通过 → 整体不通过
判定通过 → 整体通过
```

---

## 向后兼容

- 数据库层面：旧字段保留不删除，现有数据不受影响
- 代码层面：新代码不再读取写入废弃字段
- 迁移安全：只做ADD COLUMN，不做DROP COLUMN

---

## 实施范围

本次修改涉及全链路：

| 层级 | 文件 | 修改内容 |
|------|------|----------|
| **DB** | `alembic/versions/...` | 新增 `scenarios.llm_count_min/max` + `llm_models.comparison_prompt`，回填默认prompt |
| **实体** | `backend/app/domain/entities/scenario.py` | 新增字段，标记旧字段废弃 |
| **实体** | `backend/app/domain/entities/llm.py` | 新增 `comparison_prompt` |
| **Pydantic** | `backend/app/models/scenario.py` | 移除旧字段，新增LLM范围字段 |
| **Pydantic** | `backend/app/models/llm.py` | 新增 `comparison_prompt` |
| **Service** | `backend/app/services/scenario_service.py` | 移除旧字段的赋值和更新 |
| **Service** | `backend/app/services/comparison.py` | 重构比对逻辑为LLM-Only模式 |
| **API** | `backend/app/api/scenario.py` | `set-baseline` 不再提取 `baseline_tool_calls` |
| **Execution** | `backend/app/services/execution_service.py` | 规则适配：移除"退化为算法相似度"兼容分支 |
| **前端类型** | `frontend/src/api/types.ts` | 更新 Scenario 和 LLMModel 接口 |
| **前端表单** | `frontend/src/pages/ScenarioList.tsx` | 移除旧配置项，新增LLM调用次数范围输入 |
| **前端表单** | `frontend/src/pages/LLMList.tsx` | 新增比对Prompt输入框 |

不影响：
- 已存储的历史执行数据（向后兼容，旧字段保留）

---

## 完成标准

- [ ] 数据库迁移成功运行，新增两个字段到scenarios、新增comparison_prompt到llm_models
- [ ] 现有LLM记录自动填充默认比对prompt
- [ ] 后端实体/Pydantic模型更新完成，旧字段从API层移除并标记废弃
- [ ] scenario_service create/update不再读写废弃字段
- [ ] set-baseline不再提取和写入baseline_tool_calls
- [ ] ComparisonService重构为LLM-Only比对逻辑
- [ ] LLM次数范围校验正确工作，非法范围判定失败
- [ ] 只比对最后一个LLM输出结果，由LLM直接判定通过/不通过并给出原因
- [ ] 前端类型更新，ScenarioList表单移除旧配置项、新增LLM范围输入
- [ ] 前端LLMList表单新增comparison_prompt输入框
- [ ] 移除"不选LLM退化为算法相似度"选项
- [ ] 比对结果details_json使用新结构存储
- [ ] 向后兼容保留旧数据
