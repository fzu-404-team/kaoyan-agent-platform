<template>
  <div class="wrap">
    <!-- 整页共用的涂卡方格，左右两侧连成一体；对读屏隐藏 -->
    <PixelField
      class="page-pixels"
      :focus-x="0.6" :focus-y="0.42" :text-end="0.4"
      :base-rgb="[234, 229, 218]" :tint-rgb="[200, 206, 216]" :active-rgb="[47, 74, 122]"
    />

    <section class="stage" aria-label="平台介绍">
      <div class="intro">
        <div class="brand reveal" style="--d: 0ms">
          <img class="mark" src="/logo.png" alt="" width="40" height="40" />
          <span class="name">考研 Agent 平台</span>
        </div>
        <h1 class="display reveal" data-text="考研 Agent" style="--d: 100ms">考研 Agent</h1>
        <p class="typer reveal" style="--d: 220ms">
          <span class="sr-only">{{ phrases.join('、') }}</span>
          <span aria-hidden="true">{{ typed }}<span class="caret" /></span>
        </p>
        <p class="slogan reveal" style="--d: 320ms">{{ slogan }}</p>
        <p class="desc reveal" style="--d: 420ms">{{ desc }}</p>
        <ol v-if="features.length" class="dots">
          <li v-for="(f, i) in features" :key="f" class="reveal" :style="{ '--d': `${520 + i * 90}ms` }">
            <span class="dot-no" aria-hidden="true">{{ String(i + 1).padStart(2, '0') }}</span>{{ f }}
          </li>
        </ol>
      </div>

      <!-- 答题卡示意：四门科目各一行，只表示状态，不展示任何真实数据 -->
      <div class="sheet" aria-hidden="true">
        <div class="sheet-head">
          <span class="sheet-title">答题卡</span>
          <span class="sheet-sub">408 计算机学科专业基础</span>
        </div>
        <div v-for="(row, r) in sheetRows" :key="row.name" class="sheet-row">
          <span class="row-name">{{ row.name }}</span>
          <span class="row-cells">
            <span
              v-for="(state, c) in row.cells" :key="c"
              class="cell" :class="state"
              :style="{ '--i': r * 10 + c }"
            >{{ c + 1 }}</span>
          </span>
        </div>
        <div class="sheet-legend">
          <span><i class="lg done" />已判</span>
          <span><i class="lg wrong" />判错</span>
          <span><i class="lg draft" />草稿</span>
        </div>
      </div>
    </section>

    <main class="right">
      <div class="panel">
        <slot />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
