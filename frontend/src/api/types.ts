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
  baseline_result?: string
  compare_result: boolean
  compare_process: boolean
  created_at: string
  updated_at: string
}

export interface ScenarioCreate {
  agent_id: string
  name: string
  description?: string
  prompt: string
  baseline_result?: string
  compare_result?: boolean
  compare_process?: boolean
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
