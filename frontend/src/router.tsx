import { createRoutesFromElements, Route } from 'react-router-dom'
import App from './App'
import AgentList from './pages/AgentList'
import LLMList from './pages/LLMList'
import ScenarioList from './pages/ScenarioList'
import ExecutionList from './pages/ExecutionList'
import ExecutionDetail from './pages/ExecutionDetail'
import SystemConfig from './pages/SystemConfig'

export const routes = createRoutesFromElements(
  <Route path="/" element={<App />}>
    <Route index element={<ExecutionList />} />
    <Route path="agents" element={<AgentList />} />
    <Route path="llms" element={<LLMList />} />
    <Route path="scenarios" element={<ScenarioList />} />
    <Route path="executions" element={<ExecutionList />} />
    <Route path="execution/:id" element={<ExecutionDetail />} />
    <Route path="system" element={<SystemConfig />} />
  </Route>
)