/**
 * 登录 / 注册共用布局：左侧纸色品牌区（涂卡方格、宋体标题、打字机、答题卡示意），右侧表单卡片。
 * 视觉沿用刷题页“答题纸”方向；页面只通过默认插槽提供表单，左侧不放任何输入控件。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import PixelField from '@/components/PixelField.vue'

withDefaults(defineProps<{ slogan: string; desc: string; features?: string[] }>(), { features: () => [] })

type CellState = 'done' | 'wrong' | 'draft' | 'now' | ''

// 每行 10 格：已判、判错、草稿、当前题与未作答，四行各不相同，避免看起来像复制
const sheetRows: { name: string; cells: CellState[] }[] = [
  { name: '数据结构', cells: ['done', 'done', 'done', 'wrong', 'done', 'done', 'done', 'done', '', ''] },
  { name: '组成原理', cells: ['done', 'wrong', 'done', 'done', 'draft', '', '', '', '', ''] },
  { name: '操作系统', cells: ['done', 'done', 'done', 'done', 'done', 'wrong', 'done', 'now', '', 'draft'] },
  { name: '计算机网络', cells: ['done', 'done', 'done', '', '', '', '', '', '', ''] }
]

// 打字机：逐字打出、停留、逐字删除后切换下一条；减少动态效果时直接显示完整内容
const phrases = ['来源可查的课程习题', '错题自动归集', '实时解析', '按科目和难度抽题']
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const typed = ref(reduceMotion ? phrases.join(' · ') : '')
let typerTimer = 0
function typeLoop(index = 0, length = 0, deleting = false) {
  const phrase = phrases[index]
  typed.value = phrase.slice(0, length)
  let next: () => void
  let delay: number
  if (!deleting && length < phrase.length) { next = () => typeLoop(index, length + 1); delay = 110 }
  else if (!deleting) { next = () => typeLoop(index, length, true); delay = 1600 }
  else if (length > 0) { next = () => typeLoop(index, length - 1, true); delay = 45 }
  else { next = () => typeLoop((index + 1) % phrases.length, 0); delay = 300 }
  typerTimer = window.setTimeout(next, delay)
}
onMounted(() => { if (!reduceMotion) typerTimer = window.setTimeout(() => typeLoop(), 600) })
onBeforeUnmount(() => window.clearTimeout(typerTimer))
</script>

<style scoped lang="scss">
/* 答题纸方向的局部变量；刷题页落地后再提升为全局设计变量 */
.wrap {
  --paper: #f4f1ea;
  --paper-card: #fbf9f4;
  --paper-2: #ece7dc;
  --paper-3: #e3ddcf;
  --ink: #23211d;
  --ink-2: #5c574e;
  --ink-3: #6f695f;
  --rule: #d8d1c2;
  --pen: #2f4a7a;
  --pen-deep: #253c64;
  --pen-tint: #e4e6e6;
  --red: #b23a2e;
  --serif: "Songti SC", "Noto Serif SC", "Source Han Serif SC", "STSong", serif;
  --mono: "SF Mono", ui-monospace, Menlo, Consolas, monospace;

  position: relative; overflow: hidden; isolation: isolate;
  min-height: 100vh; display: flex;
  background: var(--paper);
  color: var(--ink);
}
.page-pixels { z-index: -1; }

/* ---------- 左侧品牌区 ---------- */
.stage {
  position: relative; container-type: inline-size;
  flex: 1; min-width: 0; padding: 56px 64px;
  display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 48px;
}
.intro { max-width: 420px; }
.brand { display: flex; align-items: center; gap: 10px; margin-bottom: 40px; }
.mark { width: 40px; height: 40px; border-radius: 9px; flex-shrink: 0; display: block; }
.name { font-weight: 600; color: var(--ink-2); }

.display {
  position: relative; display: inline-block;
  margin: 0 0 16px;
  font-family: var(--serif); font-size: 60px; line-height: 1.1; font-weight: 700; letter-spacing: .02em;
  color: var(--ink);
}
/* 悬停时的套印错位：钢笔蓝与批改红两层短暂错开，像印刷没对准，随后归位 */
.display::before, .display::after {
  content: attr(data-text); position: absolute; inset: 0; pointer-events: none; opacity: 0;
}
.display::before { color: var(--pen); }
.display::after { color: var(--red); }
@media (hover: hover) {
  .display:hover::before { animation: glitch-a .32s steps(2) both; }
  .display:hover::after { animation: glitch-b .32s steps(2) both; }
}
@keyframes glitch-a {
  0% { opacity: .9; clip-path: inset(10% 0 55% 0); transform: translate(-3px, -1px); }
  50% { opacity: .9; clip-path: inset(60% 0 8% 0); transform: translate(3px, 1px); }
  100% { opacity: 0; clip-path: inset(0); transform: none; }
}
@keyframes glitch-b {
  0% { opacity: .8; clip-path: inset(55% 0 15% 0); transform: translate(3px, 1px); }
  50% { opacity: .8; clip-path: inset(15% 0 60% 0); transform: translate(-3px, -1px); }
  100% { opacity: 0; clip-path: inset(0); transform: none; }
}
.typer {
  min-height: 28px; margin: 0 0 22px;
  font-family: var(--mono); font-size: 17px; font-weight: 600; color: var(--pen);
}
.caret {
  display: inline-block; width: 2px; height: 1.1em; margin-left: 3px; vertical-align: -3px;
  background: var(--pen); animation: blink 1s steps(1) infinite;
}
@keyframes blink { 50% { opacity: 0; } }
.slogan { margin: 0 0 10px; font-family: var(--serif); font-size: 21px; font-weight: 700; letter-spacing: .2em; color: var(--ink); }
.desc { margin: 0 0 28px; font-size: 14px; line-height: 1.75; color: var(--ink-2); }
.dots {
  display: grid; gap: 10px; margin: 0; padding: 22px 0 0; list-style: none;
  border-top: 1px solid var(--rule); font-size: 14px; color: var(--ink);
}
.dots li { display: flex; align-items: baseline; gap: 14px; }
.dot-no { font-family: var(--mono); font-size: 12px; color: var(--ink-3); }

