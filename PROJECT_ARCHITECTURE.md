# TestBench 项目架构详解

## 项目概述

**TestBench** 是一个 AI Agent 标准化验证测试平台，用于对不同 Agent 进行自动化验证和性能指标采集。支持从 Opik/Langfuse 等追踪系统拉取 Trace 数据，并用 LLM 进行输出比对评分。

**技术栈：**
- 后端：Python + FastAPI + SQLAlchemy + PostgreSQL + Alembic
- 前端：React + TypeScript + Vite + Ant Design
- 数据分析：ClickHouse（用于 Opik/Langfuse 数据源）

---

## 整体目录结构

```
test-bench/
├── backend/                 # Python FastAPI 后端服务
│   └── app/                # 应用主代码
│       ├── api/            # API 路由层（接口定义）
│       ├── clients/        # 外部客户端（LLM、ClickHouse、Agent）
│       ├── core/           # 核心工具模块（日志、加密、数据库、指标）
│       ├── domain/         # 领域层（实体和仓储接口）
│       │   ├── entities/   # 数据实体定义
│       │   └── repositories/ # 仓储实现（数据访问）
│       ├── middleware/     # 中间件（错误处理、日志）
│       ├── models/         # Pydantic 请求/响应模型
│       ├── services/       # 业务逻辑层
│       └── main.py         # 应用入口
│   ├── migrations/         # Alembic 数据库迁移脚本
│   ├── tests/              # 单元测试
│   ├── requirements.txt   # Python 依赖
│   └── .env.example        # 环境变量示例
├── frontend/               # React TypeScript 前端
│   └── src/
│       ├── api/            # API 客户端（调用后端接口）
│       ├── pages/          # 页面组件
│       ├── App.tsx         # 根组件
│       ├── main.tsx        # 入口文件
│       └── router.tsx      # 路由配置
├── config/                 # 配置文件目录
├── docs/                   # 文档目录
│   └── adrs/               # 架构决策记录
├── .gitignore
├── README.md               # 项目说明（快速开始）
├── PROJECT_ARCHITECTURE.md # 本文档 - 架构详解
└── docker-compose.yml      # Docker Compose 配置
```

---

## 后端目录详解

### `backend/app/api/` - API 路由层

| 文件 | 作用 |
|------|------|
| [`agent.py`](backend/app/api/agent.py) | Agent 管理接口：增删改查 Agent 配置 |
| [`llm.py`](backend/app/api/llm.py) | LLM 模型管理接口：增删改查 + **测试连接**端点 `/api/v1/llm/{id}/test` |
| [`scenario.py`](backend/app/api/scenario.py) | 测试场景管理接口：增删改查测试场景 |
| [`execution.py`](backend/app/api/execution.py) | 测试执行记录接口：列表查询、详情查询 |
| [`system.py`](backend/app/api/system.py) | 系统配置管理接口 |
| [`__init__.py`](backend/app/api/__init__.py) | API 路由聚合，注册到 FastAPI |

**特点**：遵循 RESTful 设计，只负责请求路由、参数校验、返回响应，不包含业务逻辑。业务逻辑委托给 `services` 层处理。

---

### `backend/app/clients/` - 外部客户端

这个目录封装对外部服务的调用：

| 文件 | 作用 |
|------|------|
| [`llm_client.py`](backend/app/clients/llm_client.py) | **LLM 客户端抽象**。`LLMClient` 抽象基类 + `OpenAICompatibleLLMClient` 实现。支持所有兼容 OpenAI API 格式的服务（OpenAI、Anthropic、智谱 GLM、通义千问、本地部署等）。|
| [`clickhouse_client.py`](backend/app/clients/clickhouse_client.py) | ClickHouse 客户端，用于从 Opik/Langfuse 拉取 Trace 数据和指标。|
| [`http_agent_client.py`](backend/app/clients/http_agent_client.py) | HTTP Agent 客户端，用于通过 HTTP 调用被测 Agent。|

