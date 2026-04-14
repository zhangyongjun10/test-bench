import axios from 'axios'

import type {
  Agent,
  AgentCreate,
  AgentUpdate,
  ClickHouseConfig,
  ClickHouseConfigUpdate,
  CreateConcurrentExecutionRequest,
  CreateExecutionRequest,
  CreateReplayRequest,
  DetailedComparisonResult,
  ExecutionJob,
  ExecutionListData,
  ExecutionTrace,
  LLMCreate,
  LLMModel,
  LLMUpdate,
  RecompareResponse,
  ReplayDetail,
  ReplayHistoryData,
  ReplayTask,
  Response,
  Scenario,
  ScenarioCreate,
  ScenarioUpdate,
  TestResponse,
} from './types'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

request.interceptors.response.use(
  response => {
    const data = response.data as Response<unknown>
    if (data.code !== 0) {
      throw new Error(data.message)
    }
    return response.data
  },
  error => Promise.reject(error),
)

const asResponse = <T>(promise: Promise<unknown>) => promise as Promise<Response<T>>

export const agentApi = {
  list: (keyword?: string) => asResponse<Agent[]>(request.get('/v1/agent', { params: { keyword } })),
  create: (data: AgentCreate) => asResponse<Agent>(request.post('/v1/agent', data)),
  update: (id: string, data: AgentUpdate) => asResponse<Agent>(request.put(`/v1/agent/${id}`, data)),
  delete: (id: string) => asResponse<null>(request.delete(`/v1/agent/${id}`)),
  get: (id: string) => asResponse<Agent>(request.get(`/v1/agent/${id}`)),
  test: (id: string) => asResponse<TestResponse>(request.post(`/v1/agent/${id}/test`)),
}

export const llmApi = {
  list: (keyword?: string) => asResponse<LLMModel[]>(request.get('/v1/llm', { params: { keyword } })),
  create: (data: LLMCreate) => asResponse<LLMModel>(request.post('/v1/llm', data)),
  update: (id: string, data: LLMUpdate) => asResponse<LLMModel>(request.put(`/v1/llm/${id}`, data)),
  delete: (id: string) => asResponse<null>(request.delete(`/v1/llm/${id}`)),
  get: (id: string) => asResponse<LLMModel>(request.get(`/v1/llm/${id}`)),
  test: (id: string) => asResponse<TestResponse>(request.post(`/v1/llm/${id}/test`)),
}

export const scenarioApi = {
  list: (agentId?: string, keyword?: string) => {
    const params: { keyword?: string; agent_id?: string } = { keyword }
    if (agentId) {
      params.agent_id = agentId
    }
    return asResponse<Scenario[]>(request.get('/v1/scenario', { params }))
  },
  create: (data: ScenarioCreate) => asResponse<Scenario>(request.post('/v1/scenario', data)),
  update: (id: string, data: ScenarioUpdate) => asResponse<Scenario>(request.put(`/v1/scenario/${id}`, data)),
  delete: (id: string) => asResponse<null>(request.delete(`/v1/scenario/${id}`)),
  get: (id: string) => asResponse<Scenario>(request.get(`/v1/scenario/${id}`)),
}

export const executionApi = {
  create: (data: CreateExecutionRequest) => asResponse<string>(request.post('/v1/execution', data)),
  createConcurrent: (data: CreateConcurrentExecutionRequest) =>
    asResponse<{ batch_id: string; message: string }>(request.post('/v1/execution/concurrent', data)),
  list: (agentId?: string, scenarioId?: string, limit?: number, offset?: number) =>
    asResponse<ExecutionListData>(
      request.get('/v1/execution', {
        params: { agent_id: agentId, scenario_id: scenarioId, limit, offset },
      }),
    ),
  get: (id: string) => asResponse<ExecutionJob>(request.get(`/v1/execution/${id}`)),
  getTrace: (id: string) => asResponse<ExecutionTrace>(request.get(`/v1/execution/${id}/trace`)),
  getComparison: (id: string) =>
    asResponse<DetailedComparisonResult>(request.get(`/v1/execution/${id}/comparison`)),
  getComparisons: (id: string) =>
    asResponse<DetailedComparisonResult[]>(request.get(`/v1/execution/${id}/comparisons`)),
  recompare: (id: string, llm_model_id: string) =>
    asResponse<RecompareResponse>(request.post(`/v1/execution/${id}/recompare`, {}, { params: { llm_model_id } })),
  delete: (id: string) => asResponse<null>(request.delete(`/v1/execution/${id}`)),
  getReplays: (id: string, limit?: number, offset?: number) =>
    asResponse<ReplayHistoryData>(request.get(`/v1/execution/${id}/replays`, { params: { limit, offset } })),
  getConcurrentStatus: (batchId: string) =>
    asResponse<Record<string, unknown>>(request.get(`/v1/execution/concurrent/${batchId}`)),
}

export const replayApi = {
  create: (data: CreateReplayRequest) => asResponse<ReplayTask>(request.post('/v1/replay', data)),
  get: (id: string) => asResponse<ReplayDetail>(request.get(`/v1/replay/${id}`)),
  recompare: (id: string, llm_model_id: string) =>
    asResponse<RecompareResponse>(request.post(`/v1/replay/${id}/recompare`, {}, { params: { llm_model_id } })),
}

export const scenarioApiExtended = {
  ...scenarioApi,
  setBaseline: (scenarioId: string, executionId: string) =>
    asResponse<null>(request.post(`/v1/scenario/${scenarioId}/set-baseline/${executionId}`)),
}

export const systemApi = {
  getClickhouse: () => asResponse<ClickHouseConfig>(request.get('/v1/system/clickhouse')),
  updateClickhouse: (data: ClickHouseConfigUpdate) =>
    asResponse<ClickHouseConfig>(request.post('/v1/system/clickhouse', data)),
  testClickhouse: (data: ClickHouseConfigUpdate) =>
    asResponse<TestResponse>(request.post('/v1/system/clickhouse/test', data)),
}

export default request
