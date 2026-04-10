# Scenario LLM-Only Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将场景比对模式从"工具+LLM"双比对重构为纯LLM比对模式，移除工具调用比对相关字段，新增LLM调用次数范围校验，由LLM直接判定最终输出一致性。

**Architecture:** 采用增量重构策略，数据库层面只新增字段不删除旧字段保持向后兼容；后端API层移除废弃字段，重构ComparisonService比对逻辑；前端更新类型定义并简化表单配置。比对流程简化为：LLM次数范围检查 → 通过后由选中的LLM模型直接判定最后输出一致性。

**Tech Stack:** Python FastAPI + SQLAlchemy + Pydantic + React + TypeScript + Ant Design

---

## 文件结构映射

| 文件 | 操作 | 说明 |
|------|------|------|
| `alembic/versions/<migration_id>.py` | Create | 新增 `scenarios.llm_count_min/max` 和 `llm_models.comparison_prompt` |
| `backend/app/domain/entities/scenario.py` | Modify | 新增LLM范围字段，标记旧字段废弃 |
| `backend/app/domain/entities/llm.py` | Modify | 新增 `comparison_prompt` 字段 |
| `backend/app/models/scenario.py` | Modify | 移除旧字段，新增LLM范围字段 |
| `backend/app/models/llm.py` | Modify | 新增 `comparison_prompt` 字段 |
| `backend/app/models/execution.py` | Modify | `CreateExecutionRequest` 中 `llm_model_id` 改为必填 |
| `backend/app/models/comparison.py` | Modify | 新增 `LLMCountCheck`, `FinalOutputComparison`，更新 `DetailedComparisonResponse` |
| `backend/app/services/scenario_service.py` | Modify | 移除废弃字段读写，新增LLM范围字段 |
| `backend/app/services/llm_service.py` | Modify | 创建LLM时自动填充默认 `comparison_prompt` |
| `backend/app/services/comparison.py` | Modify | 重构 `detailed_compare` 为LLM-Only比对逻辑 |
| `backend/app/api/scenario.py` | Modify | `set-baseline` 不再提取 `baseline_tool_calls` |
| `backend/app/api/execution.py` | Modify | 更新 `get_comparison` 端点解析新结构，`recompare` 强制 `llm_model_id` |
| `frontend/src/api/types.ts` | Modify | 更新 `Scenario`, `LLMModel`, `DetailedComparisonResult` 接口 |
| `frontend/src/pages/ScenarioList.tsx` | Modify | 移除旧配置项，新增LLM调用次数范围输入 |
| `frontend/src/pages/LLMList.tsx` | Modify | 新增比对Prompt输入框 |
| `frontend/src/pages/ExecutionList.tsx` | Modify | 创建执行时LLM模型改为必填 |
| `frontend/src/pages/ExecutionDetail.tsx` | Modify | 适配新的比对结果展示结构 |

---

## 任务分解

### Task 1: 数据库迁移 - 新增字段

**Files:**
- Create: `alembic/versions/<timestamp>_add_llm_count_fields.py`

- [ ] **Step 1: Create migration file**

```bash
cd backend
alembic revision --autogenerate -m "Add llm_count_min/max to scenarios and comparison_prompt to llm_models"
```

- [ ] **Step 2: Edit migration file to match spec**

```python
"""Add llm_count fields to scenarios and comparison_prompt to llm_models

Revision ID: <revision_id>
Revises: <previous_revision>
Create Date: 2026-04-09

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '<revision_id>'
down_revision = '<previous_revision>'
branch_labels = None
depends_on = None


def upgrade():
    # Add LLM count range fields to scenarios
    op.add_column('scenarios', sa.Column('llm_count_min', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('scenarios', sa.Column('llm_count_max', sa.Integer(), nullable=False, server_default='999'))
    
    # Add comparison_prompt to llm_models
    op.add_column('llm_models', sa.Column('comparison_prompt', sa.Text(), nullable=True))
    
    # Backfill default comparison_prompt for existing LLM records
    default_prompt = '''请判断下面【基线输出】和【实际输出】的核心语义是否一致：

基线输出:
{{baseline_result}}

实际输出:
{{actual_result}}

要求：
1. 核心语义一致（回答问题结论相同、解决同一个问题、满足相同需求）→ consistent = true
2. 核心语义不一致 → consistent = false
3. 请简要说明判定原因
4. 以JSON格式输出：{"consistent": boolean, "reason": string}'''
    
    # Update existing records with default prompt
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE llm_models SET comparison_prompt = :prompt WHERE comparison_prompt IS NULL"),
        {"prompt": default_prompt}
    )


def downgrade():
    op.drop_column('scenarios', 'llm_count_max')
    op.drop_column('scenarios', 'llm_count_min')
    op.drop_column('llm_models', 'comparison_prompt')
```

- [ ] **Step 3: Run migration**

```bash
alembic upgrade head
```

