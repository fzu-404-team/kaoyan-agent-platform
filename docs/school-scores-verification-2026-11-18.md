# 院校录取分数统计导入验证（2026-11-18）

契约见[搭建文档](../考研Agent平台搭建文档.md#院校录取分数统计导入契约2026-11-18)。本轮完成清洗、V16迁移、受保护导入工具、语料加载支持及隔离验证。用户对下列清单回复“Write DB and switch KB”后，**已在本机 `kaoyan_dev` 执行V16及导入，切换日常 `RAG_DATA`、重建日常索引并重启Agent**，见文末“日常环境执行”。

## 输入与处理决定

- 输入：用户提供的40个CSV，1192行，原始站点未知。用户确认按“用户审核通过”处理：状态 `USER_APPROVED`，可进向量库，来源如实记为“用户提供CSV”，不标官方、不填链接。
- 清洗：合并23行明显重复（被合并行的数值都已包含在保留行中），保留1169条观测，覆盖260所院校；2026年1118条、2025年37条、2024年14条。原值不改，标记 `POSSIBLE_SAME_POOL` 117条、`SAME_SCORES_DIFFERENT_CODES` 14条、`LINE_ABOVE_MIN` 3条、`AVG_OUT_OF_RANGE` 2条、`MAX_BELOW_MEDIAN` 1条、`MIN_ABOVE_MEDIAN` 1条。
- 院校：105所匹配日常库已有院校；155所需新增（含“湖州师范大学学院”更正为湖州师范学院）。省份按[维护者映射](../config/school-score-provinces-20261118.json)，未逐校核验官网；层次留空。“华北电力大学（保定）”归入已有的华北电力大学。
- 清单：[dataset.json](../outputs/school-scores-20261118/dataset.json)，SHA-256 `4db9e85e95cae098d3aa5a53eebfc93de763fbac8806dd3261ebb3f706c29785`；摘要见[preview.md](../outputs/school-scores-20261118/preview.md)。
- 语料：在当前本机 `RAG_DATA`（`school-catalog-corpus-d9c0a0a34c0c4e94.json`，849条）上追加1169篇分数统计，生成 `kaoyan-agent/knowledge/school-score-corpus-39429db4a8a2eed3.json`，releaseId `rag-v1-39429db4a8a2eed3`，共1274个检索块。

## 实际执行的验证

| 项目 | 结果 |
| --- | --- |
| 新增pytest | `scripts/tests/test_school_scores.py` 16项通过：无损合并、不同值或代码保留并标记、矛盾只标记、校名规范、非法行与表头拒绝、清单摘要防篡改、语料可检索但不可引用且不进入择校候选、链接与类型约束、SQL字面量不内联原文 |
| 全量Python | `kaoyan-agent/tests` 与 `scripts/tests` 共1172项通过（修复空字符串字面量前运行；修复只涉及导入脚本，其后新增测试单独重跑通过） |
| 日常库只读预览 | `kaoyan_dev` 现有121校；需执行V16，新增155校、1169条统计，已有0条 |
| 隔离预演 | 私密完整备份恢复到随机隔离库 `kaoyan_realdata_verify_6af29cd98e15`，29张表摘要一致；失败注入回滚、显式回滚、1169条与155校逐条回读、原有院校不变、非目标表摘要不变、重复执行不变、人工修订被拒绝全部通过 |
| 向量索引 | 在会话临时目录用本机缓存的 `BAAI/bge-small-zh-v1.5` 构建新语料Qdrant索引；“南京大学计算机技术2026年录取中位分”等3个院校问题返回对应院校的分数统计，`knowledge` 域无分数资料混入；hybrid检索正常 |

首次预演时，共享的 `sql()` 辅助函数把空字符串生成为空十六进制字面量，MySQL返回1054，失败注入因此提前失败。已在导入脚本内单独处理空字符串并补测试，删除该次遗留的隔离库后重跑全部通过。备份与报告在本机 `.cache/school-scores-20261118/operations/20261118-222909-283947/`（含个人数据，不公开）。

## 日常环境执行（2026-11-18 22:34—22:37）

| 步骤 | 结果 |
| --- | --- |
| `import-school-score-stats.py --apply --expected-sha 4db9e85e…6c29785` | 入口重新完整备份并在隔离库 `kaoyan_realdata_verify_612add1a8ad5` 预演，全部检查通过后写入日常库：执行V16，新增155校、1169条统计，逐条回读通过，原院校与非目标表摘要不变 |
| 再次只读预览 | 需V16否，待新增院校0、待新增统计0 |
| 日常库计数 | `school` 276、`school_score_statistic` 1169（260校）；`school_detail` 797、`school_admission_metric` 1594 保持原数 |
| Agent停止 | 原进程（工作目录 `kaoyan-agent/`、`.cache/mcp-pdf-venv`）以TERM正常退出；切换前 `.env` 私密备份于 `.cache/school-scores-20261118/switch-20261118-223554/env-before` |
| 切换语料 | `.env` 仅修改 `RAG_DATA` 一行，指向 `school-score-corpus-39429db4a8a2eed3.json` |
| `ingest.py` | 默认索引目录新增集合，`rag-v1-39429db4a8a2eed3`，1274块，约12秒；旧集合保留 |
| Agent重启 | 同一解释器、目录与uvicorn参数重启，日志 `.cache/school-scores-20261118/switch-20261118-223554/agent.log`；`/health` 200、`status=ok`、`releaseId=rag-v1-39429db4a8a2eed3`、`retrievalBackend=hybrid`，启动日志无错误 |

回退：停止Agent，用 `env-before` 中原 `RAG_DATA` 行恢复 `.env` 并重启（旧索引集合仍在）。数据库撤销须先恢复备份到独立库，按清单 `row_key` 与新增校名生成逐行撤销预览后另行确认，禁止整库覆盖日常库。写入备份与报告在 `.cache/school-scores-20261118/operations/20261118-223447-953049/`（含个人数据，不公开）。

## 未运行与限制

- 未运行：Java verify（Java代码未改）、前端构建、浏览器验收、真实模型、登录后的实际页面检查。Java与前端未重启（未改动）。
- Java接口与页面暂不读取 `school_score_statistic`；Agent现有回答路径不检索 `domain=school`，也仍遵守“不生成分数线”的约束，因此导入后对话中不会自动给出分数。分数问答路径与引用展示需另行变更。
- 数据本身未经官网核对，部分行存在明显矛盾或疑似同池重复，只作标记不修正。

## 增补：详情页与对话分数问答（2026-11-18 22:40—22:55）

契约见搭建文档同节“展示与分数问答”。用户回复“Yes, add them”后实现：

- Java：新增 `SchoolScoreStatistics`（缺V16返回null，其他数据库错误照常抛出；flags不合法的行跳过），`GET /api/schools/{id}` 增加可选 `scoreStatistics`；`SchoolCatalogService` 增加分数问题触发（`scoreRequested`／`scoreSchoolNames`），快照增加 `scoreStatistics:{total,notice,items}`（最多30条，按明确年份、六位代码或问题中的专业名过滤），回答正文由规则生成；导出写出同样字段、提示语及中文标记。
- Python：`agents/planning.py` 增加逐字一致的 `SCORE_TRIGGER`、`SCORE_EXCLUSION` 与院校名规则，`school_lookup_plan` 对分数问题返回同形 `SCHOOL_LOOKUP` 计划。
- 前端：新增 `SchoolScoreTable.vue`，院校详情页与对话中的库内院校卡片展示分数表、固定提示语和中文标记；缺值显示“未登记”，不显示0。

| 实际执行 | 结果 |
| --- | --- |
| Java `PYTHON_EXECUTABLE=../.cache/mcp-pdf-venv/bin/python bash mvnw -B -ntp verify` | 254项，0失败0错误，2项既有跳过；新增 `SchoolScoreStatisticsTest` 6项（排序、未知标记跳过、年份及专业名过滤、院系不当第二所学校、触发不吞其他流程、缺V16兼容与连接失败抛出）及导出1项 |
| Python 全量 `kaoyan-agent/tests` + `scripts/tests` | 1182项通过，含与Java同输入的分数计划镜像用例 |
| 前端 `npm run build` | 通过（既有大包提示） |
| Playwright（系统Chrome，接口替身，桌面／移动） | `school-scores`、`school-metrics`、`school-detail-loading` 共20项，`admission`、`export` 共32项通过；无横向溢出 |

**服务重启（22:55，用户回复“Restart both”）：** Java原进程（`java -jar kaoyan-B/target/kaoyan-backend-1.0.0.jar --server.address=127.0.0.1`，工作目录 `kaoyan-B/`）以TERM退出；核对其环境变量与根 `.env` 一致（仅Java不使用的 `RAG_DATA` 不同，另有 `PORT=8080`），用同一命令、目录与 `.env` 环境重启，约2秒启动，无令牌访问受保护接口返回401。Agent同样以原解释器、目录与uvicorn参数重启，`/health` 为 `ok`、`releaseId=rag-v1-39429db4a8a2eed3`，日志无错误。日志在 `.cache/school-scores-20261118/restart-20261118-225511/`。Vite开发服务器未重启（自动加载前端改动）。

**真实接口只读检查：** 用本机学情测试账号（凭据取自私密文件，未输出）登录后，`GET /api/schools` 返回276所；`GET /api/schools/{id}` 中深圳大学返回17条分数统计、南京大学13条、清华大学1条（2025年数学），字段与契约一致。

**未运行：** 真实对话中的分数问答（会在日常库写入会话记录，未执行；该路径由Java与Python测试覆盖）、登录后的浏览器实际页面截图、真实模型、线上服务器。

## 本机统一 verified 状态（2026-11-19）

- 用户确认本机数据库和版本知识库更新并允许重启两端。先备份 `school_score_statistic`，在隔离 MySQL 8.4.11 恢复该表并验证 V17、显式回滚、提交及恢复原值。兼容版 Java 启动后在本机执行 V17 和数据事务，回读 1,169 条均为 `verified`，逐行对比其余列摘要一致。
- 本机新版语料 `school-score-corpus-a90ca0d3d45795e0.json`的 2,018 条记录均为 `verified`。其中 782 条保留 `originalReviewStatus=catalog_approved`，1,169 条保留 `originalReviewStatus=user_approved`，逐条核对原来源内容及证据等级。使用本机缓存权重构建 1,274 个 Qdrant 检索块，验证向量召回及科目过滤。
- Python 共 1,207 项通过，另有 7 个子测试通过。Java Maven verify 共 271 项，269 项通过，2 项跳过。真实本机 Java 与 Agent 已重启。Agent 健康检查返回 `rag-v1-a90ca0d3d45795e0`、`hybrid`，无模型规则择校返回 `SCORE_HISTORY` 和 `USER_APPROVED` 候选。Java 已认证院校详情回读清华大学 1 条、南京大学 13 条、深圳大学 17 条分数统计，切换前后结果一致。
- 本机私有备份在 `.cache/verified-status-20261119.Pd7yO7DW/`，含表备份、状态恢复 SQL、切换前配置与旧 Java 包。旧知识库和索引保留，可在恢复配置后重启 Agent 使用。真实模型、浏览器和公网检查未运行。