/* 答题卡示意：一张略微倾斜的纸 */
.sheet {
  width: 340px; padding: 22px 22px 18px;
  background: var(--paper-card);
  border-radius: 6px;
  box-shadow: 0 0 0 1px var(--rule), 0 24px 48px -30px rgba(35, 33, 29, .45);
  transform: rotate(-1.5deg);
  /* 入场后缓慢上下漂浮；漂浮用独立的 translate 属性，不覆盖倾斜角度 */
  animation:
    sheet-in .8s cubic-bezier(.2, .7, .2, 1) .2s both,
    sheet-bob 6s ease-in-out 1s infinite;
}
@keyframes sheet-in { from { opacity: 0; transform: rotate(-4deg) translateY(16px); } }
@keyframes sheet-bob { 50% { translate: 0 -10px; } }
.sheet-head {
  display: flex; align-items: baseline; justify-content: space-between;
  padding-bottom: 12px; margin-bottom: 14px; border-bottom: 1px solid var(--rule);
}
.sheet-title { font-family: var(--serif); font-size: 18px; font-weight: 700; letter-spacing: .1em; }
.sheet-sub { font-size: 12px; color: var(--ink-3); }
.sheet-row { display: grid; grid-template-columns: 64px 1fr; align-items: center; gap: 8px; margin-bottom: 10px; }
.row-name { font-size: 12px; color: var(--ink-2); }
.row-cells { display: grid; grid-template-columns: repeat(10, 1fr); gap: 4px; }
.cell {
  position: relative; height: 24px; border-radius: 3px;
  display: grid; place-items: center;
  font-family: var(--mono); font-size: 10px; color: var(--ink-3);
  border: 1px solid var(--rule);
}
/* 格子默认就是最终状态；入场动画只从空白填进来，减少动态效果时直接显示结果 */
.cell.done, .cell.wrong {
  background: var(--paper-3); border-color: var(--paper-3); color: var(--ink-2);
  animation: cell-in .35s ease-out both; animation-delay: calc(500ms + var(--i) * 18ms);
}
.cell.wrong { color: var(--red); }
.cell.wrong::after {
  content: ""; position: absolute; left: 4px; right: 4px; top: 50%;
  height: 2px; margin-top: -1px; border-radius: 2px; background: var(--red);
  transform: rotate(-28deg); transform-origin: left center;
  animation: pen-stroke .3s ease-out both; animation-delay: calc(700ms + var(--i) * 18ms);
}
.cell.draft { border-style: dashed; border-color: var(--pen); color: var(--pen); }
.cell.now { border: 2px solid var(--ink); color: var(--ink); font-weight: 700; }
@keyframes cell-in { from { background: transparent; border-color: var(--rule); } }
@keyframes pen-stroke { from { transform: rotate(-28deg) scaleX(0); } }
.sheet-legend { display: flex; gap: 16px; margin-top: 14px; font-size: 12px; color: var(--ink-3); }
.lg { display: inline-block; width: 10px; height: 10px; margin-right: 5px; vertical-align: -1px; border-radius: 2px; }
.lg.done { background: var(--paper-3); }
.lg.wrong { background: var(--red); }
.lg.draft { border: 1px dashed var(--pen); }

/* 入场：依次淡入上移 */
.reveal { opacity: 0; animation: rise .7s cubic-bezier(.2, .7, .2, 1) forwards; animation-delay: var(--d, 0ms); }
@keyframes rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }

