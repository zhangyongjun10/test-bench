# ADR-002: 后端语言选择 - Python + FastAPI

## Context

需要选择后端开发语言。需求特点：
- 需要开发速度快
- 需要并发执行多个测试任务
- 需要调用 HTTP API（Agent、LLM、ClickHouse）
- 需要部署简单

可选语言：
1. Go
2. Python (FastAPI)
3. Java/Spring

## Decision

**选择：Python + FastAPI**

## Rationale

### 对比 Go：
- Python 开发速度更快，迭代更快
- FastAPI 是现代异步 Web 框架，性能好
- 对 AI/LLM 生态集成更好
- 代码更简洁，新人上手更快

### 对比 Java：
- Python 开发快，代码量少
- 部署简单，开发效率高
- 对于这个项目规模，Python 完全足够

### Python + FastAPI 符合我们需求的优点：
- FastAPI 原生支持异步，适合 I/O 密集型场景（我们大量调用 HTTP API，I/O 密集）
- 自动生成 OpenAPI 文档，前端对接方便
- 类型提示支持好，运行时检查
- ClickHouse、Prometheus、PostgreSQL 都有成熟 Python 客户端
- 数据处理（指标计算、百分位数）都有 numpy/pandas 支持

## Consequences

### 优点：
- ✅ 开发速度快，适合 MVP 快速交付
- ✅ FastAPI 异步支持，适合 I/O 密集型场景
- ✅ 自动 API 文档，对接方便
- ✅ LLM 调用和数据处理生态好
- ✅ Docker 部署也简单

### 缺点：
- ⚠️ 运行时没有静态类型检查（可以用 mypy 弥补）
- ⚠️ 性能比 Go 稍差，但我们一期并发低，完全足够
- ⚠️ Docker 镜像比 Go 大一些，可以接受

## Alternatives Considered

| 方案 | 优点 | 缺点 |
|---|---|---|
| Go | 性能好，部署小 | 开发比 Python 慢 |
| Java/Spring | 企业成熟 | 重，启动慢，开发慢 |
| **Python + FastAPI** | **开发快，生态匹配** | **性能稍差**（一期并发低，可接受）|
