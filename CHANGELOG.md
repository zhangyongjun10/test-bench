# 更新日志

## 2026-04-10

### 执行链路稳定性
- 修复 Trace 尚未完整落库时可能提前进入比对的问题：执行链路现在会等待出现最终 `provider == "openai"` LLM 调用后再比对。最终 LLM 调用的判定规则为：该 LLM span 能提取到文本输出，并且同一个输出中不包含 `tool_calls` / `function_call`；纯工具调用 turn 不会被当作最终输出。
- 明确 LLM 次数比对规则：等待只用于避免 Trace 异步落库导致的提前误判；一旦最终 LLM 文本已经出现，就立刻按当前 `provider == "openai"` 的 LLM span 实际数量做次数校验。如果实际数量低于场景最小值，会直接判定 LLM 调用次数检查未通过，不再为了凑满最小次数额外等待。
- 重新比对也采用同一套 Trace ready 等待逻辑：后台任务会重新拉取 trace，并在出现最终 OpenAI LLM 文本后执行比对；如果等待结束后仍没有最终文本，则按当前 trace 生成新的比对结果。
- 修复 OpenAI 纯工具调用响应被误识别为最终 LLM 输出的问题，避免把 `content = null` 且只有 `tool_calls` 的 span 当作最终输出。
- 补充执行等待与 LLM 输出提取测试，覆盖纯工具调用 span、OpenAI provider 过滤和最小 LLM 次数等待。

## 2026-04-09

### LLM-only 回放比对重构
- 将场景比对从旧的“过程/结果阈值”模式收敛为 LLM-only 比对流程。
- 为场景新增 `llm_count_min` 和 `llm_count_max`，用于校验 LLM 调用次数范围。
- 为 LLM 模型新增 `comparison_prompt`，并在创建/更新时接入默认 prompt 回填。
- 创建执行任务和触发重新比对时，`llm_model_id` 改为必填。
- 比对结果结构调整为 `llm_count_check` 和 `final_output_comparison`。
- 在最终输出比对中保留算法粗筛，并新增 `algorithm_similarity` 和 `verification_mode`。
- 比对时只统计 `provider == "openai"` 的 LLM span，并只从这些 span 中提取最终输出。

### 后端接口与服务更新
- 新增迁移文件 [0005_add_llm_only_comparison_fields.py](/E:/项目/model/test-bench/backend/migrations/versions/0005_add_llm_only_comparison_fields.py)。
- 更新 execution、scenario、llm、comparison、trace 相关模型以匹配新契约。
- 重构执行和重新比对链路，统一走 LLM-only 比对流程。
- 更新 `GET /execution/{id}/comparison`，返回新的比对结果结构，同时保留旧结构映射兼容。
- 更新 `GET /execution/{id}/trace`，返回 span 的 `provider`、`input_tokens`、`output_tokens`。
- 为 LLM 语义校验增加超时兜底，避免外部比对模型超时导致整次 recompare 直接失败。
- 将用户可见的比对失败原因统一改为中文提示。

### 稳定性修复
- 修复删除执行记录时的外键问题，先删除 `comparison_results` 再删除 `execution_jobs`。
- 为“清理旧执行数据”补齐相同的外键安全删除逻辑。
- 修复指标提取逻辑，避免 `duration_ms = None` 的 tool span 导致聚合崩溃。
- 修复重新比对成功后旧的 `execution.error_message` 残留问题，避免页面继续显示历史失败横幅。
- 将 SQLAlchemy `declarative_base` 导入切换到 2.0 推荐路径，清除相关 warning。
- 修复 execution 时间默认值，改为使用 UTC aware 时间写入新数据。

### 前端页面调整
- 移除临时的 V2 页面命名，恢复执行、场景、LLM 页面正式文件名。
- 将执行列表页改成真正的服务端分页。
- 场景表单、LLM 表单、执行详情页都已切换到新的 LLM-only 配置模型。
- 执行详情页的比对区域新增展示：
  - 总体结果摘要
  - LLM 调用次数检查
  - 最终输出比对
  - 算法粗筛相似度
  - 判定方式
- 在 Trace 中为 LLM span 展示 token 用量，格式为 `总数(输入+输出)`。
- Trace 里只展示 `provider == "openai"` 的 LLM span。
- Trace 回放样式重做，包含：
  - 更清晰的 span 卡片
  - LLM / tool 颜色区分
  - LLM span 的 `Messages` / `Details` 标签页
  - System / User / Assistant 默认折叠
  - 自动提取可读消息内容和工具命令摘要
- 执行详情页整体视觉升级，增加背景层次、顶部状态头图层和更清晰的模块分区。

### 时间处理
- 执行详情页统一按北京时间（`Asia/Shanghai`）显示时间。
- 为历史执行记录补充展示兼容逻辑，修正旧数据中 `created_at` 早 8 小时的历史写入问题。

### 测试补充
- 新增 [test_comparison_llm_only.py](/E:/项目/model/test-bench/backend/tests/test_comparison_llm_only.py)，覆盖：
  - LLM-only 比对主流程
  - 算法粗筛直通
  - OpenAI 消息内容提取
  - provider 过滤
  - LLM 超时降级处理
- 新增 [test_execution_api_llm_only.py](/E:/项目/model/test-bench/backend/tests/test_execution_api_llm_only.py)，覆盖：
  - `llm_model_id` 必填
  - 新的 comparison 返回结构
  - trace 的 provider / token 字段
  - recompare 行为
  - set-baseline 语义
  - 删除执行行为
- 补充 [test_metric_extractor.py](/E:/项目/model/test-bench/backend/tests/test_metric_extractor.py)，覆盖 `None` duration 的处理。

### 验证
- 后端：`python -m pytest tests/test_execution_api_llm_only.py tests/test_comparison_llm_only.py tests/test_metric_extractor.py`
- 前端：`npx tsc --noEmit`