Expected: Migration completes successfully, two new columns added to scenarios, one new column added to llm_models.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/<revision_id>_add_llm_count_fields.py
git commit -m "feat: add migration for llm count fields and comparison prompt"
```

---

### Task 2: 更新Scenario领域实体

**Files:**
- Modify: `backend/app/domain/entities/scenario.py`

- [ ] **Step 1: Read current file content to see existing structure**

- [ ] **Step 2: Add new fields and mark deprecated fields**

```python
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

- [ ] **Step 3: Verify syntax**

```bash
cd backend && python -m pytest app/domain/entities/scenario.py -v
```

Expected: No syntax errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/domain/entities/scenario.py
git commit -m "feat: add llm_count_min/max fields to scenario entity"
```

---

### Task 3: 更新LLMModel领域实体

**Files:**
- Modify: `backend/app/domain/entities/llm.py`

- [ ] **Step 1: Read current file content**

- [ ] **Step 2: Add `comparison_prompt` field after `max_tokens`**

```python
max_tokens = Column(Integer, nullable=False, default=1024)
comparison_prompt = Column(Text)  # 结果比对prompt模板
is_default = Column(Boolean, nullable=False, default=False)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/domain/entities/llm.py
git commit -m "feat: add comparison_prompt field to LLMModel entity"
```

---

### Task 4: 更新Scenario Pydantic模型

**Files:**
- Modify: `backend/app/models/scenario.py`

- [ ] **Step 1: Read current file**

- [ ] **Step 2: Update `ScenarioCreate` - remove ALL deprecated fields, add new fields with validation**

```python
class ScenarioCreate(BaseModel):
    agent_id: UUID
    name: str
    description: Optional[str] = None
    prompt: str
    baseline_result: Optional[str] = None
    llm_count_min: int = 0  # 新增：最小LLM调用次数
    llm_count_max: int = 999  # 新增：最大LLM调用次数
    compare_enabled: bool = True  # 保留：控制是否启用自动比对

    @model_validator(mode='after')
    def validate_llm_count_range(self) -> 'ScenarioCreate':
        if self.llm_count_min < 0 or self.llm_count_max < 0:
            raise ValueError('llm_count_min and llm_count_max must be non-negative')
        if self.llm_count_min > self.llm_count_max:
            raise ValueError('llm_count_min must be less than or equal to llm_count_max')
        return self
```

已完全移除所有废弃字段：
- `baseline_tool_calls` ✅ 彻底移除（数据库实体层保留但API层不再接收）
- `process_threshold` ✅ 移除
- `result_threshold` ✅ 移除
- `tool_count_tolerance` ✅ 移除
- `compare_result` ✅ 移除
- `compare_process` ✅ 移除
- `enable_llm_verification` ✅ 移除

- [ ] **Step 3: Update `ScenarioUpdate`**

```python
class ScenarioUpdate(BaseModel):
    agent_id: Optional[UUID] = None
    name: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    baseline_result: Optional[str] = None
    llm_count_min: Optional[int] = None  # 新增
    llm_count_max: Optional[int] = None  # 新增
    compare_enabled: Optional[bool] = None  # 保留

    @model_validator(mode='after')
    def validate_llm_count_range(self) -> 'ScenarioUpdate':
        if self.llm_count_min is not None and self.llm_count_max is not None:
            if self.llm_count_min < 0 or self.llm_count_max < 0:
                raise ValueError('llm_count_min and llm_count_max must be non-negative')
            if self.llm_count_min > self.llm_count_max:
                raise ValueError('llm_count_min must be less than or equal to llm_count_max')
        return self
```

已完全移除所有废弃字段。

- [ ] **Step 4: Update `ScenarioResponse`**

```python
class ScenarioResponse(BaseModel):
    id: UUID
    agent_id: UUID
    agent_name: Optional[str] = None
    name: str
    description: Optional[str] = None
    prompt: str
    baseline_result: Optional[str] = None
    llm_count_min: int  # 新增
    llm_count_max: int  # 新增
    compare_enabled: bool  # 保留
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

Remove all deprecated fields from response.

- [ ] **Step 5: Run type check**

```bash
cd backend && python -m pytest app/models/scenario.py -v
```

Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/scenario.py
git commit -m "feat: update scenario pydantic models for llm-only refactor"
```

---

### Task 5: 更新LLM Pydantic模型

**Files:**
- Modify: `backend/app/models/llm.py`

- [ ] **Step 1: Read current file**

- [ ] **Step 2: Add DEFAULT_COMPARISON_PROMPT and update `LLMCreate`**

```python
DEFAULT_COMPARISON_PROMPT = '''请判断下面【基线输出】和【实际输出】的核心语义是否一致：

基线输出:
{{baseline_result}}

实际输出:
{{actual_result}}

要求：
1. 核心语义一致（回答问题结论相同、解决同一个问题、满足相同需求）→ consistent = true
2. 核心语义不一致 → consistent = false
3. 请简要说明判定原因
4. 以JSON格式输出：{"consistent": boolean, "reason": string}'''

