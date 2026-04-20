# 更新日志

## 2026-04-20

### 并发执行状态机加固
- 新增 `execution_batches` 批次表和迁移 `0012_add_execution_batches`，持久化记录请求并发数、准备成功数、启动成功数、准备失败数、启动标记失败数和统一 Agent 调用时间。
- 重构并发执行单路结果为明确状态对象，覆盖准备失败、启动标记失败、Agent 失败、延迟比对、比对失败、完成和比对未通过，避免 `asyncio.gather` 子任务异常被静默吞掉。
- 修复 Agent client 构建、API key 解密、外层 Session 创建等异常无法回写 execution 的问题：只要 execution 已创建，后续任意异常都会收口为 `failed` 并写入错误原因。
- 修复 Trace 未 ready 时主流程误标 `completed` 的问题：首次比对返回延迟状态时 execution 保持 `comparing`，等待自动延迟比对成功后再进入最终完成状态。
- 优化批次状态接口：`queued`、`running`、`pulling_trace`、`comparing` 都计入运行中；不存在的批次返回 `not_found`；存在失败时返回 `completed_with_failures`。
- 新增 `CONCURRENT_EXECUTION_MAX_CONCURRENCY` 后端硬上限，默认 `200`；前端并发输入同步限制为 `200`，后端仍做最终校验并返回中文错误。
- 新增 `GET /api/v1/system/runtime-config` 运行时配置接口，前端并发输入上限改为读取后端配置，不再单独维护并发上限常量；后续只需修改后端 `CONCURRENT_EXECUTION_MAX_CONCURRENCY`。
- 更新 `.env.example`，补齐 Agent 超时、数据库连接池、数据库写入并发和单批次最大并发配置。
- 补充并发执行边界测试，覆盖 client 构建失败收口、Trace 延迟比对不误标完成、批次非终态统计和超过最大并发拦截。

### 并发执行比对
- 新增数据库连接池配置项：`DB_POOL_SIZE`、`DB_MAX_OVERFLOW`、`DB_POOL_TIMEOUT`、`DB_POOL_RECYCLE_SECONDS`，避免继续使用 SQLAlchemy 默认 `5 + 10 overflow` 的固定小连接池。
- 新增并发执行数据库访问限流：`CONCURRENT_EXECUTION_DB_CONCURRENCY` 控制并发执行链路同一时刻进入数据库读写区的协程数，Agent HTTP 并发与 DB 并发解耦，避免几十到上百并发场景把连接池瞬间打满。
- 调整并发执行启动方式为两阶段：先按 DB 限流准备所有 execution 记录，再一次性启动 OpenClaw HTTP 调用，确保页面选择 100 并发时不会因为 DB 写入限流变成分批 20 路调用 OpenClaw。
- 并发批次内 execution 会在所有记录准备完成后，使用真正即将统一调用 Agent 的时间回写 `created_at`、`updated_at`、`started_at`，避免页面时间显示为 DB 准备阶段的分批时间。
- 修复并发执行长时间占用数据库连接的问题：后台批次读取 Agent 后立即释放请求 Session，每一路执行只在落库/查询时短暂使用数据库连接，Agent HTTP 调用、Trace 轮询等待、LLM 比对前都会释放连接，避免高并发或长任务把 SQLAlchemy 连接池打满。
- 修复自动延迟比对重试耗尽后状态不收口的问题：当 Trace 多次重试后仍不可用，或比对逻辑未能完成时，会将 execution 标记为 `failed`，并写入中文错误信息，避免页面长时间停留在“比对中”。
- 修复自动延迟比对失败原因不准确的问题：现在会区分“完全没有 Trace spans”和“Trace 已存在但长时间没有最终 OpenAI 纯文本输出”，避免把工具调用未结束误报为未找到 Trace。
- 自动延迟比对新增顶层异常兜底：后台任务出现未预期异常时会记录错误日志，并同步将 execution 与对应 comparison 记录标记为失败态，避免协程异常导致状态悬挂。
- 自动延迟比对失败时会同步更新 `comparison_results`：已有处理中比对记录会改为 `failed` 并写入 `error_message`、`completed_at`；如果不存在比对记录，则创建一条失败比对记录，保证前端可以看到失败原因。

