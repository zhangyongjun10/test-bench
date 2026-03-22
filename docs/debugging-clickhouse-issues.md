# ClickHouse 问题调试笔记

## 问题背景

Trace ID 获取错误：
- Agent 返回 `id` = `chatcmpl_xxx`，这其实是 `opik.traces.metadata.runId`
- 真实 trace_id 在 `opik.traces.id` 字段（UUID 格式）
- 需要：`Agent 返回 runId` → 查询 `opik.traces` → 得到真实 `trace_id` → 更新数据库

---

## 遇到的问题层层深入

### 问题 1：SQL 语法错误 `%s`

**错误信息：**
```
Code: 62. DB::Exception: Syntax error: failed at position 417 (%) ...
```

**第一轮修复：**
- 代码中所有 `%s` 占位符全改为 f-string 格式化 + 手动单引号转义
- **结果：** 仍然报错！

**根因发现：** (`clickhouse-driver` 的坑)

`clickhouse_driver.Client.execute` 函数签名：
```python
def execute(
    self,
    query: str,
    params: Optional[Sequence] = None,
    with_column_types: bool = False,
    ...
):
```

**错误代码：**
```python
# ❌ 错误！with_column_types=True 跑到 params 参数位置了！
return self.client.execute(query, with_column_types=True)
```

clickhouse-driver 看到 `params=True` → 仍然认为你传了参数 → **仍然会尝试解析 SQL 中的 `%` 字符作为占位符！**
即使你的 SQL 中根本没有 `%`，只要 `params` 不是 `None`，它就会走解析路径！

**正确代码：**
```python
# ✅ 正确：显式传递 params=None
return self.client.execute(query, params=None, with_column_types=True)
```

---

### 问题 2：Pydantic 验证错误 `duration_ms`

**错误信息：**
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for SpanResponse
duration_ms
  Input should be a valid integer [input_value=None, input_type=NoneType]
```

**根因：**
- ClickHouse 中 `duration` 可以是 `NULL`
- Python 中得到 `None`
- 但 Pydantic 模型定义 `duration_ms: int`（不允许 None）
- 实体定义 `duration_ms: int`（也不允许 None）

**修复：**
```python
# 实体定义
class Span:
    duration_ms: Optional[int]  # 添加 Optional

# Pydantic 响应模型
class SpanResponse(BaseModel):
    duration_ms: Optional[int]  # 添加 Optional
```

---

## 总结教训

| 教训 | 说明 |
|------|------|
| **检查参数顺序** | 位置参数容易错，提倡关键字参数 |
| **clickhouse-driver 占位符机制** | 只要 `params` 不是 `None`，就会解析占位符，不管你 SQL 里有没有 `%` |
| **kill 进程完全重启** | Uvicorn 热重载有时候不加载新修改的代码，一定要 kill 所有 Python 进程再启动 |
| **允许 NULL 字段** | ClickHouse 字段允许 NULL → Python 类型必须标记 `Optional` |

---

## 快速调试 Checklist

遇到 ClickHouse 语法错误 `%s` 时：

- [ ] grep 全项目确认还有没有 `%`
- [ ] 检查 `clickhouse_client.query` 中 `params=None` 是否正确传递
- [ ] 确认 `execute(query, params=None, with_column_types=True)` 参数顺序正确
- [ ] kill 所有 Python 进程完全重启后端
- [ ] 直接 curl API 验证，排除浏览器缓存

---

## 本次修复的关键文件修改

- `app/clients/clickhouse_client.py` - 修复参数顺序，明确 `params=None`
- `app/domain/entities/trace.py` - `duration_ms`, `start_time_ms`, `end_time_ms` 改为 `Optional`
- `app/models/execution.py` - `SpanResponse.duration_ms` 改为 `Optional[int]`
- `app/services/trace_fetcher.py` - 所有查询改为 f-string，移除 `%s` 占位符
- `app/services/execution_service.py` - 集成 `get_trace_id_by_run_id` 流程

