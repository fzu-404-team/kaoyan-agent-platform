<template>
  <div class="page recommendation-page">
    <header class="page-head">
      <div>
        <h1>择校推荐</h1>
        <p>
          {{ profile?.examYear ? `报考年份 ${profile.examYear}` : '报考年份未填写' }}
          <template v-if="profile?.targetSchool"> · 意向院校 {{ profile.targetSchool }}</template>
          · <RouterLink to="/profile">编辑档案</RouterLink>
        </p>
      </div>
      <RouterLink to="/schools">浏览院校库</RouterLink>
    </header>

    <el-tabs v-model="tab">
      <el-tab-pane label="条件推荐" name="manual">
        <section class="card pane">
          <el-form label-position="top" :disabled="submitting" @submit.prevent="generate">
            <div class="form-grid">
              <el-form-item label="目标专业">
                <el-select v-model="form.majorCode" aria-label="目标专业" clearable placeholder="由问题或档案补充">
                  <el-option label="081200 计算机科学与技术" value="081200" />
                  <el-option label="085404 计算机技术" value="085404" />
                </el-select>
              </el-form-item>
              <el-form-item label="学位类型">
                <el-select v-model="form.degreeType" aria-label="学位类型" clearable placeholder="由问题或档案补充">
                  <el-option label="学硕" value="academic" />
                  <el-option label="专硕" value="professional" />
                </el-select>
              </el-form-item>
              <el-form-item label="意向地区">
                <el-select v-model="form.regions" aria-label="意向地区" multiple filterable allow-create placeholder="不限地区">
                  <el-option v-for="province in provinces" :key="province" :label="province" :value="province" />
                </el-select>
              </el-form-item>
              <el-form-item label="地区要求">
                <el-select v-model="form.regionConstraint" aria-label="地区要求" :disabled="!form.regions.length">
                  <el-option label="优先考虑" value="preferred" />
                  <el-option label="必须满足" value="required" />
                </el-select>
              </el-form-item>
              <el-form-item label="学习方式">
                <el-select v-model="form.studyMode" aria-label="学习方式" clearable placeholder="不限学习方式">
                  <el-option label="全日制" value="full_time" />
                  <el-option label="非全日制" value="part_time" />
                </el-select>
              </el-form-item>
            </div>
            <details class="extra">
              <summary>按模考总分推荐（冲／稳／保）</summary>
              <p class="muted">选填同一科目组合的整套模考总分。填写后按往年录取分筛选并分冲稳保，低于往年范围或缺分数参考的学校只报数量；也可以直接在上方写“估分320，英一数一”。</p>
              <div class="form-grid">
                <el-form-item label="模考总分">
                  <el-input v-model="mockTotal" aria-label="模考总分" type="number" inputmode="numeric" min="0" max="500" placeholder="0–500" />
                </el-form-item>
                <el-form-item label="模考科目组合">
                  <el-select v-model="mockCombo" aria-label="模考科目组合" clearable placeholder="选择与模考一致的组合">
                    <el-option v-for="combo in combos" :key="combo.value" v-bind="combo" />
                  </el-select>
                </el-form-item>
              </div>
            </details>
            <details class="extra">
              <summary>补充报考条件或请求 AI 解释</summary>
              <el-form-item label="补充条件或问题">
                <el-input v-model="query" aria-label="补充条件或问题" type="textarea" :rows="2" maxlength="8000" placeholder="例如初试需要考408" />
              </el-form-item>
              <el-checkbox v-model="form.explainWithAi">请求 AI 解释</el-checkbox>
            </details>
            <p v-if="formError" class="error" role="alert">{{ formError }}</p>
            <div class="actions">
              <el-button type="primary" native-type="submit" :loading="submitting">
                {{ result?.resultPayload?.outcome === 'COMPLETED' ? '重新生成' : '生成推荐' }}
              </el-button>
              <span class="muted">每次生成计入任务额度</span>
            </div>
          </el-form>
        </section>
        <section v-if="result" ref="resultSection" class="card pane result-pane">
          <h2>本次推荐</h2>
          <TaskResultView :key="result.id" :task="result" compact-recommendation />
        </section>
      </el-tab-pane>

      <el-tab-pane v-if="autoAvailable" label="自动更新" name="automatic" lazy>
        <LearningRecommendationPanel :key="user.token" />
      </el-tab-pane>

      <el-tab-pane label="推荐历史" name="history">
        <section class="card pane" v-loading="historyLoading">
          <div class="history-head">
            <h2>最近 100 条推荐</h2>
            <el-button size="small" :disabled="historyLoading" @click="loadHistory">刷新历史</el-button>
          </div>
          <p v-if="historyError" role="alert">历史加载失败，请重试。</p>
          <el-empty v-else-if="!historyLoading && !history.length" description="还没有推荐记录" :image-size="64" />
          <div v-for="task in history" :key="task.id" class="history-row">
            <span>{{ task.createdAt?.replace('T', ' ').slice(0, 16) }} · {{ taskLabel(task) }}</span>
            <el-button size="small" @click="historyTask = task">查看</el-button>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog :model-value="!!historyTask" title="历史推荐" width="min(760px, 94vw)" top="5vh" @close="historyTask = undefined">
      <TaskResultView v-if="historyTask" :key="historyTask.id" :task="historyTask" compact-recommendation />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { nextTick, reactive, ref, watch } from 'vue'
