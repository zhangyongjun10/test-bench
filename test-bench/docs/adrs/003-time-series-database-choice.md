# ADR-003: 时序数据库选择 - Prometheus

## Context

需求需要存储性能指标（TTFT、TPOT、CPU、Memory 等），要求时序数据库。

可选方案：
1. Prometheus
2. InfluxDB
3. ClickHouse（自己存指标）

## Decision

**选择：Prometheus**

## Rationale

### 为什么不选 InfluxDB：
- Prometheus 更轻量，Docker Compose 部署更简单
- Prometheus 刚好适合我们的指标类型（aggregated metrics）
- InfluxDB 对这个项目来说功能过剩了

### 为什么不选 ClickHouse 存指标：
- 我们已经依赖 Opik/Langfuse 的 ClickHouse 读数据
- 如果自己用 ClickHouse 存指标，增加运维复杂度
- Prometheus 对指标查询、聚合更优化
- Prometheus 自带 UI 可以直接查看指标，方便运维

### Prometheus 优点：
- 标准，广泛使用
- Pull 模型，对我们来说足够了
- Go 客户端支持好（client_golang）
- 可以直接暴露指标给 Grafana 展示（如果需要）
- Docker Compose 一键启动，配置简单

## Consequences

### 优点：
- ✅ 轻量，部署简单
- ✅ 对我们的指标场景完美匹配
- ✅ 生态好，Grafana 开箱即用
- ✅ 正好满足需求，不过度设计

### 缺点：
- ⚠️ Prometheus 不是持久化数据库，长期存储Retention 要配置（我们只存 1 个月，正好符合需求）
- ⚠️ 如果未来需要非常高基数标签，可能有 Cardinality 爆炸问题（我们规模小，不担心）

## Alternatives Considered

| 方案 | 优点 | 缺点 |
|---|---|---|
| InfluxDB | 功能强 | 重，对我们过度设计 |
| ClickHouse | 灵活 | 运维复杂，我们已经只读 Opik CH |
| **Prometheus** | **正好满足** | **Retention 限制**（符合我们 1 个月需求）|