class LLMCreate(BaseModel):
    name: str
    provider: str
    model_id: str
    base_url: Optional[str] = None
    api_key: str
    temperature: float = 0.0
    max_tokens: int = 1024
    comparison_prompt: str = DEFAULT_COMPARISON_PROMPT  # 新增：默认比对prompt
    is_default: bool = False
```

- [ ] **Step 3: Update `LLMUpdate`**

```python
class LLMUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model_id: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    comparison_prompt: Optional[str] = None  # 新增
    is_default: Optional[bool] = None
```

- [ ] **Step 4: Update `LLMResponse`**

```python
class LLMResponse(BaseModel):
    id: UUID
    name: str
    provider: str
    model_id: str
    base_url: Optional[str] = None
    temperature: float
    max_tokens: int
    comparison_prompt: Optional[str]  # 新增
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

类名与现有代码保持一致：`LLMCreate`/`LLMUpdate`/`LLMResponse`。

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/llm.py
git commit -m "feat: add comparison_prompt to LLM pydantic models"
```

---

### Task 6: 更新CreateExecutionRequest强制llm_model_id必填

**Files:**
- Modify: `backend/app/models/execution.py`

- [ ] **Step 1: Read current file**

- [ ] **Step 2: Change `llm_model_id` from Optional to required**

```python
class CreateExecutionRequest(BaseModel):
    agent_id: UUID
    scenario_id: UUID
    llm_model_id: UUID  # 改为必填：新规则要求必须选择LLM模型才能比对
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/execution.py
git commit -m "feat: make llm_model_id required in CreateExecutionRequest"
```

---

### Task 7: 更新比较结果Pydantic模型新增字段

**Files:**
- Modify: `backend/app/models/comparison.py`

- [ ] **Step 1: Read current file**

- [ ] **Step 2: Add new Pydantic models for LLM-Only comparison after imports**

```python
class LLMCountCheck(BaseModel):
    expected_min: int
    expected_max: int
    actual_count: int
    passed: bool


class FinalOutputComparison(BaseModel):
    baseline_output: str
    actual_output: str
    consistent: bool
    reason: str
```

- [ ] **Step 3: Update `DetailedComparisonResponse`**

Add the two new fields to the class:

```python
class DetailedComparisonResponse(BaseModel):
    id: UUID
    execution_id: UUID
    scenario_id: UUID
    trace_id: Optional[str]
    process_score: Optional[float]  # 始终为 None，兼容旧结构
    result_score: Optional[float]  # 始终为 None，兼容旧结构
    overall_passed: bool
    tool_comparisons: List[SingleToolComparison]  # 始终为空数组
    llm_comparison: Optional[SingleLLMComparison]  # 始终为 None，兼容旧结构
    llm_count_check: Optional[LLMCountCheck]  # 新增：LLM次数检查结果
    final_output_comparison: Optional[FinalOutputComparison]  # 新增：最终输出比对结果
    status: str
    error_message: Optional[str]
    retry_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/comparison.py