**架构设计**：
- `OpenAICompatibleLLMClient`：使用标准 OpenAI 格式调用任何 LLM，遵循标准端点约定：
  - 测试连接：`GET {base_url}/models`
  - 推理调用：`POST {base_url}/chat/completions`

---

### `backend/app/core/` - 核心工具模块

| 文件 | 作用 |
|------|------|
| [`db.py`](backend/app/core/db.py) | SQLAlchemy 数据库连接配置，会话管理，基类实体定义。|
| [`encryption.py`](backend/app/core/encryption.py) | **加密服务**。API Key 等敏感信息存储到数据库时需要加密，使用 AES 加密。|
| [`logger.py`](backend/app/core/logger.py) | 日志配置，结构化日志输出。|
| [`metrics.py`](backend/app/core/metrics.py) | 指标计算工具，定义支持的指标类型。|
| [`__init__.py`](backend/app/core/__init__.py) | 导出核心模块。|

---

### `backend/app/domain/` - 领域层

遵循领域驱动设计（DDD）分层，包含实体和仓储：

#### `domain/entities/` - 数据实体定义

| 文件 | 作用 |
|------|------|
| [`agent.py`](backend/app/domain/entities/agent.py) | Agent 实体：被测 Agent 的配置信息（名称、端点、API Key 等）|
| [`llm.py`](backend/app/domain/entities/llm.py) | LLM 实体：比对用 LLM 的配置信息（base_url、模型 ID、加密的 API Key 等）|
| [`scenario.py`](backend/app/domain/entities/scenario.py) | 测试场景实体：定义一个测试场景，包含描述、预期输出等。|
| [`execution.py`](backend/app/domain/entities/execution.py) | 执行记录实体：保存每次测试执行的结果。|
| [`system.py`](backend/app/domain/entities/system.py) | 系统配置实体：存储 ClickHouse 连接配置等。|
| [`trace.py`](backend/app/domain/entities/trace.py) | Trace 实体：Opik/Langfuse 追踪数据。|

这些是 SQLAlchemy ORM 实体，映射到数据库表。

#### `domain/repositories/` - 仓储实现（数据访问层）

| 文件 | 作用 |
|------|------|
| [`agent_repo.py`](backend/app/domain/repositories/agent_repo.py) | Agent 数据访问，CRUD 操作。|
| [`llm_repo.py`](backend/app/domain/repositories/llm_repo.py) | LLM 模型数据访问。|
| [`scenario_repo.py`](backend/app/domain/repositories/scenario_repo.py) | 测试场景数据访问。|
| [`execution_repo.py`](backend/app/domain/repositories/execution_repo.py) | 执行记录数据访问，支持分页查询。|

**职责**：封装所有数据库查询操作，业务层通过仓储访问数据，解耦业务逻辑与数据访问细节。

---

### `backend/app/middleware/` - 中间件

| 文件 | 作用 |
|------|------|
| [`error_handler.py`](backend/app/middleware/error_handler.py) | 全局错误处理中间件，统一错误响应格式。|
| [`logging.py`](backend/app/middleware/logging.py) | 请求日志中间件，记录每个请求的处理时间、状态码。|

---

### `backend/app/models/` - Pydantic 请求/响应模型

| 文件 | 作用 |
|------|------|
| [`agent.py`](backend/app/models/agent.py) | Agent 创建/更新请求、响应模型。|
| [`llm.py`](backend/app/models/llm.py) | LLM 创建/更新请求、响应模型，**测试连接响应模型 `LLMTestResponse`**。|
| [`scenario.py`](backend/app/models/scenario.py) | 场景 CRUD 请求响应模型。|
| [`execution.py`](backend/app/models/execution.py) | 执行查询、详情响应模型。|
| [`system.py`](backend/app/models/system.py) | 系统配置请求响应模型。|
| [`common.py`](backend/app/models/common.py) | 通用分页响应、统一 API 响应格式。|

这一层是 FastAPI 请求验证使用，所有入参出参都通过 Pydantic 校验。

---

### `backend/app/services/` - 业务逻辑层

所有核心业务逻辑都在这里：