/* ---------- 右侧表单区（表单内容来自页面插槽） ---------- */
.right {
  width: 460px; flex-shrink: 0;
  display: grid; place-items: center; padding: 40px;
}
.panel {
  /* 表单校验提示改用批改红，在纸色底上对比度足够 */
  --el-color-danger: var(--red);
  width: 100%; max-width: 380px; padding: 36px 32px 28px;
  background: var(--paper-card);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--rule), 0 30px 60px -40px rgba(35, 33, 29, .5);
  animation: rise .7s cubic-bezier(.2, .7, .2, 1) .15s both;
}
.panel :deep(.title) { font-family: var(--serif); font-size: 28px; font-weight: 700; margin: 0 0 6px; color: var(--ink); }
.panel :deep(.sub) { color: var(--ink-2); margin: 0 0 28px; }
.panel :deep(.foot) { text-align: center; margin-top: 18px; color: var(--ink-2); font-size: 13px; }
.panel :deep(.foot a) { color: var(--pen); font-weight: 600; }
.panel :deep(.foot a:hover) { text-decoration: underline; text-underline-offset: 3px; }

/* 输入框：纸面白底、细描边，聚焦时钢笔蓝；字号 16px，避免手机聚焦时页面被放大 */
.panel :deep(.el-input__wrapper) {
  background: #fffdf8; border-radius: 6px;
  box-shadow: 0 0 0 1px var(--rule) inset;
  transition: box-shadow .15s ease;
}
.panel :deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px var(--ink-3) inset; }
.panel :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--pen) inset, 0 0 0 3px rgba(47, 74, 122, .14);
}
.panel :deep(.el-input__inner) { font-size: 16px; color: var(--ink); }
.panel :deep(.el-input__inner::placeholder) { color: var(--ink-3); }
.panel :deep(.el-input__prefix), .panel :deep(.el-input__suffix) { color: var(--ink-3); }

/* 主按钮：钢笔蓝实色，覆盖全局主按钮的渐变与投影（这里选择器更具体） */
.wrap .panel :deep(.el-button.el-button--primary.btn) {
  --el-button-bg-color: var(--pen);
  --el-button-border-color: var(--pen);
  --el-button-hover-bg-color: var(--pen-deep);
  --el-button-hover-border-color: var(--pen-deep);
  --el-button-active-bg-color: var(--pen-deep);
  --el-button-active-border-color: var(--pen-deep);
  width: 100%; margin-top: 4px; height: 44px;
  border-radius: 6px; background-image: none; box-shadow: none;
  font-size: 15px; letter-spacing: 2px;
}
.wrap .panel :deep(.el-button.el-button--primary.btn:active) { transform: translateY(1px); }
.wrap .panel :deep(.el-button.el-button--primary.btn:focus-visible) { outline: 3px solid var(--pen); outline-offset: 2px; }

/* 按左侧区域自身宽度决定是否显示答题卡，太窄时不压住文案 */
@container (max-width: 800px) {
  .sheet { display: none; }
}
@media (max-width: 900px) {
  .wrap { flex-direction: column; }
  .stage { display: block; flex: none; padding: 32px 24px 24px; }
  .brand { margin-bottom: 24px; }
  .display { font-size: 44px; }
  .right { width: 100%; padding: 8px 16px 40px; }
  .panel { max-width: 440px; }
}
@media (max-width: 480px) {
  .stage { padding: 24px 20px 20px; }
  .brand { margin-bottom: 18px; }
  .display { font-size: 38px; margin-bottom: 10px; }
  .typer { font-size: 15px; margin-bottom: 14px; }
  .slogan { font-size: 17px; letter-spacing: .14em; margin-bottom: 0; }
  /* 手机上让表单进入首屏：说明与特性列表收起，品牌、打字机与标语保留 */
  .desc, .dots { display: none; }
  .panel { padding: 28px 20px 24px; }
}
@media (prefers-reduced-motion: reduce) {
  .caret, .panel, .reveal, .sheet, .cell, .cell::after,
  .display::before, .display::after { animation: none !important; }
  .reveal { opacity: 1; }
  .caret { display: none; }
  .panel :deep(.el-input__wrapper) { transition: none; }
}
</style>