import { learningStatus } from '@/api/learning'
import { generateRecommend, getRecommendList } from '@/api/recommend'
import { getSchoolOptions } from '@/api/school'
import { getCurrentUser } from '@/api/user'
import LearningRecommendationPanel from '@/components/LearningRecommendationPanel.vue'
import TaskResultView from '@/components/TaskResultView.vue'
import { useUserStore } from '@/stores/user'
import type { Task, User } from '@/types/api'

const user = useUserStore()
const tab = ref('manual'), autoAvailable = ref(false)
const profile = ref<User>(), provinces = ref<string[]>([])
const result = ref<Task>(), historyTask = ref<Task>(), history = ref<Task[]>([])
const resultSection = ref<HTMLElement>()
const submitting = ref(false), historyLoading = ref(false), historyError = ref(false)
const query = ref(''), mockTotal = ref(''), mockCombo = ref(''), formError = ref('')
const emptyForm = () => ({
  majorCode: '', degreeType: '', regions: [] as string[],
  regionConstraint: 'preferred', studyMode: '', explainWithAi: false,
})
const form = reactive(emptyForm())
const combos = ['一', '二'].flatMap((english, i) => ['一', '二', '三'].map((math, j) => ({
  label: `政治 / 英语${english} / 数学${math} / 408`, value: `${i + 1}${j + 1}408`,
})))

watch(() => user.token, async (token, _, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  tab.value = 'manual'
  profile.value = result.value = historyTask.value = undefined
  provinces.value = []
  history.value = []
  autoAvailable.value = submitting.value = historyLoading.value = historyError.value = false
  query.value = mockTotal.value = mockCombo.value = formError.value = ''
  Object.assign(form, emptyForm())
  if (!token) return
  await Promise.allSettled([
    getCurrentUser().then(data => { if (current) profile.value = data }),
    getSchoolOptions().then(data => { if (current) provinces.value = data.provinces }),
    learningStatus().then(data => { if (current) autoAvailable.value = data.enabled === true }),
  ])
}, { immediate: true })

watch(tab, value => { if (value === 'history') void loadHistory() })

async function loadHistory() {
  if (historyLoading.value) return
  const token = user.token
  historyLoading.value = true
  historyError.value = false
  try {
    const records = await getRecommendList()
    if (token === user.token) history.value = records
  } catch {
    if (token === user.token) historyError.value = true
  } finally {
    if (token === user.token) historyLoading.value = false
  }
}

async function generate() {
  if (submitting.value) return
  formError.value = ''
  const score = mockTotal.value.trim()
  if (score && (!/^\d{1,3}$/.test(score) || Number(score) > 500 || !mockCombo.value)) {
    formError.value = '请填写 0–500 的整数总分，并选择对应的科目组合。'
    return
  }
  const token = user.token
  submitting.value = true
  try {
    const task = await generateRecommend({
      query: query.value.trim() || '请比较符合条件的院校专业。',
      mockScore: score ? { total: Number(score), examCombo: mockCombo.value } : undefined,
      preferences: {
        majorCodes: form.majorCode ? [form.majorCode] : undefined,
        degreeType: form.degreeType || undefined,
        regions: form.regions.length ? form.regions : undefined,
        regionConstraint: form.regions.length ? form.regionConstraint : undefined,
        studyMode: form.studyMode || undefined,
        explainWithAi: form.explainWithAi,
      },
    })
    if (token !== user.token) return
    result.value = task
    await nextTick()
    if (tab.value === 'manual') resultSection.value?.scrollIntoView({ block: 'start' })
  } catch {
    // The request wrapper reports errors and ignores late results from an old session.
  } finally {
    if (token === user.token) submitting.value = false
  }
}

function taskLabel(task: Task) {
  if (task.status !== 'SUCCESS') return { FAILED: '处理失败', RUNNING: '处理中', PENDING: '等待处理', CANCELLED: '已取消' }[task.status]
  return { COMPLETED: '已生成', NEEDS_INPUT: '待补充条件', UNSUPPORTED: '暂无匹配候选' }[task.resultPayload?.outcome ?? 'COMPLETED']
}
</script>

<style scoped>
.recommendation-page { max-width: 1050px; }
.page-head, .history-head, .history-row, .actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.page-head, .history-head, .history-row { justify-content: space-between; }
.page-head { margin-bottom: 12px; }
.page-head h1, .pane h2 { margin: 0; }
.page-head p { margin: 8px 0 0; color: var(--c-ink-2); }
.pane { padding: clamp(14px, 3vw, 24px); }
.pane h2 { font-size: 18px; }
.result-pane { margin-top: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 16px; }
.form-grid .el-select { width: 100%; }
.extra { padding: 12px 0; border-top: 1px solid var(--c-line); }
.extra summary { cursor: pointer; font-weight: 600; }
.extra .el-form-item { margin-top: 10px; }
.muted { color: var(--c-ink-2); font-size: 13px; }
.error { color: var(--el-color-danger); }
.actions { margin-top: 8px; }
.history-row { padding: 10px 0; border-bottom: 1px solid var(--c-line); }
@media (max-width: 600px) { .form-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
