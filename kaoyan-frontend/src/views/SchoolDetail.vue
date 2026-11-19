<template>
  <div class="page">
    <el-page-header @back="router.push('/schools')" title="返回院校库" />
    <div v-if="loading" class="loading-state" v-loading="true" role="status" aria-label="正在加载院校信息">正在加载院校信息…</div>
    <el-result v-else-if="error" icon="warning" :title="error" sub-title="请重试，或返回院校库选择其他院校。">
      <template #extra>
        <el-button v-if="!notFound" type="primary" @click="load">重试加载</el-button>
        <el-button @click="router.push('/schools')">返回院校库</el-button>
      </template>
    </el-result>
    <template v-else-if="detail">
    <el-alert title="招生计划优先展示统考名额；含推免、专业合计及第三方数据均单独标注。往年复试线仅供参考，不代表2027年分数线；缺失值不代表零。专业信息的核验状态仍以备注为准。" type="warning" :closable="false" />
    <el-alert v-for="message in warningMessages" :key="message" :title="message" type="warning" :closable="false" />
    <div class="card hero">
      <div class="hero-icon">{{ detail.school?.name?.[0] }}</div>
      <div>
        <h2 class="hero-name">{{ detail.school?.name }}</h2>
        <p class="hero-meta">{{ detail.school?.province }} · {{ detail.school?.level || '层次未登记' }}</p>
      </div>
    </div>

    <h3 class="sec-title">招生专业信息</h3>
    <el-empty v-if="!detail.details.length" description="该院校暂无已收录的招生专业信息" />
    <!-- 手机：每条专业一张卡片，优先露出专业、年份、招生计划与复试参考线，其余字段展开查看 -->
    <template v-else-if="isMobile">
      <p class="mobile-hint">优先展示专业、年份、招生计划与复试参考线；展开「其余字段」查看专业代码、学院／方向与备注。</p>
      <article v-for="row in detail.details" :key="row.id" class="card major-card">
        <header class="major-head">
          <h4 class="major-name">{{ row.majorName }}</h4>
          <el-tag size="small" type="info" effect="plain">{{ row.year }}年</el-tag>
        </header>
        <SchoolMetric class="major-metric" :metric="row.admissionMetrics?.enrollment" kind="enrollment" :legacy-value="row.enrollmentCount" :legacy-year="row.year" />
        <SchoolMetric class="major-metric" :metric="row.admissionMetrics?.cutoffReference" kind="cutoff" :legacy-value="row.scoreLine" :legacy-year="row.year" />
        <details class="major-more">
          <summary>其余字段：专业代码、学院／方向、备注</summary>
          <dl class="major-fields">
            <dt>专业代码</dt><dd>{{ row.majorCode || '未登记' }}</dd>
            <template v-if="row.admissionMetrics">
              <dt>学院</dt><dd>{{ row.admissionMetrics.college || '学院待核实' }}</dd>
              <dt>方向</dt><dd>{{ row.admissionMetrics.track || '方向未登记' }}</dd>
              <dt>学习方式</dt><dd>{{ studyModeLabel(row.admissionMetrics.studyMode) }}</dd>
              <dt>招考类别</dt><dd>{{ categoryLabel(row.admissionMetrics.admissionCategory) }}</dd>
            </template>
            <template v-else>
              <dt>学院／方向</dt><dd>见原始备注</dd>
            </template>
            <dt>备注</dt><dd class="major-remark">{{ row.remark || '无' }}</dd>
          </dl>
        </details>
      </article>
    </template>
    <div v-else class="card">
      <el-table :data="detail.details || []" stripe>
        <el-table-column prop="majorName" label="专业" min-width="180" />
        <el-table-column prop="majorCode" label="专业代码" width="120" />
        <el-table-column prop="year" label="年份" width="100" />
        <el-table-column label="学院／方向" min-width="200">
          <template #default="scope">
            <template v-if="scope.row.admissionMetrics">
              <div>{{ scope.row.admissionMetrics.college || '学院待核实' }}</div>
              <div>{{ scope.row.admissionMetrics.track || '方向未登记' }}</div>
              <div class="program-context">{{ studyModeLabel(scope.row.admissionMetrics.studyMode) }} · {{ categoryLabel(scope.row.admissionMetrics.admissionCategory) }}</div>
            </template>
            <span v-else>见原始备注</span>
          </template>
        </el-table-column>
        <el-table-column label="招生计划与口径" min-width="260"><template #default="scope"><SchoolMetric :metric="scope.row.admissionMetrics?.enrollment" kind="enrollment" :legacy-value="scope.row.enrollmentCount" :legacy-year="scope.row.year" /></template></el-table-column>
        <el-table-column label="往年复试参考线" min-width="260"><template #default="scope"><SchoolMetric :metric="scope.row.admissionMetrics?.cutoffReference" kind="cutoff" :legacy-value="scope.row.scoreLine" :legacy-year="scope.row.year" /></template></el-table-column>
        <el-table-column prop="remark" label="备注" min-width="420" />
      </el-table>
    </div>

    <template v-if="detail.scoreStatistics">
      <div class="score-title">
        <h3 class="sec-title">往年录取分数统计</h3>
      </div>
      <el-empty v-if="!detail.scoreStatistics.length" description="该院校暂无录取分数统计" />
      <div v-else class="card score-card"><SchoolScoreTable :rows="detail.scoreStatistics" /></div>
    </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import axios from 'axios'
