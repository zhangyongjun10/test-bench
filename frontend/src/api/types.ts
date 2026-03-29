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
}

export interface LLMUpdate extends Partial<LLMCreate> {}

export interface Scenario {
  id: string
  agent_id: string
  agent_name?: string
  name: string
  description?: string
  prompt: string
  baseline_tool_calls?: string  // JSON string
  baseline_result?: string
  compare_result: boolean
  compare_process: boolean
  process_threshold: number  // 0-100
  result_threshold: number   // 0-100
  tool_count_tolerance: number
  compare_enabled: boolean
  enable_llm_verification: boolean
  created_at: string
  updated_at: string
}

export interface ScenarioCreate {
  agent_id: string
  name: string
  description?: string
  prompt: string
  baseline_tool_calls?: string
  baseline_result?: string
  compare_result: boolean
  compare_process: boolean
  process_threshold?: number
  result_threshold?: number
  tool_count_tolerance?: number
  compare_enabled?: boolean
  enable_llm_verification?: boolean
}

export interface ScenarioUpdate extends Partial<ScenarioCreate> {}

export interface ExecutionJob {
  id: string
  agent_id: string
  scenario_id: string
  llm_model_id?: string
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

export interface Span {
  span_id: string
  span_type: string
  name: string
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

// 比对结果相关类型
export interface SingleToolComparison {
  tool_name: string
  baseline_input: string
  baseline_output: string
  actual_input: string
  actual_output: string
  similarity: number  // 0-1
  score: number      // 0-1
  consistent: boolean
  reason: string
  matched: boolean
}

export interface SingleLLMComparison {
  baseline_output: string
  actual_output: string
  similarity: number  // 0-1
  score: number      // 0-1
  consistent: boolean
  reason: string
}

export interface DetailedComparisonResult {
  id: string
  execution_id: string
  scenario_id: string
  trace_id: string
  process_score: number | null  // 0-100
  result_score: number | null  // 0-100
  overall_passed: boolean
  tool_comparisons: SingleToolComparison[]
  llm_comparison: SingleLLMComparison | null
  status: string  // pending/processing/completed/failed
  error_message: string | null
  retry_count: number
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface SetBaselineRequest {
  scenario_id: string
  execution_id: string
}
