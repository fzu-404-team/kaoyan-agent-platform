# 移动端刷题与院校详情布局验证（G11，2026-11-17）

## 范围

- 上游 issue `fzu-404-team/kaoyan-agent-platform#61`（G11 · [移动端] 让手机上更容易刷题和查看院校详情）。
- 改动文件：`kaoyan-frontend/src/views/PracticeHome.vue`、`PracticeSession.vue`、`SchoolDetail.vue`、`kaoyan-frontend/src/components/DiagnosticEntry.vue`；新增 `kaoyan-frontend/tests/mobile-practice-school.spec.ts`。
- 仅布局与展示层：接口契约、任务类型、判分、持久化与模型边界不变，无数据库迁移，Java／Python 未改动。

## 实现

- 刷题页 ≤640px：紧凑设置区（页面内边距 16/12、设置卡 14/12、组间距 12、选项胶囊 13px 字号／44px 高、摘要与全宽开始按钮竖排）。默认配置（普通练习·数据结构·中等·5 题）且诊断提示行启用时，「开始刷题」按钮完整落在 390×844 首屏内。
- 答题页 ≤640px：卡片与选项间距紧凑，提交／下一题与查看已保存作答按钮全宽、44px 高；提交成功后反馈 `scrollIntoView({block:'nearest'})` 滚入视野，遵循 `prefers-reduced-motion`；已选提示不再提及 Enter（桌面快捷键提示保留）。
- 院校详情 ≤640px：`matchMedia('(max-width: 640px)')` 切换为每条专业一张卡片，直接展示专业名、年份标签、招生计划与往年复试参考线（复用 `SchoolMetric`，口径、来源与待核实标注不变）；专业代码、学院、方向、学习方式、招考类别与备注收进原生 `<details>`「其余字段」，展开可读完整记录。桌面保留原 `el-table` 与全部列。视口监听在组件卸载时移除。
- `DiagnosticEntry` compact 变体 ≤640px：缩小内边距与字号，压缩首屏占用；其余变体不变。

## 验证（本机 Windows，Edge 作为 Playwright 浏览器）

- 环境：Node 24、Playwright 1.58.2，`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 指向本机 Edge；Vite preview 4173 使用生产构建；API 全部由测试 mock，不连接日常 MySQL／Redis／模型。
- `npm ci`：本机全局 registry 为旧镜像 `npmmirror.com/mirrors/npm/`（zrender 等 tarball 404）。本次以命令行 `--registry=https://registry.npmmirror.com` 绕过；未修改全局 npm 配置与 `package-lock.json`。
- `npm run build`（`vue-tsc -b && tsc -p tsconfig.node.json && vite build`）通过；大于 500kB 的包体提示为既有保留项。
- 新增用例 `mobile-practice-school.spec.ts` 4/4 通过（desktop 1280×900 与 mobile 390×844 各 2 项）：
  - 首屏断言：开始按钮 `getBoundingClientRect` 完整位于视口内，无需滚动；
  - 闭环：开始刷题 → 选 B → 提交 → 反馈「回答错误，正确答案：C」及解析自动滚入视野 → 完成，查看结果 → 「本次练习完成」；
  - 院校详情 mobile：2 张卡片、无 `el-table`；专业、年份、招生计划、复试参考线首屏可读；其余字段默认折叠，展开后长备注、专业代码、学院／方向、学习方式与招考类别完整可读；旧版原登记值保留；文档无横向溢出；
  - 院校详情 desktop：7 列表头齐全，指标与备注可读，无卡片渲染。
- 全量回归 `npx playwright test`：288 项，286 通过，2 失败（均 desktop）：
  - `school-options.spec.ts:85`「empty catalog has explicit empty options」：strict mode 冲突（两个 el-select 下拉同时 visible）。在当前构建与 HEAD 基线 worktree（`13aa645`，独立构建、共用依赖 junction）单独复跑均同样失败 → 既有问题，与本轮无关（SchoolList 未改动）；mobile project 同用例通过。
  - `export.spec.ts:43`：全量中失败一次，当前构建与基线单独复跑均通过 → 偶发。
  - 基线 worktree 与 junction 已清理，主工作区依赖与构建产物完好。
- 截图：`kaoyan-frontend/test-results/mobile-practice-school-*/` 下 `practice-home.png`、`practice-feedback.png`、`school-detail.png`（双视口）。

## 真实栈复核（2026-11-17，隔离 Docker 演示栈）

- 临时本机脚手架（compose／Dockerfile／nginx，不入库）启动 MySQL8（全新隔离卷：V1＋V7—V15 各一次＋V2 演示种子与项目原创夹具）、Redis、Java、Agent（规则模式、lexical）与 nginx 前端，入口 `http://localhost:8080`。
- 真实浏览器（Edge／Playwright）双视口 29/29 通过：注册／登录；默认配置「开始刷题」首屏 bottom=661<844；5 题完整批次选答案→提交→判定＋解析反馈滚入视野→批次完成；院校详情手机卡片优先字段与展开后完整专业记录、桌面 7 列表格；均无横向溢出。
- 搭建期修复：MySQL 初始化客户端在 C locale 下以 latin1 读种子致中文双重编码（容器 `LANG=C.UTF-8` 后重建隔离卷）；年份标签约 0.3s 入场淡入属组件动画，非缺陷，验收等其可见后再断言与截图。
- 脚手架与演示卷仅供本机人工验收，不入库、非正式数据；真实模型、实机手机与公网仍未运行。

## 未运行

- 真实模型、实机手机与公网检查；未启动或重启日常服务（真实栈复核使用隔离 Docker 演示栈，见上节）。
- Java `verify` 与 Python pytest 未运行（本轮两端无改动）。
- 人工验收待用户完成；验收通过后再提 PR。

## 剩余问题

- `school-options` desktop 用例在本机 Edge 上既有失败（基线可复现），建议另开任务处理下拉关闭时机或测试选择器，不在本轮范围。
- 启用自定义题量或科目切到计算机组成原理（附加许可说明行）时首屏高度增加；issue 仅要求默认配置首屏可见，本轮不处理。