git commit -m "feat: add new fields to DetailedComparisonResponse for LLM-Only"
```

---

### Task 8: 更新get_comparison API端点解析新结构

**Files:**
- Modify: `backend/app/api/execution.py`

- [ ] **Step 1: Read current `get_comparison_detail` endpoint**

- [ ] **Step 2: Import new Pydantic models**

```python
from app.models.comparison import (
    DetailedComparisonResponse,
    LLMCountCheck,
    FinalOutputComparison,
)
from app.models.common import Response
from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
```

- [ ] **Step 3: Update endpoint to parse details_json into new response structure,保持统一Response包装**

```python
@router.get("/{execution_id}/comparison", response_model=Response[DetailedComparisonResponse])
async def get_comparison_detail(
    execution_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """获取比对详情，支持新的LLM-Only结构和旧结构兼容"""
    comparison_repo = SQLAlchemyComparisonRepository()
    comparison_result = await comparison_repo.get_by_execution_id(session, execution_id)
    if not comparison_result:
        raise HTTPException(status_code=404, detail="Comparison not found")
    
    # 解析details_json
    details: Dict[str, Any] = {}
    if comparison_result.details_json:
        try:
            details = json.loads(comparison_result.details_json)
        except json.JSONDecodeError:
            details = {}
    
    # 解析新结构字段
    llm_count_check = None
    final_output_comparison = None
    if 'llm_count_check' in details and details['llm_count_check']:
        llm_count_check = LLMCountCheck(**details['llm_count_check'])
    if 'final_output_comparison' in details and details['final_output_comparison']:
        final_output_comparison = FinalOutputComparison(**details['final_output_comparison'])
    
    data = DetailedComparisonResponse(
        id=comparison_result.id,
        execution_id=comparison_result.execution_id,
        scenario_id=comparison_result.scenario_id,
        trace_id=comparison_result.trace_id,
        process_score=comparison_result.process_score,  # 兼容：旧数据有值，新数据None
        result_score=comparison_result.result_score,  # 兼容：旧数据有值，新数据None
        overall_passed=comparison_result.overall_passed,
        tool_comparisons=[],  # 新结构始终为空，旧数据不返回（兼容处理简化）
        llm_comparison=None,  # 新结构始终为None
        llm_count_check=llm_count_check,
        final_output_comparison=final_output_comparison,
        status=comparison_result.status,
        error_message=comparison_result.error_message,
        retry_count=comparison_result.retry_count,
        created_at=comparison_result.created_at,
        updated_at=comparison_result.updated_at,
        completed_at=comparison_result.completed_at,
    )
    return Response[DetailedComparisonResponse](data=data)
```

保持现有的统一`Response[T]`包装不变，只更新内部data的结构。

- [ ] **Step 4: Check `recompare` endpoint - ensure llm_model_id is required**

Verify that `recompare` endpoint requires `llm_model_id` and does not have fallback to dummy/algorithm comparison. If there's a fallback branch, remove it. Now it's required that caller provides `llm_model_id`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/execution.py
git commit -m "feat: update get_comparison to support new LLM-Only structure"
```

---

### Task 9: 更新ScenarioService移除废弃字段

**Files:**
- Modify: `backend/app/services/scenario_service.py`

- [ ] **Step 1: Read current file**

- [ ] **Step 2: Update `create_scenario` method**

Modify the Scenario constructor:

```python
async def create_scenario(self, request: ScenarioCreate) -> Scenario:
    """创建场景"""
    scenario = Scenario(
        agent_id=request.agent_id,
        name=request.name,
        description=request.description,
        prompt=request.prompt,
        baseline_result=request.baseline_result,
        llm_count_min=request.llm_count_min,
        llm_count_max=request.llm_count_max,
        compare_enabled=request.compare_enabled,
    )
    result = await self.repo.create(scenario)
    logger.info(f"Created scenario: {result.id} name={result.name} agent_id={request.agent_id}")
    return result
```

Remove assignments to deprecated fields: `compare_result`, `compare_process`.

- [ ] **Step 3: Update `update_scenario` method - remove deprecated field assignments**

Remove these lines:

```python
if request.process_threshold is not None:
    scenario.process_threshold = request.process_threshold
if request.result_threshold is not None:
    scenario.result_threshold = request.result_threshold
if request.tool_count_tolerance is not None:
    scenario.tool_count_tolerance = request.tool_count_tolerance
if request.enable_llm_verification is not None:
    scenario.enable_llm_verification = request.enable_llm_verification
if request.compare_result is not None:
    scenario.compare_result = request.compare_result
if request.compare_process is not None:
    scenario.compare_process = request.compare_process
```

Add these new lines:

```python
if request.llm_count_min is not None:
    scenario.llm_count_min = request.llm_count_min
if request.llm_count_max is not None:
    scenario.llm_count_max = request.llm_count_max
```

- [ ] **Step 4: Update logger at top of method - remove deprecated fields**

```python
logger.info(f"Update scenario {scenario_id}: llm_count_min={request.llm_count_min}, llm_count_max={request.llm_count_max}")
```

- [ ] **Step 5: Run test to verify syntax**

```bash
cd backend && python -m pytest app/services/scenario_service.py -v
```

Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scenario_service.py
git commit -m "feat: update scenario_service to remove deprecated fields"
```

---

### Task 10: 更新LLMService创建时填充默认comparison_prompt

**Files:**
- Modify: `backend/app/services/llm_service.py`

- [ ] **Step 1: Read current file**

- [ ] **Step 2: Import DEFAULT_COMPARISON_PROMPT and update create method**

```python
from app.models.llm import DEFAULT_COMPARISON_PROMPT, LLMCreate

...

async def create_llm(self, request: LLMCreate) -> LLMModel:
    """创建LLM模型"""
    llm_model = LLMModel(
        name=request.name,
        provider=request.provider,
        model_id=request.model_id,
        base_url=request.base_url,
        api_key_encrypted=encrypt_api_key(request.api_key),
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        comparison_prompt=request.comparison_prompt or DEFAULT_COMPARISON_PROMPT,
        is_default=False,
    )
    result = await self.repo.create(llm_model)
    logger.info(f"Created LLM model: {result.id} name={result.name} model_id={request.model_id}")
    return result
```

类名与`models/llm.py`保持一致。

说明：上面示例中的 `comparison_prompt` 赋值应以 `request.comparison_prompt or DEFAULT_COMPARISON_PROMPT` 为准；类名、方法名与当前仓库真实定义保持一致：`LLMCreate / LLMUpdate / LLMResponse`、`create_llm / update_llm`。
- [ ] **Step 3: Update update method**

说明：`create_llm` 示例里应使用 `comparison_prompt=request.comparison_prompt or DEFAULT_COMPARISON_PROMPT`，并保持当前仓库中的命名 `LLMCreate / LLMUpdate / LLMResponse`、`create_llm / update_llm` 不变。

Add this line in update:

```python
if request.comparison_prompt is not None:
    llm_model.comparison_prompt = request.comparison_prompt
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/llm_service.py
git commit -m "feat: update llm_service to handle comparison_prompt"
```

---

### Task 11: 重构ComparisonService为LLM-Only比对逻辑

**Files:**
- Modify: `backend/app/services/comparison.py`

- [ ] **Step 1: Read current `detailed_compare` method**

- [ ] **Step 2: Add DEFAULT_COMPARISON_PROMPT import**

```python
from app.models.llm import DEFAULT_COMPARISON_PROMPT
```

- [ ] **Step 3: Rewrite `detailed_compare` method to LLM-Only scheme**

```python
async def detailed_compare(
    self,
    scenario: Scenario,
    execution: ExecutionJob,
    trace_spans: List[Span],
    llm_model: LLMModel,
) -> ComparisonResultEntity:
    """LLM-Only 详细比对：检查LLM调用次数范围 + LLM判定最后输出一致性"""
    
    # 提取所有LLM spans
    llm_spans = [s for s in trace_spans if s.span_type == 'llm']
    actual_count = len(llm_spans)
    
    # 1. LLM调用次数范围校验
    llm_count_check = {
        'expected_min': scenario.llm_count_min,
        'expected_max': scenario.llm_count_max,
        'actual_count': actual_count,
        'passed': scenario.llm_count_min <= actual_count <= scenario.llm_count_max,
    }
    
    details: Dict[str, Any] = {
        'llm_count_check': llm_count_check,
        'final_output_comparison': None,
        'tool_comparisons': [],  # 始终为空，不再支持工具比对
    }
    
    process_score: Optional[float] = None  # 始终为 None，兼容
    result_score: Optional[float] = None  # 始终为 None，不再使用分数
    overall_passed = llm_count_check['passed']
    
    # 只有次数通过 且 有基线结果 且 有LLM输出 才做结果比对
    if overall_passed and scenario.baseline_result and llm_spans:
        baseline_output = scenario.baseline_result.strip()
        last_llm = llm_spans[-1]
        actual_output = (last_llm.output or '').strip()
        
        # 获取比对prompt模板
        prompt_template = llm_model.comparison_prompt or DEFAULT_COMPARISON_PROMPT
        prompt = prompt_template.replace('{{baseline_result}}', baseline_output)
        prompt = prompt.replace('{{actual_result}}', actual_output)
        
        # 调用LLM进行判定
        try:
            judgment = await self._call_llm_for_judgment(llm_model, prompt)
            final_output_comparison = {
                'baseline_output': baseline_output,
                'actual_output': actual_output,
                'consistent': judgment.get('consistent', False),
                'reason': judgment.get('reason', ''),
            }
            details['final_output_comparison'] = final_output_comparison
            overall_passed = llm_count_check['passed'] and final_output_comparison['consistent']
        except Exception as e:
            logger.error(f"LLM judgment failed: {e}")
            details['error'] = str(e)
            overall_passed = False
    
    # 创建比对结果实体
    result = ComparisonResultEntity(
        execution_id=execution.id,
        scenario_id=scenario.id,
        trace_id=execution.trace_id,
        process_score=process_score,
        result_score=result_score,
        overall_passed=overall_passed,
        details_json=json.dumps(details, ensure_ascii=False),
        status='completed',
        error_message=None,
    )
    
    # 按照当前仓库接口，此处只构造并返回 ComparisonResultEntity，
    # 由 ExecutionService / recompare 调用方在外部通过 comparison_repo.create(session, result) 持久化
    return result
```

- [ ] **Step 4: Implement `_call_llm_for_judgment` method**

Add this method to parse JSON response from LLM:

```python
async def _call_llm_for_judgment(self, llm_model: LLMModel, prompt: str) -> Dict[str, Any]:
    """调用LLM进行一致性判定，解析JSON输出"""
    client = self._create_client(llm_model)
    response = await client.generate(prompt)
    content = response.strip()
    
    # 尝试解析JSON，处理可能的markdown包裹
    if '```json' in content:
        content = content.split('```json')[1].split('```')[0].strip()
    elif '```' in content:
        content = content.split('```')[1].split('```')[0].strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM judgment as JSON: {content}")
        # 如果解析失败，保守判定为不一致
        return {
            'consistent': False,
            'reason': f'LLM输出解析失败: {str(e)}, 原始输出: {content[:200]}'
        }
```

- [ ] **Step 5: Remove old tool comparison code paths**

Verify all old tool/process comparison code paths are removed or bypassed for new comparisons.

- [ ] **Step 6: Run syntax check**

```bash
cd backend && python -m pytest app/services/comparison.py -v
```

Expected: No syntax errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/comparison.py
git commit -m "refactor: rewrite detailed_compare to LLM-Only comparison"
```

---

### Task 11a: 更新ExecutionService调用链路 - 传入llm_model，并继续由外部调用方保存 comparison_result

**Files:**
- Modify: `backend/app/services/execution_service.py`

- [ ] **Step 1: Read current comparison call section**

Find where `comparison_service.detailed_compare()` is called after execution completes.

- [ ] **Step 2: Update method signature - get llm_model from database and pass it in**

```python
# Before the call to detailed_compare:
from app.services.llm_service import LLMService
from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository

llm_service = LLMService(self.session)
llm_model = await llm_service.get_llm(execution.llm_model_id)
comparison_repo = SQLAlchemyComparisonRepository()
if not llm_model or llm_model.deleted_at is not None:
    # llm_model_id is required, so this should not happen if request validated properly
    comparison_result = ComparisonResultEntity(
        execution_id=execution.id,
        scenario_id=scenario.id,
        trace_id=execution.trace_id,
        process_score=None,
        result_score=None,
        overall_passed=False,
        details_json=json.dumps({"error": "LLM model not found"}, ensure_ascii=False),
        status='failed',
        error_message="LLM model not found",
    )
    await comparison_repo.create(self.session, comparison_result)
    return comparison_result

comparison_service = ComparisonService(
    llm_service.get_client(llm_model),
    comparison_repo,
)
comparison_result = await comparison_service.detailed_compare(
    scenario=scenario,
    execution=execution,
    trace_spans=spans,
    llm_model=llm_model,
)
await comparison_repo.create(self.session, comparison_result)
```

**修正说明：** 为了与当前 `ComparisonRepository.create(session, comparison)` 接口保持一致，重构后的 `detailed_compare` 仍然只负责构造并返回 `ComparisonResultEntity`；真正的持久化继续由 `ExecutionService` 和 `recompare` 调用方在外部完成。

- [ ] **Step 3: Verify method signature matches**

```python
# ComparisonService method signature now is:
async def detailed_compare(
    self,
    scenario: Scenario,
    execution: ExecutionJob,
    trace_spans: List[Span],
    llm_model: LLMModel,
) -> ComparisonResultEntity:
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/execution_service.py
git commit -m "fix: update execution_service to pass llm_model to detailed_compare and persist comparison externally"
```

---

### Task 12: 更新set-baseline API不再提取baseline_tool_calls

**Files:**
- Modify: `backend/app/api/scenario.py`

- [ ] **Step 1: Read current `set_baseline` endpoint**

- [ ] **Step 2: Remove code that extracts and updates `baseline_tool_calls`**

Before (remove these lines):
```python
# 提取工具调用基线
tool_calls = extract_tool_calls_from_trace(trace)
scenario.baseline_tool_calls = json.dumps(tool_calls, ensure_ascii=False)
```

After (comment out or delete):
```python
# 不再提取工具调用基线 (LLM-Only refactor)
# 保留原有字段值不变，新set-baseline不修改该字段
# tool_calls = extract_tool_calls_from_trace(trace)
# scenario.baseline_tool_calls = json.dumps(tool_calls, ensure_ascii=False)
```

- [ ] **Step 3: Verify `baseline_result` extraction remains unchanged**

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/scenario.py
git commit -m "feat: update set-baseline to not extract baseline_tool_calls"
```

---

### Task 13: 更新前端TypeScript类型定义

**Files:**
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Update `LLMModel` interface**

```typescript
export interface LLMModel {
  id: string
  name: string
  provider: string
  model_id: string
  base_url?: string
  temperature: number
  max_tokens: number
  comparison_prompt?: string  // 新增：比对prompt模板
  is_default: boolean
  created_at: string
  updated_at: string
}
```

- [ ] **Step 2: Update `LLMCreate` interface**

```typescript
export interface LLMCreate {
  name: string
  provider: string
  model_id: string
  base_url?: string
  api_key: string
  temperature?: number
  max_tokens?: number
  comparison_prompt?: string  // 新增
}
```

- [ ] **Step 3: Add new interfaces for comparison result after `SingleLLMComparison`**

```typescript
export interface LLMCountCheck {
  expected_min: number
  expected_max: number
  actual_count: number
  passed: boolean
}

export interface FinalOutputComparison {
  baseline_output: string
  actual_output: string
  consistent: boolean
  reason: string
}
```

- [ ] **Step 4: Update `DetailedComparisonResult` interface**

```typescript
export interface DetailedComparisonResult {
  id: string
  execution_id: string
  scenario_id: string
  trace_id?: string
  process_score: number | null  // 0-100, always null in new scheme
  result_score: number | null  // 0-100, always null in new scheme
  overall_passed: boolean
  tool_comparisons: SingleToolComparison[]  // always empty array in new scheme
  llm_comparison: SingleLLMComparison | null  // always null in new scheme
  llm_count_check?: LLMCountCheck | null  // 新增
  final_output_comparison?: FinalOutputComparison | null  // 新增
  status: string
  error_message: string | null
  retry_count: number
  created_at: string
  updated_at: string
  completed_at?: string
}
```

- [ ] **Step 5: Update `Scenario` interface**

```typescript
export interface Scenario {
  id: string
  agent_id: string
  agent_name?: string
  name: string
  description?: string
  prompt: string
  baseline_result?: string
  llm_count_min: number  // 新增
  llm_count_max: number  // 新增
  compare_enabled: boolean  // 保留
  created_at: string
  updated_at: string
  // 以下字段已移除：不再返回给前端
  // baseline_tool_calls?: string
  // compare_result: boolean
  // compare_process: boolean
  // process_threshold: number
  // result_threshold: number
  // tool_count_tolerance: number
  // enable_llm_verification: boolean
}
```

- [ ] **Step 6: Update `ScenarioCreate` interface**

```typescript
export interface ScenarioCreate {
  agent_id: string
  name: string
  description?: string
  prompt: string
  baseline_result?: string
  llm_count_min?: number  // 新增，默认0
  llm_count_max?: number  // 新增，默认999
  compare_enabled?: boolean  // 保留
  // 已移除废弃字段：
  // baseline_tool_calls?: string
  // compare_result: boolean
  // compare_process: boolean
  // process_threshold?: number
  // result_threshold?: number
  // tool_count_tolerance: number
  // enable_llm_verification?: boolean
}
```

- [ ] **Step 7: Update `CreateExecutionRequest` - `llm_model_id` is required**

```typescript
export interface CreateExecutionRequest {
  agent_id: string
  scenario_id: string
  llm_model_id: string  // 改为必填
}
```

- [ ] **Step 8: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/types.ts
git commit -m "feat: update frontend types for LLM-Only refactor"
```

---

### Task 14: 更新ScenarioList前端表单 - 移除旧配置新增LLM范围

**Files:**
- Modify: `frontend/src/pages/ScenarioList.tsx`

- [ ] **Step 1: Update `handleCreate` default values**

Change from:

```typescript
form.setFieldsValue({
  process_threshold: 60.0,
  result_threshold: 60.0,
  tool_count_tolerance: 0,
  compare_enabled: true,
  enable_llm_verification: true,
})
```

To:

```typescript
form.setFieldsValue({
  llm_count_min: 0,
  llm_count_max: 999,
  compare_enabled: true,
})
```

- [ ] **Step 2: Update `handleEdit` setFieldsValue**

Remove setting deprecated fields, add new fields:

Remove:
```typescript
baseline_tool_calls: record.baseline_tool_calls,
process_threshold: record.process_threshold ?? 60.0,
result_threshold: record.result_threshold ?? 60.0,
tool_count_tolerance: record.tool_count_tolerance ?? 0,
enable_llm_verification: record.enable_llm_verification ?? true,
```

Add:
```typescript
llm_count_min: record.llm_count_min ?? 0,
llm_count_max: record.llm_count_max ?? 999,
```

Keep: `agent_id`, `name`, `description`, `prompt`, `baseline_result`, `compare_enabled`.

- [ ] **Step 3: Remove deprecated Form.Item from Modal**

Remove these Form.Items entirely:
- `baseline_tool_calls` (工具调用基线)
- `enable_llm_verification` (启用LLM语义验证)
- `process_threshold` (过程通过阈值)
- `result_threshold` (结果通过阈值)
- `tool_count_tolerance` (工具次数容忍度)

- [ ] **Step 4: Add new Form.Items for LLM count range after "启用自动比对"**

```tsx
<Form.Item
  label="LLM调用次数范围"
>
  <Space>
    <Form.Item
      name="llm_count_min"
      rules={[{ required: true, message: '请输入最小值' }]}
      noStyle
      initialValue={0}
    >
      <InputNumber min={0} placeholder="最小次数" style={{ width: 120 }} />
    </Form.Item>
    <span>~</span>
    <Form.Item
      name="llm_count_max"
      rules={[
        { required: true, message: '请输入最大值' },
        ({ getFieldValue }) => ({
          validator(_, value) {
            const min = getFieldValue('llm_count_min')
            if (value !== undefined && min !== undefined && value < min) {
              return Promise.reject(new Error('最大值不能小于最小值'))
            }
            return Promise.resolve()
          },
        }),
      ]}
      noStyle
      initialValue={999}
    >
      <InputNumber min={0} placeholder="最大次数" style={{ width: 120 }} />
    </Form.Item>
  </Space>
</Form.Item>
```

- [ ] **Step 5: Remove `compare_result` from Table columns**

Remove the entire "比对结果" column from the columns array.

- [ ] **Step 6: Verify compile and commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/pages/ScenarioList.tsx
git commit -m "feat: update ScenarioList form for LLM-Only refactor"
```

---

### Task 15: 更新LLMList表单新增comparison_prompt输入框

**Files:**
- Modify: `frontend/src/pages/LLMList.tsx`

- [ ] **Step 1: Read current file**

- [ ] **Step 2: Add default comparison_prompt at top of file**

```typescript
const DEFAULT_COMPARISON_PROMPT = `请判断下面【基线输出】和【实际输出】的核心语义是否一致：

基线输出:
{{baseline_result}}

实际输出:
{{actual_result}}

要求：
1. 核心语义一致（回答问题结论相同、解决同一个问题、满足相同需求）→ consistent = true
2. 核心语义不一致 → consistent = false
3. 请简要说明判定原因
4. 以JSON格式输出：{"consistent": boolean, "reason": string}`;
```

- [ ] **Step 3: Update `handleCreate` default values**

Add:

```typescript
comparison_prompt: DEFAULT_COMPARISON_PROMPT,
```

- [ ] **Step 4: Update `handleEdit` to load `comparison_prompt`**

Add line:

```typescript
comparison_prompt: record.comparison_prompt,
```

- [ ] **Step 5: Add Form.Item for `comparison_prompt` after max_tokens**

```tsx
<Form.Item
  name="comparison_prompt"
  label="比对Prompt"
  rules={[{ required: true, message: '请输入比对Prompt' }]}
>
  <TextArea
    placeholder="用于比对基线输出和实际输出的prompt模板，使用 {{baseline_result}} 和 {{actual_result}} 作为占位符"
    rows={10}
  />
</Form.Item>
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LLMList.tsx
git commit -m "feat: add comparison_prompt input to LLMList form"
```

---

### Task 16: 更新ExecutionList让llm_model_id必填

**Files:**
- Modify: `frontend/src/pages/ExecutionList.tsx`

- [ ] **Step 1: Read current file**

- [ ] **Step 2: Make LLM Model selection required in create execution form**

Change the Form.Item to add required rule:

```tsx
<Form.Item
  name="llm_model_id"
  label="LLM比对模型"
  rules={[{ required: true, message: '请选择LLM模型才能进行比对' }]}
>
  <Select placeholder="选择LLM模型用于比对">
    {llmModels.map(m => (
      <Select.Option key={m.id} value={m.id}>
        {m.name}
      </Select.Option>
    ))}
  </Select>
</Form.Item>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ExecutionList.tsx
git commit -m "feat: make llm_model_id required in execution create form"
```

---

### Task 17: 更新ExecutionDetail适配新比对结果展示

**Files:**
- Modify: `frontend/src/pages/ExecutionDetail.tsx`

- [ ] **Step 1: Read current file**

- [ ] **Step 2: Remove old sections that are no longer used:**
- Remove "过程分数" card
- Remove "结果分数" card
- Remove "工具比对" collapse panel
- Remove "LLM比对" collapse panel (old format)

- [ ] **Step 3: Add new sections for LLM-Only result:**

Add LLM Count Check section:

```tsx
{comparisonResult.llm_count_check && (
  <Card
    title={`LLM调用次数检查 ${comparisonResult.llm_count_check.passed ? '✅ 通过' : '❌ 不通过'}`}
    size="small"
    style={{ marginBottom: 16 }}
  >
    <p>期望范围: {comparisonResult.llm_count_check.expected_min} ~ {comparisonResult.llm_count_check.expected_max}</p>
    <p>实际次数: {comparisonResult.llm_count_check.actual_count}</p>
  </Card>
)}
```

Add Final Output Comparison section:

```tsx
{comparisonResult.final_output_comparison && (
  <Card
    title={`最终输出比对 ${comparisonResult.final_output_comparison.consistent ? '✅ 一致' : '❌ 不一致'}`}
    size="small"
    style={{ marginBottom: 16 }}
  >
    <Descriptions bordered column={1}>
      <Descriptions.Item label="基线输出">
        <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
          {comparisonResult.final_output_comparison.baseline_output}
        </pre>
      </Descriptions.Item>
      <Descriptions.Item label="实际输出">
        <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
          {comparisonResult.final_output_comparison.actual_output}
        </pre>
      </Descriptions.Item>
      <Descriptions.Item label="判定原因">
        {comparisonResult.final_output_comparison.reason}
      </Descriptions.Item>
    </Descriptions>
  </Card>
)}
```

- [ ] **Step 4: Keep overall result summary at top**

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ExecutionDetail.tsx
git commit -m "feat: update ExecutionDetail to display new LLM-Only comparison result"
```

---

## 完成检查清单

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
- [ ] 移除"不选LLM退化为算法相似度"选项，创建执行必须选LLM
- [ ] 比对结果details_json使用新结构存储
- [ ] API返回正确包含新字段，前端能正确展示
- [ ] 向后兼容保留旧数据

---

## Self-Review 检查

1. **Spec coverage**: ✓ 覆盖了设计文档中所有需求，每个变更都有对应任务
2. **No placeholders**: ✓ 所有步骤都有具体代码/命令，没有TBD
3. **Type consistency**: ✓ 前后端字段名称一致（llm_count_min, llm_count_max, comparison_prompt）
4. **向后兼容**: ✓ 所有旧数据库字段保留，不删除，新代码不读写

**Total tasks: 17**

Plan complete.