import { useRoute, useRouter } from 'vue-router'
import { getSchoolDetail } from '@/api/school'
import type { SchoolDetailVO } from '@/api/school'
import SchoolMetric from '@/components/SchoolMetric.vue'
import SchoolScoreTable from '@/components/SchoolScoreTable.vue'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const detail = ref<SchoolDetailVO | null>(null)
const error = ref('')
const notFound = ref(false)
const user = useUserStore()
const mobileQuery = window.matchMedia('(max-width: 640px)')
const isMobile = ref(mobileQuery.matches)
const onViewportChange = (event: MediaQueryListEvent) => { isMobile.value = event.matches }
mobileQuery.addEventListener('change', onViewportChange)
let active: AbortController | undefined
let sequence = 0
const warningMessages = computed(() => [...new Set(detail.value?.warnings?.map(item => item.message) ?? [])])
function studyModeLabel(mode: string): string {
  return ({ full_time: '全日制', part_time: '非全日制' } as Record<string, string>)[mode] || '学习方式待核实'
}
function categoryLabel(category: string): string {
  return ({ ordinary: '普通统考', recommended: '推免', special: '专项' } as Record<string, string>)[category] || '招考类别待核实'
}

async function load() {
  const current = ++sequence
  active?.abort()
  const controller = new AbortController()
  active = controller
  detail.value = null
  error.value = ''
  notFound.value = false
  loading.value = true
  try {
    const id = Number(route.params.id)
    if (!Number.isSafeInteger(id) || id <= 0) {
      notFound.value = true
      error.value = '院校不存在'
      return
    }
    const result = await getSchoolDetail(id, controller.signal)
    if (current === sequence) detail.value = result
  } catch (cause) {
    if (current !== sequence || axios.isCancel(cause)) return
    notFound.value = axios.isAxiosError(cause) && cause.response?.status === 404
    error.value = notFound.value ? '院校不存在' : axios.isAxiosError(cause) && cause.code === 'ECONNABORTED'
      ? '院校信息加载超时，请稍后重试' : '院校信息加载失败'
  } finally {
    if (current === sequence) loading.value = false
  }
}
watch([() => route.params.id, () => user.token], () => { void load() }, { immediate: true })
onBeforeUnmount(() => { sequence++; active?.abort(); mobileQuery.removeEventListener('change', onViewportChange) })
</script>

<style scoped>
.hero { display: flex; align-items: center; gap: 16px; padding: 24px; margin: 16px 0; }
.hero-icon {
  width: 56px; height: 56px; border-radius: 12px;
  background: var(--c-primary-light); color: var(--c-primary);
  display: grid; place-items: center; font-weight: 700; font-size: 22px;
}
.hero-name { margin: 0; font-size: 20px; }
.hero-meta { margin: 4px 0 0; color: var(--c-ink-2); }
:deep(.el-table__cell) { vertical-align: top; }
:deep(.el-table .cell) { overflow-wrap: anywhere; }
.sec-title { font-size: 15px; font-weight: 600; margin: 0 0 12px; }
.program-context { color: var(--c-ink-2); font-size: 13px; }
.card { min-width: 0; overflow: hidden; }
.score-title { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; margin: 24px 0 12px; }
.score-title .sec-title { margin: 0; }
.score-card { padding: 16px; }
.loading-state { position: relative; min-height: 160px; padding: 24px; }
.mobile-hint { margin: 0 0 12px; color: var(--c-ink-2); font-size: 13px; line-height: 1.6; }
.major-card { display: grid; gap: 10px; padding: 14px; margin-bottom: 12px; }
.major-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.major-name { margin: 0; font-size: 15px; line-height: 1.5; overflow-wrap: anywhere; }
.major-head .el-tag { flex-shrink: 0; }
.major-metric { border-top: 1px dashed var(--c-line); padding-top: 10px; }
.major-more summary { cursor: pointer; color: var(--c-primary); font-size: 13px; font-weight: 600; }
.major-fields { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; margin: 10px 0 0; font-size: 13px; }
.major-fields dt { color: var(--c-ink-2); white-space: nowrap; }
.major-fields dd { margin: 0; overflow-wrap: anywhere; line-height: 1.6; }
.major-remark { color: var(--c-ink-2); }
@media (max-width: 640px) {
  .page { padding: 16px 12px; }
  .hero { padding: 16px; margin: 12px 0; }
  .hero-name { font-size: 18px; }
}
</style>