### 比对逻辑
- 移除历史内容截断逻辑：算法粗筛和 LLM 语义比对都会使用完整基线输出与完整实际输出，不再按固定长度截断。
- LLM 语义比对超时和调用失败原因改为中文提示，并继续归类为 `llm_verification_error`，避免把比对模型异常误展示成普通语义不一致。
- 重新比对后台流程保持可替换的仓储、Trace 拉取和比对服务入口，保证接口校验、后台执行和测试替身走同一套依赖路径。

### 执行清理
- 清理旧执行数据时改为复用单条执行删除逻辑，逐条清理回放子执行、回放任务和比对结果，避免批量删除绕过外键依赖处理。

### 日志输出
- 修复文件日志包含 ANSI 颜色控制字符导致打开像乱码的问题：控制台保留彩色输出，`logs/info.*.log` 和 `logs/error.*.log` 强制使用无颜色纯文本渲染。
- 修复日志文件日期长期停留在服务启动日的问题：文件日志改为按北京时间动态写入 `logs/info.YYYY-MM-DD.log` 和 `logs/error.YYYY-MM-DD.log`，不再生成 `info.启动日.log.轮转日.log` 这类混乱文件名。

### Agent 会话隔离
- 清理 Agent 级 `user_session` 运行时残留：Agent 创建、更新、响应和连通性测试不再读写或使用 Agent 配置里的 Session；正式执行统一使用 execution 级 `exec_{execution_id}` 会话，并发执行每一路显式传入独立 execution session。
- 清理 Agent 实体、接口模型、前端类型和并发执行测试中的 Agent Session 残留，并新增数据库迁移 `0011_drop_agent_user_session` 删除 `agents.user_session` 历史字段。
- 保留 `HTTPAgentClient` 的 `user_session` 入参与随机兜底，仅用于 execution 级调用覆盖和防御性会话隔离；前端 Agent 类型不再暴露 `user_session` 字段。

## 2026-04-17

### 比对日志与排障
- 新增比对模型请求结构化日志：当最终输出比对进入 LLM 语义判断时，会打印 `LLM comparison request payload`，包含 `execution_id`、`trace_id`、比对模型信息、`prompt`、`baseline_output`、`actual_output` 及长度，便于确认本次实际送给比对模型的内容。
- 新增比对模型响应结构化日志：比对模型返回后会打印 `LLM comparison response payload`，包含 `consistent`、`reason`、`duration_ms` 和比对模型信息，方便和请求日志按 `execution_id`、`trace_id`、`task_id` 配对排查。
- 优化全局 structlog 上下文：所有结构化日志自动补充稳定的进程内递增 `task_id`，不再使用 Python 对象内存地址，避免协程对象销毁后地址复用导致日志串联误判；日志中不再输出 `task_name`。
- 保留最终输出的 `execution.original_response` fallback 逻辑，仅增加日志观测能力；如果最终 OpenAI LLM 文本 span 未被本次比对快照取到，日志可以直接看出 `actual_output` 是否来自 fallback。

### 并发执行比对
- 修复并发执行比对过早触发的问题：并发执行链路此前只要拉到任意 Trace span 就会进入比对，可能在最终 `provider == "openai"` 纯文本 LLM span 尚未可见时保存不完整快照，导致 `actual_count` 少算或 `actual_output` fallback 到 `execution.original_response`。
- 并发执行现在复用普通执行的 Trace ready 规则：必须出现最后一个 `provider == "openai"` 的 LLM span，且该 span 能提取文本、没有 `tool_calls` / `function_call`，才进入比对；否则写入处理中比对记录并安排自动延迟比对。
- 自动延迟比对任务补充可追踪日志上下文，并继续按 Trace ready 规则等待最终 OpenAI 文本输出，避免 Trace 异步写入窗口内误判。

### 比对结果展示
- 将 LLM 调用次数范围错误、次数不符合预期、基线为空、最终输出为空等用户可见比对原因改为中文；前端详情页同时兼容历史英文原因，展示时即时翻译为中文。
- 执行详情页返回列表时保留来源列表 URL，执行列表的筛选条件、页码和每页条数会同步到 URL；从第二页进入详情再返回时，会回到原分页并避免 5 秒轮询刷新后跳回第一页。

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
