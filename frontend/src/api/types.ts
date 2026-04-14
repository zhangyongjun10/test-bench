export interface Response<T> {
  code: number
  message: string
  data: T
}

export interface Agent {
  id: string
  name: string
  description?: string
  base_url: string
  user_session?: string
  created_at: string
  updated_at: string
}

export interface AgentCreate {
  name: string
  description?: string
  base_url: string
  api_key: string
  user_session?: string
}

export interface AgentUpdate extends Partial<AgentCreate> {}

export interface LLMModel {
  id: string
  name: string
  provider: string
  model_id: string
  base_url?: string
  temperature: number
  max_tokens: number
  comparison_prompt?: string
  created_at: string
  updated_at: string
}

export interface LLMCreate {
  name: string
  provider: string
  model_id: string
  base_url?: string
  api_key: string
  temperature?: number
  max_tokens?: number
  comparison_prompt?: string
}

export interface LLMUpdate extends Partial<LLMCreate> {}

export interface Scenario {
  id: string
  agent_id: string
  agent_name?: string
  name: string
  description?: string
  prompt: string
  baseline_result?: string
  llm_count_min: number
  llm_count_max: number
  compare_enabled: boolean
  created_at: string
  updated_at: string
}

export interface ScenarioCreate {
  agent_id: string
  name: string
  description?: string
  prompt: string
  baseline_result?: string
  llm_count_min?: number
  llm_count_max?: number
  compare_enabled?: boolean
}

export interface ScenarioUpdate extends Partial<ScenarioCreate> {}

export interface ExecutionJob {
  id: string
  agent_id: string
  scenario_id: string
  llm_model_id?: string
  user_session?: string
  run_source?: string
  parent_execution_id?: string | null
  request_snapshot_json?: string | null
  trace_id?: string
  status: string
  comparison_score?: number
  comparison_passed?: boolean
  error_message?: string
  original_request?: string
  original_response?: string
  started_at?: string
  completed_at?: string
  created_at: string
  updated_at: string
}

export interface CreateExecutionRequest {
  agent_id: string
  scenario_id: string
  llm_model_id?: string
}

export interface CreateConcurrentExecutionRequest {
  input: string
  concurrency: number
  model: string
  scenario_id?: string
  concurrent_mode?: 'single_instance' | 'multi_instance'
  llm_model_id?: string
  agent_id?: string
}

export interface Span {
  span_id: string
  span_type: string
  name: string
  provider?: string | null
  input_tokens?: number
  output_tokens?: number
  input?: string
  output?: string
  duration_ms: number
  ttft_ms?: number
  tpot_ms?: number
}

export interface ExecutionTrace {
  trace_id: string
  spans: Span[]
}

export interface ExecutionListData {
  total: number
  items: ExecutionJob[]
}

export interface ClickHouseConfig {
  endpoint: string
  database: string
  username?: string
  source_type: string
}

export interface ClickHouseConfigUpdate {
  endpoint: string
  database: string
  username?: string
  password?: string
  source_type: string
}

export interface TestResponse {
  success: boolean
  message: string
}

export interface SingleToolComparison {
  tool_name: string
  baseline_input: string
  baseline_output: string
  actual_input: string
  actual_output: string
  similarity: number
  score: number
  consistent: boolean
  reason: string
  matched: boolean
}

export interface SingleLLMComparison {
  baseline_output: string
  actual_output: string
  similarity: number
  score: number
  consistent: boolean
  reason: string
}

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
  algorithm_similarity?: number | null
  verification_mode?: string | null
}

export interface DetailedComparisonResult {
  id: string
  execution_id: string
  scenario_id: string
  llm_model_id?: string | null
  replay_task_id?: string | null
  source_type?: string | null
  baseline_source?: string | null
  trace_id: string
  process_score: number | null
  result_score: number | null
  overall_passed: boolean | null
  tool_comparisons: SingleToolComparison[]
  llm_comparison: SingleLLMComparison | null
  llm_count_check: LLMCountCheck | null
  final_output_comparison: FinalOutputComparison | null
  status: string
  error_message: string | null
  retry_count: number
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface RecompareResponse {
  success: boolean
  message: string
}

export type ReplayBaselineSource = 'scenario_baseline' | 'reference_execution'

export interface CreateReplayRequest {
  original_execution_id: string
  baseline_source: ReplayBaselineSource
  llm_model_id: string
  idempotency_key: string
}

export interface ReplayTask {
  id: string
  original_execution_id: string
  replay_execution_id: string
  scenario_id: string
  agent_id: string
  baseline_source: ReplayBaselineSource
  baseline_snapshot_json: string
  idempotency_key: string
  llm_model_id: string
  status: string
  comparison_id?: string | null
  overall_passed?: boolean | null
  error_message?: string | null
  created_at: string
  updated_at: string
  started_at?: string | null
  completed_at?: string | null
}

export interface ReplayDetail {
  replay_task: ReplayTask
  original_execution: ExecutionJob
  replay_execution: ExecutionJob
  comparison?: DetailedComparisonResult | null
}

export interface ReplayHistoryData {
  total: number
  items: ReplayTask[]
}

export interface SetBaselineRequest {
  scenario_id: string
  execution_id: string
}
