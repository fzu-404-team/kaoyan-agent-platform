# 刷题随机抽题验证记录（2026-11-19）

契约见[搭建文档 4.4 刷题中心规则](../考研Agent平台搭建文档.md#44-刷题中心的完整建设规则)中“2026-11-19 随机抽题”一段。该段补齐了 4.4 节原有的“random 无放回抽样”要求。

## 问题

普通刷题按 `stable_order` 取前 N 题，相同科目和难度每次都是同一批题；错题本和收藏夹也总从列表开头取题。

## 改动

| 文件 | 内容 |
| --- | --- |
| `service/PracticeDraw.java`（新增） | 排序规则：本人没做过的题随机无放回在前，做过的题按最近有效作答时间从早到晚，同一时间随机，截取 count |
| `mapper/PracticeRecordMapper.java` | `selectLastAnswered`：本人每题最近一次有效作答时间（`grading_status=valid` 且有 `answered_at`） |
| `mapper/QuestionMapper.java` | `selectPracticePool`：启用、已审核及科目／难度筛选的完整候选池；原 `selectForPractice` 未改 |
| `service/impl/PracticeServiceImpl.java` | 未传 `questionIds` 时，普通及错题／收藏来源走上述抽题；服务端 `SecureRandom`，不保存种子 |

不改的部分：传入 `questionIds` 的批次、`GET /api/questions/practice`、学习助手内部抽题、诊断批次、表结构、前端与响应字段。

## 实际验证

| 项目 | 环境 | 结果 |
| --- | --- | --- |
| `PracticeDrawTest`（新增 3 项） | 单元测试 | 没做过的题在前；做过的题按最久未做排序；数量截取、空池；不同种子顺序不同、同一时间并列随机、相同种子可复现 |
| `PracticeRandomDrawTest`（新增 2 项） | H2（MySQL 模式），真实接口 | 做完 3 题后下一批只抽另外 3 题；全部做过后最久未做的一批先出；他人作答不影响本人；8 个新账号抽到的 3 题不全相同；错题本只抽本人错题；`GET /api/questions/practice` 仍按 stable_order |
| `bash mvnw -B -ntp verify` | 本机 | 271 项，2 项跳过，BUILD SUCCESS |

## 未运行与限制

- 日常 Java 服务未重启，页面未检查；未在真实 MySQL 上运行，查询只在 H2 MySQL 模式下验证过。
- 每次开始练习都会读取该科目全部候选题和本人作答时间汇总。题库扩大到上万题时，需要重新评估查询开销。
- 学情功能开启时生成的 `L-` 批次也走同一抽题逻辑，但测试环境未开启学情功能，这条路径没有单独测试。