| 文件 | 作用 |
|------|------|
| [`agent_service.py`](backend/app/services/agent_service.py) | Agent 业务逻辑：创建、更新、删除、测试连接。|
| [`llm_service.py`](backend/app/services/llm_service) | LLM 业务逻辑：创建、更新、删除、解密 API Key、获取客户端实例。|
| [`scenario_service.py`](backend/app/services/scenario_service.py) | 场景业务逻辑：CRUD。|
| [`execution_service.py`](backend/app/services/execution_service.py) | **核心执行逻辑**：触发一次测试执行，调用 Agent，获取输出，调用 LLM 比对，保存结果。|
| [`comparison.py`](backend/app/services/comparison.py) | **比对服务**：构造比对 prompt，调用 LLM 进行输出比对。|
| [`trace_fetcher.py`](backend/app/services/trace_fetcher.py) | **Trace 拉取服务**：从 ClickHouse 拉取 Opik/Langfuse Trace 数据。|
| [`metric_extractor.py`](backend/app/services/metric_extractor.py) | **指标提取服务**：从 Trace 中提取指标（输入 tokens、输出 tokens、延迟等）。|

**调用关系示例（一次测试执行）：**
```
execution_service.start_execution
  ├─ http_agent_client.invoke (调用被测 Agent)
  ├─ comparison.compare (调用 LLM 比对预期输出)
  │   └─ llm_client.compare
  ├─ trace_fetcher.fetch_latest_trace (从 ClickHouse 拉取 Trace)
  │   └─ clickhouse_client.query
  ├─ metric_extractor.extract (从 Trace 提取指标)
  └─ execution_repo.save (保存执行结果)
```

---

### `backend/app/` 根文件

| 文件 | 作用 |
|------|------|
| [`main.py`](backend/app/main.py) | FastAPI 应用入口，创建应用实例，注册路由，挂载中间件。|
| [`config.py`](backend/app/config.py) | 配置加载，从环境变量读取配置。|

---

### `backend/migrations/` - 数据库迁移

使用 Alembic 进行数据库版本管理。

| 目录 | 作用 |
|------|------|
| `versions/` | 存放各个版本的迁移脚本。|
| `env.py` | Alembic 环境配置。|

---

### `backend/tests/` - 单元测试

| 文件 | 作用 |
|------|------|
| [`test_encryption.py`](backend/tests/test_encryption.py) | 加密服务测试。|
| [`test_metric_extractor.py`](backend/tests/test_metric_extractor.py) | 指标提取测试。|

---

## 前端目录详解

### `frontend/src/api/` - API 客户端

| 文件 | 作用 |
|------|------|
| [`client.ts`](frontend/src/api/client.ts) | 封装 axios 实例，导出所有 API 方法（`agentApi`, `llmApi`, `scenarioApi`, `executionApi`, `systemApi`）。|
| [`types.ts`](frontend/src/api/types.ts) | TypeScript 类型定义，对应后端 Pydantic 模型。|

---

### `frontend/src/pages/` - 页面组件

| 文件 | 作用 |
|------|------|
| [`AgentList.tsx`](frontend/src/pages/AgentList.tsx) | Agent 配置管理列表页面。|
| [`LLMList.tsx`](frontend/src/pages/LLMList.tsx) | **LLM 模型管理列表页面**，在这里添加/编辑/测试 LLM 连接（包括 GLM-4.7）。|
| [`ScenarioList.tsx`](frontend/src/pages/ScenarioList.tsx) | 测试场景列表页面。|
| [`ExecutionList.tsx`](frontend/src/pages/ExecutionList.tsx) | 执行记录列表页面。|
| [`ExecutionDetail.tsx`](frontend/src/pages/ExecutionDetail.tsx) | **执行详情页面**，展示比对结果、提取的指标、Trace 信息。|
| [`SystemConfig.tsx`](frontend/src/pages/SystemConfig.tsx) | 系统配置页面（ClickHouse 连接配置）。|

---

### `frontend/src/` 根文件

