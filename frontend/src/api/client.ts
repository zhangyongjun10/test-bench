import axios from 'axios'
import { Response } from './types'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 响应拦截器
request.interceptors.response.use(
  response => {
    const data = response.data as Response<any>
    if (data.code !== 0) {
      throw new Error(data.message)
    }
    return response.data
  },
  error => {
    return Promise.reject(error)
  }
)

// Agent API
export const agentApi = {
  list: (keyword?: string) => {
    return request.get<Response<Array<any>>>('/v1/agent', { params: { keyword } })
  },
  create: (data: any) => {
    return request.post<Response<any>>('/v1/agent', data)
  },
  update: (id: string, data: any) => {
    return request.put<Response<any>>(`/v1/agent/${id}`, data)
  },
  delete: (id: string) => {
    return request.delete<Response<null>>(`/v1/agent/${id}`)
  },
  get: (id: string) => {
    return request.get<Response<any>>(`/v1/agent/${id}`)
  },
  test: (id: string) => {
    return request.post<Response<any>>(`/v1/agent/${id}/test`)
  }
}

// LLM API
export const llmApi = {
  list: (keyword?: string) => {
    return request.get<Response<Array<any>>>('/v1/llm', { params: { keyword } })
  },
  create: (data: any) => {
    return request.post<Response<any>>('/v1/llm', data)
  },
  update: (id: string, data: any) => {
    return request.put<Response<any>>(`/v1/llm/${id}`, data)
  },
  delete: (id: string) => {
    return request.delete<Response<null>>(`/v1/llm/${id}`)
  },
  get: (id: string) => {
    return request.get<Response<any>>(`/v1/llm/${id}`)
  },
  test: (id: string) => {
    return request.post<Response<any>>(`/v1/llm/${id}/test`)
  }
}

// Scenario API
export const scenarioApi = {
  list: (agentId?: string, keyword?: string) => {
    const params: any = { keyword }
    if (agentId) {
      params.agent_id = agentId
    }
    return request.get<Response<Array<any>>>('/v1/scenario', { params })
  },
  create: (data: any) => {
    return request.post<Response<any>>('/v1/scenario', data)
  },
  update: (id: string, data: any) => {
    return request.put<Response<any>>(`/v1/scenario/${id}`, data)
  },
  delete: (id: string) => {
    return request.delete<Response<null>>(`/v1/scenario/${id}`)
  },
  get: (id: string) => {
    return request.get<Response<any>>(`/v1/scenario/${id}`)
  }
}

// Execution API
export const executionApi = {
  create: (data: any) => {
    return request.post<Response<string>>('/v1/execution', data)
  },
  list: (agentId?: string, scenarioId?: string, limit?: number, offset?: number) => {
    return request.get<Response<{total: number, items: Array<any>}>>('/v1/execution', {
      params: { agent_id: agentId, scenario_id: scenarioId, limit, offset }
    })
  },
  get: (id: string) => {
    return request.get<Response<any>>(`/v1/execution/${id}`)
  },
  getTrace: (id: string) => {
    return request.get<Response<any>>(`/v1/execution/${id}/trace`)
  },
  delete: (id: string) => {
    return request.delete<Response<null>>(`/v1/execution/${id}`)
  }
}

// System API
export const systemApi = {
  getClickhouse: () => {
    return request.get<Response<any>>('/v1/system/clickhouse')
  },
  updateClickhouse: (data: any) => {
    return request.post<Response<any>>('/v1/system/clickhouse', data)
  },
  testClickhouse: (data: any) => {
    return request.post<Response<any>>('/v1/system/clickhouse/test', data)
  }
}

export default request
