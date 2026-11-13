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
