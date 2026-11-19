# 按分数择校验证记录（2026-11-19）

契约见[按分数择校契约](../考研Agent平台搭建文档.md#按分数择校契约2026-11-19)，规则版本 `score-match-v1`。

## 背景与决定

- 问题：“我估分320，推荐哪些学校”此前会被拒绝，或按普通择校处理，分数不参与筛选；表单模考分只在 Java 选出 5 所之后做组内排序。
- 2026-11-19 用户确认：按往年录取最低分／中位分分冲稳保；无可比数据或低于范围的不进入候选，只报数量；择校页和主对话都支持；自动更新不接收分数；在目录分级会话（`evidenceLevel`／`SCORE_HISTORY`）完成后在其基础上实现。

## 改动范围

| 端 | 文件 | 内容 |
| --- | --- | --- |
| 文档 | 搭建文档、`docs/rag.md`、`docs/conversations.md`、README | 新增契约，改写“Python不接收模考分”等旧条目 |
| Python | `score_query.py`（新） | 原话总分与科目组合的确定性解析、表单／原话／偏好合并、追问 |
| Python | `schemas.py` | `ScoreQuery`；`ChatRequest.scoreQuery` 仅 `SCHOOL_RECOMMEND` 可用 |
| Python | `tools/schools.py` | `match_scores` 注册工具、统计索引、`score_tier`、`rank_programs` 分层名额与补位 |
| Python | `agents/school.py` | 科目作为硬条件、调用分层、`scoreFilter`、规则回答、带分数时不发起院校解释 |
| Python | `intents.py`、`agents/resolver.py` | 主对话把“总分+学校”和单独补充的“英一数一”识别为择校 |
| Java | `AgentRequest`、`TaskServiceImpl` | 转发 `scoreQuery`（不进快照）；校验 `scoreMatch`／`scoreFilter` |
| Java | `RecommendationScoreReferences` | 结果带 `scoreFilter` 时不再重排 |
| 前端 | `types/api.ts`、`utils/score-match.ts`（新）、`RecommendationCandidateList.vue`、`TaskResultView.vue`、`SchoolRecommendations.vue` | 冲／稳／保标签、往年最低／中位与分差、固定提示、表单说明 |

说明：解析模块放在 `kaoyan-agent/` 根目录（与 `intents.py` 同级），不是计划中的 `agents/`，避免 `intents.py` 导入时形成循环依赖。

## 实际验证

| 项目 | 环境 | 结果 |
| --- | --- | --- |
| Python pytest | `.cache/mcp-pdf-venv` | 1081 项通过（新增 `tests/test_score_match.py` 20 项） |
| Java `bash mvnw -B -ntp clean verify` | 本机，`PYTHON_EXECUTABLE` 指向同一环境 | 266 项，2 项跳过，BUILD SUCCESS（新增 3 项）。第一次不带 `clean` 的运行出现 48 个 Spring 上下文错误（找不到 `JwtService` 等 Bean），原因是构建途中修改了测试文件，导致编译产物不完整；`clean` 后全部通过 |
| 前端 `npm run build` | 本机 | 类型检查及构建通过 |
| Playwright `recommendation.spec.ts`、`admission.spec.ts` | 本机 Chrome（`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`），接口全部为页面内替身 | 36 项通过（新增分层展示 1 项 × 2 视口） |
| 隔离进程冒烟 | `school-score-corpus-39429db4a8a2eed3.json`，模型关闭，每组 20 个任务编号 | 见下表 |

冒烟结果（考生组合英一数一，计数按学校）：

| 专业 | 总分 | 三层内 | 低于范围 | 缺数据 | 组合不符 | 20 次共出现学校 |
| --- | --- | --- | --- | --- | --- | --- |
| 081200 学硕 | 280 | 76 | 66 | 16 | 1 | 44 |
| 081200 学硕 | 320 | 118 | 24 | 16 | 1 | 54 |
| 081200 学硕 | 360 | 140 | 2 | 16 | 1 | 41 |
| 081200 学硕 | 400 | 142 | 0 | 16 | 1 | 62（全部为稳／保） |
| 085404 专硕 | 320 | 16 | 7 | 4 | 59 | 16 |

085404 多数项目考英二数二，所以按英一数一查询时“组合不符”较多，符合预期。

## 实施中发现并处理的问题

- 冒烟时发现三处解析问题，已修正并写入契约和测试：“408分数一般”被读成 408 分；“320-340分”只取到 340；“英一408”因为数字前瞻规则丢失了英语科目。
- 推荐页旧 Playwright 用例在目录分级改动后已经失败：目录线索也显示「项目说明」，导致定位器匹配到两个元素。该问题与本功能无关，本次只把点击范围限定为第一个候选。

## 未运行与限制

- 日常 Python、Java、前端服务未重启，页面上的真实效果未在日常环境查看；未运行真实模型、MySQL 集成或公网部署。
- 分数统计为用户提供并经用户审核批准的数据，非学校官网原文。录取最低分／中位分可能来自共用录取池；往年数据不代表今年分数线；分层不代表录取概率。
- 用户写在原话里的分数和其他原话一样，按既有授权参与已有的一次条件解析；表单分数不进入模型输入。
- 主对话中，如果上一轮因缺科目组合而追问，下一轮只回复“英一数一”时，会沿用最近一条用户消息中的分数；更早的消息不会被回溯。
- `comboMismatch` 只统计招生目录项目；分数统计中其他科目组合的行在筛选阶段直接跳过，不计入该数。
