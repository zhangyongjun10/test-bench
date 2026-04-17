# 更新日志

## 2026-04-16

### 并发执行
- 修复并发执行误把页面选择的比对模型（例如 `kimi-k2.5`）作为 Agent 请求体 `model` 发送给 OpenClaw 的问题；并发执行调用 Agent 时固定使用 `openclaw:main`，`llm_model_id` 仅用于后续比对。
- 并发执行的 `user_session` 统一调整为 `exec_{execution_id.hex}`，与普通执行和回放执行保持一致；每路并发在创建执行记录前先生成独立执行 ID，不增加额外数据库更新。
- 移除前端“单实例 / 多实例”并发模式选择，后端同步收敛为单一路径：按照并发数创建多条独立 execution，每条独立客户端、独立 `user_session`、独立 `trace_id`。
- 并发执行 API 不再要求前端传递 Agent 请求模型或并发模式，前端只需传入输入内容、并发数、场景、Agent 和比对模型。
- 补充并发执行单元测试，覆盖 Agent 请求模型固定、会话隔离和执行状态更新。

### 执行列表
- 测试执行列表新增回放标识：后端列表接口按当前页执行 ID 聚合统计 `replay_count`，前端在列表中显示 `已回放 N 次`，方便快速识别已有链路回放记录的执行。

## 2026-04-15

### Agent 执行与连通性
- 将正式执行链路的默认 Agent 超时时间从 `300s` 调整为 `1200s`，用于支持文档批处理、多工具调用等可能超过 5 分钟的长任务场景；部署环境仍可通过 `AGENT_TIMEOUT_SECONDS` 覆盖。
- 将 Agent 管理页“测试链接”的请求超时时间调整为 `60s`，避免响应较慢的 OpenClaw 环境在短测试窗口内误判失败。
- 优化 Agent 测试链接失败原因：非 2xx 响应会返回 `HTTP 状态码 + 响应摘要`，连接/读取异常会至少返回异常类型，例如 `ReadTimeout`、`ConnectError`，避免前端出现空 `message`。

### 执行删除与回放依赖
- 修复删除带有回放子执行的执行记录时触发 `execution_jobs_parent_execution_id_fkey` 外键约束的问题：删除父执行前会先清理关联的回放任务、回放比对结果和子执行记录。
- 清理旧执行数据时复用单条执行删除逻辑，确保历史清理同样会处理回放依赖，避免批量删除绕过外键安全清理。

### 编码规则
- 新增根目录 `AGENTS.md`，作为 Codex 每次进入仓库时应读取的项目级规则；明确后续新增或修改代码时，类、方法、函数、接口、类型、常量等定义上方必须添加中文注释，并说明职责、用途或关键约束。

### 测试补充
- 补充 Agent 测试链接异常格式化测试，覆盖空字符串异常仍能返回异常类型的场景。
- 补充删除执行时清理回放依赖的仓储层测试，覆盖父执行、子执行、回放任务和比对结果的删除顺序。

## 2026-04-11

### 端到端链路回放
- 新增端到端回放任务：回放会重新触发一次 agent 完整调用，并为回放执行生成独立 `user_session`，避免复用历史会话上下文。
- 新增回放任务、回放详情、回放历史相关后端接口与数据模型；普通执行列表只展示 `run_source = normal` 的执行，回放执行通过回放详情和原始执行详情中的回放历史查看。
- 回放支持两种比对基准：和场景基线比对、和原始执行最终输出比对；原始执行基准会冻结原始最终输出和 OpenAI LLM 次数，场景基线会冻结场景基线输出和配置的 LLM 次数范围。
- 回放详情页支持场景基线单 Trace 展示、原始执行基准双 Trace 展示，并复用执行详情页的 Trace 样式：LLM / Tool 颜色区分、token 展示、LLM `Messages` / `Details` 标签页、消息默认折叠和工具调用摘要。
- 收紧最终输出判定规则：最终输出只能来自最后一个 `span_type == "llm"` 且 `provider == "openai"` 的 span，并且该 span 必须只有文本输出、没有 `tool_calls` / `function_call`；如果最后一个 OpenAI LLM span 是工具调用或没有文本，则认为 Trace 尚未完成或异常，不能回退使用前面的文本 span。
- 为回放比对和 Trace ready 判定补充测试，覆盖“前面有文本但最后一个 OpenAI LLM span 是工具调用时不能认定为最终输出”的场景。

## 2026-04-10

### 执行链路稳定性
- 修复 Trace 尚未完整落库时可能提前进入比对的问题：执行链路现在会等待出现最终 `provider == "openai"` LLM 调用后再比对。最终 LLM 调用的判定规则为：该 LLM span 能提取到文本输出，并且同一个输出中不包含 `tool_calls` / `function_call`；纯工具调用 turn 不会被当作最终输出。
- 明确 LLM 次数比对规则：等待只用于避免 Trace 异步落库导致的提前误判；一旦最终 LLM 文本已经出现，就立刻按当前 `provider == "openai"` 的 LLM span 实际数量做次数校验。如果实际数量低于场景最小值，会直接判定 LLM 调用次数检查未通过，不再为了凑满最小次数额外等待。
- 重新比对也采用同一套 Trace ready 等待逻辑：后台任务会重新拉取 trace，并在出现最终 OpenAI LLM 文本后执行比对；如果等待结束后仍没有最终文本，则按当前 trace 生成新的比对结果。
- 修复 OpenAI 纯工具调用响应被误识别为最终 LLM 输出的问题，避免把 `content = null` 且只有 `tool_calls` 的 span 当作最终输出。
- 收紧最终输出判定规则：只能检查最后一个 `provider == "openai"` LLM span；如果最后一个 LLM span 是工具调用或没有文本，说明 Trace 尚未完成或异常，不能回退使用前面的文本 span 作为最终输出。
- 补充执行等待与 LLM 输出提取测试，覆盖纯工具调用 span、OpenAI provider 过滤和最小 LLM 次数等待。

### 多次比对结果
- `comparison_results` 新增 `llm_model_id`，记录每一次比对实际使用的模型；历史数据会回填为执行记录上的初始比对模型。
- 新增 `GET /api/v1/execution/{id}/comparisons`，按时间倒序返回某次执行的全部比对结果，保留 `GET /api/v1/execution/{id}/comparison` 返回最新结果的兼容行为。
- 执行详情页改为左侧比对历史、右侧选中比对详情；默认选中最新比对，也可以点击历史卡片查看不同模型产生的比对结果。
- 执行详情页区分展示“首次比对模型”和“当前比对模型”，避免重新比对后仍误以为当前结果使用的是首次模型。

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
