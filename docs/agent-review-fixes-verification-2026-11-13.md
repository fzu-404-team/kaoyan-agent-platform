# Agent审查修复验证记录（2026-11-13）

契约见[搭建文档](../考研Agent平台搭建文档.md#agent审查修复契约2026-11-13)。本记录只描述本轮实际执行的内容。

## 环境

- 本机 macOS，Python 3.13.15，`.cache/mcp-pdf-venv`（`hello-agents==0.2.8`、`openai==1.109.1`、`mcp==1.12.4`）。
- 根目录 `.venv` 缺 `hello_agents`、`.cache/helloagents-venv` 缺 `mcp`，两者均不能导入 `main`，本轮未使用、未修改。
- 模型关闭，使用测试替身；未连接日常MySQL／Redis，未启动或重启任何日常服务。

## 修复前的复现

| 问题 | 复现方式 | 结果 |
| --- | --- | --- |
| 词表缺失时预算失真 | 本机系统临时目录无cl100k词表，用 `prepare_input` 计量各提示 | 模式为 `utf8_piece_upper_bound`；意图解析固定开销7468／8000；两条历史全部被裁掉；输入200个汉字报 `context_budget_exceeded` |
| 知识问答检索不可用 | 注入抛出 `ToolUnavailable` 的检索工具，调用 `Workflows.run` | 异常直接抛出，任务失败 |
| 供应商空结果 | 替身返回 `choices=[]`，调用 `ainvoke` | 抛出 `IndexError`，不属于可降级的模型失败 |
| 日志配置 | 追踪 `logging.basicConfig` 的调用方 | 由 `hello_agents/memory/types/semantic.py` 导入时调用，级别固定INFO；`LOG_LEVEL` 无引用 |

说明：审查阶段曾判断“INFO日志不输出”，实测并非如此——日志一直由框架导入时的配置输出，问题是级别不可配、无时间戳、第三方INFO一并输出。

## 修改

| 文件 | 内容 |
| --- | --- |
| `kaoyan-agent/core/tokens.py` | 依次查找环境变量目录、项目 `.cache/tiktoken`、系统临时目录，逐份校验SHA-256 |
| `scripts/prepare-tokenizer.py` | 新增。下载并校验词表后写入项目缓存；执行情况见下文 |
| `kaoyan-agent/main.py` | 入口配置日志；词表缺失时WARNING；`/health` 增加 `tokenCounting` |
| `kaoyan-agent/agents/knowledge.py` | 检索不可用时返回 `UNSUPPORTED` 与固定提示，不调用模型 |
| `kaoyan-agent/core/model.py` | 空 `choices` 转为 `InvalidModelOutput("model_output_missing")` |
| `kaoyan-agent/core/framework.py` | 导入框架后恢复根日志器原有处理器与级别 |
| `kaoyan-agent/core/logs.py` | 新增。日志格式、项目／第三方过滤、只安装一次 |
| `kaoyan-agent/config.py` | `LOG_LEVEL` 规范化并校验取值 |
| `kaoyan-agent/tests/test_agent_review_fixes.py` | 新增14项回归 |
| `kaoyan-agent/tests/test_mcp_runtime.py` | 更新1条既有断言，见下 |

## 既有行为变更

`test_app_isolates_one_tool_and_health_never_calls_tools[knowledge]` 原断言知识MCP不可用时同步 `/internal/rag/chat` 返回 `FAILED`。按本轮契约改为 `SUCCESS` 且 `result.outcome=UNSUPPORTED`、无引用、正文含“检索暂时不可用”。原有“不自动重试、不静默切回本地”的约束未变。用户已于2026-11-13在了解该变化后确认保留新行为。Java对这类成功轮次的配额与历史处理沿用现有规则，本轮未验证。

## 验证结果

从项目根目录执行：

```bash
.cache/mcp-pdf-venv/bin/python -m pytest -q -p no:cacheprovider kaoyan-agent/tests
```

- 修复前基线：981项通过。
- 修复后：995项通过，0失败（66秒左右）。新增14项，覆盖词表查找顺序与校验、`/health` 字段、三类检索不可用降级且不调用模型、空结果原因码、日志过滤与只安装一次、全新进程中的日志格式、`LOG_LEVEL` 校验。
- 词表相关测试使用256个单字节的合成词表并临时替换校验值，验证的是查找与校验逻辑，不是真实cl100k词表。
- 在pytest之外用真实进程启动工厂并发一次知识问答：日志为 `2026-11-13 18:41:22,311 WARNING main tokenCounting=utf8_piece_upper_bound ...` 格式，httpx的INFO请求行不再输出；`/health` 返回 `tokenCounting=utf8_piece_upper_bound`，响应共367字符（Java读取上限4000）。

## 词表准备与真实词表下的结果

经用户同意后执行 `.cache/mcp-pdf-venv/bin/python scripts/prepare-tokenizer.py`：

- 首次执行因本机python.org版Python缺少系统根证书而失败（`CERTIFICATE_VERIFY_FAILED`），未写入文件。脚本改为使用环境内 `certifi` 的根证书并把网络错误转为明确提示，未关闭证书校验。
- 再次执行成功：写入 `kaoyan-agent/.cache/tiktoken/9b5ad71b2ce5302211f9c61530b329a4922fc6a4`，1681126字节，SHA-256为 `223921b7…65b2a7`，与代码内固定值一致；该目录已被 `.gitignore` 忽略。第三次执行输出“已存在校验通过的词表，未下载”。
- 真实词表下全量pytest：995项通过，0失败。
- 真实词表下的固定开销（系统提示、输出Schema与JSON包装）：

| 提示 | 字节估算 | cl100k估算 | 上限 |
| --- | --- | --- | --- |
| 意图解析 | 7468（93%） | 2278（28%） | 8000 |
| 学情专家 | 4668（38%） | 1487（12%） | 12000 |
| 知识问答 | 1869（15%） | 617（5%） | 12000 |
| 复习计划 | 2664（22%） | 852（7%） | 12000 |
| 笔记 | 1380（6%） | 451（2%） | 20000 |

- 同一组两条历史加“它们的区别是什么”：字节估算下历史0／2条，cl100k下2／2条。
- 用单字重复的合成输入探测意图解析的输入上限：2000字通过，4000字报 `context_budget_exceeded` 并回退本地规则。这是既有 `PLAN_INPUT_TOKENS=8000` 的结果，本轮未调整；合成文本的分词密度与真实中文不同，仅作量级参考。
- `/health` 返回 `tokenCounting=cl100k_base_estimate`。

## 未运行

- 真实模型请求未运行；空结果只用替身验证。两种计量均为本地估算，未与供应商真实用量对比。
- 服务器及其他机器未准备词表。
- 向量索引缺失、真实Qdrant故障下的知识问答未实测；`qdrant` 后端的远程连接异常不属于 `ToolUnavailable`，仍可能使任务失败，本轮未处理。
- Java `verify`、前端构建、三端联调、浏览器回归未运行；日常Agent未重启，本轮修改尚未在日常服务生效。

## 第二批：审查第5—8项

第一批已按功能拆为4个提交（`8be1589`、`22cb994`、`90dab6f`、`29a98f5`），位于 `adaptation-main`，未推送。以下为其后的修改。

### 修改

| 文件 | 内容 |
| --- | --- |
| `kaoyan-agent/core/scheduling.py` | 新增 `EXPERT_LABELS`；专家预期故障的提示由“SCHOOL：暂时不可用”改为“院校比较：暂时不可用” |
| `kaoyan-agent/agents/coordinator.py` | 复用同一标签表；综合汇总生成期间扣住正文增量 |
| `kaoyan-agent/retrieval.py` | lexical／bm25／qdrant先取20个候选块，去重后再截取；hybrid改用同一常量 |
| `kaoyan-agent/agents/school.py` | 院校候选解释生成期间扣住正文增量 |
| `kaoyan-agent/tests/test_agent_review_fixes.py` | 新增4项回归 |
| `kaoyan-agent/tests/test_multiagent.py` | 既有断言由“SCHOOL：暂时不可用”改为中文标签，并断言结果中不含 `SCHOOL` |
| `README.md`、`docs/rag.md`、搭建文档 | 同步契约、环境说明与命令 |

### 验证结果

- 全量pytest（`.cache/mcp-pdf-venv`，真实词表计量模式）：999项通过，0失败。
- 反向检查：临时把两处增量扣留替换为空操作、把候选块数置0后，本批4项新用例全部失败，说明用例确实覆盖了修改点。
- 综合汇总用例实际走到了汇总分支（断言模型收到 `CombinedAnswer` 请求），分别覆盖汇总被采纳与被拒绝两种情况，流事件只有两条stage，无delta。
- 检索去重用例使用临时合成语料（1篇约2850字的长文档加4篇短文档）和lexical后端；修改前该查询只能返回长文档1篇，修改后返回5篇。当前仓库语料每篇仅1个块，线上结果不受影响。

### README环境核对

对本文引用的脚本逐个检查顶层导入能否在各环境解析（静态导入检查，未实际运行这些脚本）：

| 环境 | 结果 |
| --- | --- |
| `.cache/mcp-pdf-venv` | 10个脚本与 `main` 全部可导入；`pip check` 无冲突；requirements、requirements-dev与约束文件中的固定版本全部一致 |
| `.cache/helloagents-venv` | `main`、`eval-quality.py`、`check-admission.py` 因缺 `mcp` 不能导入；`smoke-learning.py`、`smoke-chat.py`、`smoke-managed-mysql.py` 自身可导入，但会用当前解释器启动Agent，同样不可用 |
| 根目录 `.venv` | 缺 `hello_agents`，不能导入 `main` |

据此把README中7处需要启动或导入Agent的命令改为 `.cache/mcp-pdf-venv`，并在“准备环境”补充本机环境现状表。未安装、升级或删除任何环境中的包。

### 发现但未处理（BM25已于2026-11-14修正，见后文）

`retrieval.py` 的 `BM25Index` 用 `doc_freq.update(values)` 统计文档频率，实际累加的是词的出现次数而非包含该词的文档数。在31篇真实语料上：2312个多字词中317个计数被放大，7个词的IDF为负（如“计算”计48、实际17篇）；抽查15条查询，2条的前5排序与按真实文档频率计算的结果不同。只影响 `RAG_BACKEND=bm25` 与 `hybrid`，默认的lexical不受影响。修正会改变这两种后端的排序和既有质量评测基线，需单独确认后处理。

### 未运行

- 真实模型、Java `verify`、前端构建、三端联调与浏览器回归未运行；院校解释和综合汇总不再逐字输出的页面表现未在浏览器中查看。
- qdrant与hybrid后端的去重顺序只做了代码修改，未用真实向量索引验证。
- README中改写的脚本命令只做了导入检查，未实际执行。
- 日常Agent未重启。

## 2026-11-14：BM25修正与两项核实

第二批已按功能拆为5个提交（`fa19b0e`、`5e9b573`、`d92fa36`、`5af0f19`、`012cf36`），未推送。以下为其后的工作。环境同上（`.cache/mcp-pdf-venv`，真实词表计量模式）。

### BM25文档频率修正

- 修改：`kaoyan-agent/retrieval.py` 的 `BM25Index` 由 `doc_freq.update(values)` 改为 `doc_freq.update(set(values))`，文档频率按“包含该词的块数”统计。
- 回归：`test_agent_review_fixes.py` 新增 `test_bm25_document_frequency_counts_chunks_not_occurrences`（某词在单个块内出现30次、多于块总数时仍能命中该块，且任何词的文档频率不超过块数）；长文档不挤占名额的用例补上bm25后端。该bm25用例在修正前返回空结果。
- 全量pytest：1001项通过，0失败。
- 离线质量评测（不调用模型，`--data kaoyan-agent/knowledge/corpus.json`）修改前后各跑一次：`bm25` 与 `hybrid`（本机无向量标记，按设计回退BM25）均为10/10，逐例结果完全一致。报告在 `.cache/review-bm25fix-{before,after}-{bm25,hybrid}-20261114.json`，不提交。
- 31篇真实语料：IDF为负的多字词由7个降为0，文档频率超过块数的词为0。抽查15条查询，2条（“进程和线程的区别”“虚拟内存”）前5的顺序变化，结果集合不变，其余13条不变。
- 未验证：真实向量索引下的hybrid融合排序；日常服务当前为lexical，本次修正对其无影响。

### 核实一：`max_completion_tokens` 未被当前供应商采纳

经用户同意发出1次真实请求（本机配置：`https://api.deepseek.com`，`deepseek-flash`，thinking为disabled）。请求参数与应用一致（temperature 0、JSON模式、非流式、SDK不重试），仅把 `max_completion_tokens` 设为16；提示为合成的TCP拥塞控制说明请求，不含个人资料、历史或业务数据。直接使用SDK客户端发出，未经应用预算计数，未创建任务。

| 项 | 结果 |
| --- | --- |
| 结束原因 | `stop`（若上限生效应为 `length`） |
| 输出用量 | 200 tokens（上限设为16） |
| 正文长度 | 329字符 |
| 输入用量 | 59 tokens |
| 耗时 | 2.57秒 |

结论：该参数在DeepSeek的兼容接口上没有生效。因此 `MODEL_OUTPUT_TOKENS`、`PLAN_OUTPUT_TOKENS`、`NOTE_OUTPUT_TOKENS`、`STUDY_OUTPUT_TOKENS` 四个输出上限目前都没有传达到供应商，实际上限是供应商的默认值；应用侧的截断检测（`finish_reason=length`）和15万字符保护仍然有效。仅1次样本，也未测试智谱端点。未取得账单，不估算费用。该结论促成了下文的修复。

### 核实二：汇总4秒超时偏紧，证据有限

未为此追加真实请求，依据是两条已有的真实耗时：

- 本次请求：本机发出，输出200 tokens，总耗时2.57秒。
- [服务器模型配置记录](server-llm-verification-2026-11-03.md)：服务器发出，输出仅5 tokens，耗时3.709秒。

汇总需要重述至少两位专家的回答，输出通常远多于200 tokens；而服务器上输出5 tokens已用去3.7秒。据此判断4秒内完成汇总的可能性较低，超时后会回退本地拼接，但已消耗1次模型调用和1次每日额度（服务器每日上限20次）。这只是两条不同提示、不同机器的样本，不是对汇总请求本身的测量；汇总的实际成功率未测。时限为2026-11-03经用户确认的参数，本轮未调整。

### 修复：输出上限改用 `max_tokens`

- 修改：`kaoyan-agent/core/model.py` 中 `AsyncHelloAgentsLLM` 的非流式 `ainvoke` 与流式 `astream_invoke` 均改为以 `max_tokens` 传递上限，数值不变。契约见搭建文档“2026-11-14 输出上限参数”。
- 断言：`test_deepseek.py` 改为断言请求体含 `max_tokens` 且不含 `max_completion_tokens`；`test_provider_baseline.py` 在测试内把冻结基线中的旧键换成新键，基线文件 `tests/fixtures/provider-baseline.json` 保持不动。
- 全量pytest：1001项通过，0失败。
- 真实验证（经用户同意，第2次真实请求，按用户同时提出的“统一采用流式输出”走流式路径）：通过应用自己的 `AsyncHelloAgentsLLM.astream_invoke` 发出，参数与应用一致（DeepSeek `deepseek-flash`、thinking disabled、JSON模式、temperature 0、SDK不重试），上限设16，提示与核实一相同的合成内容。

| 项 | 结果 |
| --- | --- |
| 实际发出的参数 | `max_tokens=16`、`stream=True`，未发送 `max_completion_tokens` |
| 应用判定 | `model_output_truncated`，对外原因码 `INVALID_OUTPUT` |
| 截断前收到的正文 | 32字符 |
| 耗时 | 1.78秒 |

结论：上限在流式路径上已生效，且截断被应用正确识别并降级。非流式路径（同步 `/internal/rag/chat`）使用同一参数，只经单元测试的请求体断言验证，未单独发真实请求。流式请求未开启用量回传，故无供应商token计数。日常Agent未重启，服务器尚未更新。

上限生效后的影响：此前四个输出上限形同虚设；现在超过上限的回答会被判为截断并降级为规则结果。既有上限为普通专家2200、意图解析2048、笔记4096、复习计划最多8192（按天数），本轮未调整取值，也未统计真实回答是否经常接近这些上限。

### 校验后分段输出（用户新增要求）

用户在本轮提出“内容输出统一采用流式输出”。该要求与11月2日可信度约定及第7项（校验前不转发待审正文）冲突，经说明后用户选择“校验后分段输出”，未选择“生成即流式”。契约见搭建文档“2026-11-14 校验后分段输出”。

- 修改：新增 `kaoyan-agent/core/replay.py`（按换行与句末标点切分、最多24段、段间等待合计不超过1秒）；`kaoyan-agent/main.py` 的对话流在结果通过 `ChatResponse` 校验后、`result` 事件前推送分段，本轮已实时推送过正文的结果不再重复。
- Python回归新增9项：切分可完整还原原文且不超过24段；规则回答、问候与澄清提示都会分段；被拒绝的模型原文（含“99999”）从未出现在任何事件中，分段与降级后的最终回答一致；错题辅导已实时推送时不再回放；生成失败只发送error、不发送分段。反向检查：把回放替换为空操作后，4项相关用例全部失败。
- Java：`ConversationIntegrationTest` 原断言知识流“完全没有增量”，与新契约冲突。改为新增辅助方法 `streamedAnswer`：把订阅快照中的草稿与后续增量拼接，要求增量在completed之前、槽位为answer、offset连续，且拼接结果与最终保存的回答完全一致。该检查用于知识问答（模型回答被采纳）和非法引用（模型回答被降级）两种情况。首次运行时，沿用旧测试“收到增量后另发请求查询状态应为RUNNING”的检查失败（返回SUCCESS）：分段紧挨着结果发出，查询请求与最后一段存在竞态。已改为在同一条流内判断事件顺序。
- 结果：Python全量pytest 1012项通过；`ConversationIntegrationTest` 22项通过；Java全量 `bash mvnw -B -ntp verify` 239项、0失败、2项跳过（与11月3日记录一致）。Java运行使用 `PYTHON_EXECUTABLE=.cache/mcp-pdf-venv/bin/python`。
- 未运行：前端构建、浏览器中逐段显示的实际观感、真实模型下的分段；未统计分段带来的实际延迟。同步 `/internal/rag/chat` 不在本次范围内，仍一次性返回。日常服务未重启。
