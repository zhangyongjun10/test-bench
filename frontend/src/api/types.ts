// 后端统一响应结构，所有业务接口都通过 data 承载实际返回内容。
export interface Response<T> {
  code: number
  message: string
  data: T
}

// Agent 列表与详情结构；Agent 本身不再暴露运行态 Session。
export interface Agent {
  id: string
  name: string
  description?: string
  base_url: string
  created_at: string
  updated_at: string
}

// 创建 Agent 时只提交连接配置，避免把运行态会话耦合进静态配置。
export interface AgentCreate {
  name: string
  description?: string
  base_url: string
  api_key: string
}

// 更新 Agent 允许局部字段修改，沿用创建请求的字段集合。
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
  agent_ids: string[]
  agent_names: string[]
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

// 创建 Case 时允许单 Agent 创建，也允许前端多选 Agent 后批量创建同内容 Case。
export interface ScenarioCreate {
  agent_ids: string[]
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
  replay_count?: number
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

// 并发执行请求只描述输入与并发参数，具体执行策略由后端统一控制。
export interface CreateConcurrentExecutionRequest {
  input: string
  concurrency: number
  scenario_id?: string
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
  output_throughput_tps?: number
  total_throughput_tps?: number
}

export interface ExecutionTrace {
  trace_id: string
  total_duration_ms?: number
  avg_ttft_ms?: number | null
  avg_tpot_ms?: number | null
  output_throughput_tps?: number | null
  total_throughput_tps?: number | null
  total_input_tokens?: number
  total_output_tokens?: number
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

// 运行时配置来自后端系统接口，避免前端硬编码关键阈值。
export interface RuntimeConfig {
  concurrent_execution_max_concurrency: number
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