| 文件 | 作用 |
|------|------|
| [`App.tsx`](frontend/src/App.tsx) | 根组件，配置布局。|
| [`main.tsx`](frontend/src/main.tsx) | 应用入口，挂载到 DOM。|
| [`router.tsx`](frontend/src/router.tsx) | 路由配置，定义各个页面对应的路由。|
| [`index.css`](frontend/src/index.css) | 全局样式。|

---

## 分层架构总结

项目清晰地遵循**四层架构**：

```
┌─────────────────────────────────────────────────┐
│                    API 路由层 (api/)             │
│  职责：路由转发、参数校验                         │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│                  业务逻辑层 (services/)          │
│  职责：实现核心业务流程，协调各层                 │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│               领域层 (domain/)                   │
│  ├─ entities: 数据实体定义 (ORM)                │
│  └─ repositories: 数据访问层                    │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│               外部客户端 (clients/)              │
│  职责：封装对外部服务（LLM、ClickHouse、Agent）  │
└─────────────────────────────────────────────────┘
```

**设计优势：**
- 每层职责清晰，低耦合
- 易于测试和维护
- 新增 LLM 提供商只需要实现对应的 client，不需要修改核心逻辑
- 遵循 OpenAI 兼容标准，支持绝大部分主流模型

---

## 数据流向

### LLM 测试连接流程

```
前端点击"测试"
  ↓
POST /api/v1/llm/{id}/test → api/llm.py
  ↓
llm_service.test_connection → 解密 API Key
  ↓
llm_client.test_connection → GET {base_url}/models
  ↓
 返回 (success: true/false, message)
  ↓
 前端显示结果
```

### 测试执行流程

```
用户点击"执行"
  ↓
POST /api/v1/execution/start → api/execution.py
  ↓
execution_service.start_execution
  ├─ 1. 调用被测 Agent → http_agent_client.invoke
  ├─ 2. LLM 比对 → comparison.compare → llm_client.compare
  ├─ 3. 拉取 Trace → trace_fetcher.fetch → clickhouse_client.query
  ├─ 4. 提取指标 → metric_extractor.extract
  └─ 保存结果 → execution_repo.create
  ↓
返回执行结果给前端
  ↓
前端跳转到执行详情页展示
```

---

## 关键配置说明

| 配置项 | 位置 | 说明 |
|--------|------|------|
| 数据库连接 | `backend/.env` | PostgreSQL 连接信息 |
| 加密密钥 | `backend/.env` | `ENCRYPTION_KEY`，用于加密存储 API Key |
| ClickHouse | 前端系统配置页 | Opik/Langfuse 连接配置 |
| LLM 模型 | 前端 LLM 管理页 | 配置 base_url、api_key、model_id |
| Agent | 前端 Agent 管理页 | 配置被测 Agent 端点 |
| 测试场景 | 前端场景管理页 | 定义测试用例、问题描述、预期输出 |

---

## 部署相关

| 文件 | 作用 |
|------|------|
| [`docker-compose.yml`](docker-compose.yml) | 一键启动 PostgreSQL、前端、后端 |
| `backend/Dockerfile` | 后端 Docker 镜像构建 |
| `frontend/Dockerfile` | 前端 Docker 镜像构建 |

---

## 架构决策记录

相关架构决策记录在 `docs/adrs/` 目录下。

---

## 快速参考

你关心的核心代码位置：

| 功能 | 文件位置 |
|------|---------|
| GLM-4.7 连接测试 | [`backend/app/clients/llm_client.py:51-63`](backend/app/clients/llm_client.py#L51-L63) |
| LLM 实际调用 | [`backend/app/clients/llm_client.py:65-118`](backend/app/clients/llm_client.py#L65-L118) |
| 测试执行入口 | [`backend/app/services/execution_service.py`](backend/app/services/execution_service.py) |
| LLM 比对逻辑 | [`backend/app/services/comparison.py`](backend/app/services/comparison.py) |
| 前端 LLM 管理页 | [`frontend/src/pages/LLMList.tsx`](frontend/src/pages/LLMList.tsx) |
| 后端 API 入口 | [`backend/app/main.py`](backend/app/main.py) |
