<template>
  <section class="task-result" aria-live="polite">
    <el-alert v-if="task.status === 'FAILED'" type="error" :closable="false" :title="task.errorMessage || '任务失败，请稍后重试'" />
    <el-alert v-else-if="task.status === 'CANCELLED'" type="info" :closable="false" title="已停止生成" />
    <template v-else-if="result">
      <div v-if="task.status === 'SUCCESS'" class="export-actions">
        <ExportButton :source="{ source: 'TASK_RESULT', taskId: task.id, part: 'ANSWER' }" label="导出回答" />
        <ExportButton v-if="result.studyPlan" :source="{ source: 'TASK_RESULT', taskId: task.id, part: 'STUDY_PLAN' }" label="导出复习计划" />
        <ExportButton v-if="result.documentProposal" :source="{ source: 'TASK_RESULT', taskId: task.id, part: 'NOTE_PROPOSAL' }" label="导出笔记建议" />
      </div>
      <section v-if="result.sections?.length" class="expert-sections" aria-label="分项处理结果">
        <p v-if="result.partial">部分事项已完成，其他事项请查看下方提示。</p>
        <ul>
          <li v-for="item in result.sections" :key="item.agent">
            <strong>{{ expertLabels[item.agent] }}</strong> · {{ sectionOutcomeLabels[item.outcome] }} · {{ modeLabels[item.explanationMode] }}<template v-if="fallbackReasonLabel(item.fallbackReason)">（{{ fallbackReasonLabel(item.fallbackReason) }}）</template>
            <p v-if="item.notice">{{ item.notice }}</p>
          </li>
        </ul>
      </section>
      <div v-if="!legacyAdmission && result.outcome !== 'COMPLETED'" class="meta">
        <el-tag>{{ result.retrievalStatus && retrievalLabels[result.retrievalStatus] || outcomeLabels[result.outcome] }}</el-tag>
      </div>
      <p v-if="result.resolvedTaskType === 'WRONG_QUESTION_TUTOR'" class="tutor-mode">{{ result.explanationMode === 'ai' ? 'AI解释' : result.explanationMode === 'fallback' ? 'AI降级 · 原题解析' : '原题解析' }}</p>
      <p v-if="result.resolvedTaskType === 'WRONG_QUESTION_TUTOR'" class="answer">{{ result.answer }}</p>
      <p v-if="result.resolvedTaskType === 'WRONG_QUESTION_TUTOR'" class="saved-result">已保存作答 · 题目版本 {{ result.questionVersion }} · 你的选择 {{ result.userAnswer }} · 标准答案 {{ result.standardAnswer }}</p>
      <SafeMarkdown v-if="result.resolvedTaskType !== 'WRONG_QUESTION_TUTOR'" :navigation="navigation" :content="displayAnswer" :allowed-urls="answerUrls" />
      <SchoolCatalogView v-if="!legacyAdmission && result.schoolCatalog" :catalog="result.schoolCatalog" />
      <AdmissionLinksView v-if="links" :links="links" />
      <section v-if="result.studyPlan" class="study-plan" aria-label="复习安排">
        <h3>每日安排（{{ result.studyPlan.days.length }}天）</h3>
        <p v-for="(basis, index) in result.studyPlan.basis" :key="`basis-${index}`">{{ basis }}</p>
        <details v-for="day in result.studyPlan.days" :key="day.day" :open="result.studyPlan.days.length <= 7 || day.day === 1">
          <summary>第 {{ day.day }} 天 · {{ day.topic }}</summary>
          <ul><li v-for="(item, index) in day.tasks" :key="index">{{ item }}</li></ul>
        </details>
        <p class="muted">这是可调整的学习建议，不会自动创建练习或保存笔记。</p>
      </section>
      <div v-if="citation?.checked" class="grounding">
        <el-tag size="small" :type="citationType(citation?.status)">{{ citationLabel(citation?.status) }}</el-tag>
        <span class="muted">引用支持度 {{ Math.round((citation?.ratio ?? 0) * 100) }}%（{{ citation?.supported ?? 0 }}/{{ citation?.checked ?? 0 }} 条结论）</span>
        <details v-if="citation?.items?.length" class="claim-list">
          <summary>逐条结论与来源（{{ citation?.supported ?? 0 }}/{{ citation?.checked ?? 0 }} 条已核实）</summary>
          <ul>
            <li v-for="(item, index) in citation?.items ?? []" :key="index">
              <el-tag size="small" :type="item.supported ? 'success' : 'danger'">{{ item.supported ? '已核实' : '未核实' }}</el-tag>
              <span>{{ item.text }}</span>
              <span v-if="item.sourceIds?.length" class="muted">（{{ item.sourceIds.map(sourceLabel).join('、') }}）</span>
              <span v-if="item.reason" class="muted">· {{ reasonLabel(item.reason) }}</span>
            </li>
          </ul>
        </details>
        <details v-else-if="citation?.unsupported?.length">
          <summary>未充分核实的结论（{{ citation?.unsupported?.length }}）</summary>
          <ul><li v-for="(item, index) in citation?.unsupported ?? []" :key="index">{{ item.text }}<span class="muted">（{{ reasonLabel(item.reason) }}）</span></li></ul>
        </details>
      </div>
      <component :is="practice ? 'details' : 'div'" v-if="result.evidence?.length" class="source"><summary v-if="practice">学习依据（{{ result.evidence.length }}）</summary><strong v-else>学习依据</strong><p v-for="item in result.evidence" :key="item.ref"><router-link v-if="resourceRoute(item.resource)" :to="resourceRoute(item.resource)!">{{ item.ref }} · {{ item.title }}</router-link><span v-else>{{ item.ref }} · {{ item.title }}</span> · {{ item.locator || '原文位置未记录' }} · {{ item.version || '版本未记录' }}<template v-if="item.matchMethod"><br><span class="match-label">{{ item.matchMethod === 'LABEL' ? '知识点匹配' : '语义相关' }} · {{ item.matchTopic }}</span><br>{{ item.summary }}</template></p></component>
      <nav v-if="navigation.length" class="navigation-links" aria-label="相关功能入口"><router-link v-for="item in navigation" :key="item.target" :to="item.path" class="navigation-link">前往{{ item.label }}</router-link></nav>
      <el-alert v-if="!legacyAdmission && (result.notice || result.explanationMode === 'fallback')" type="warning" :closable="false" :title="result.notice || 'AI解释暂不可用，已保留资料与规则结果。'" :description="fallbackReasonLabel(result.fallbackReason) && `原因：${fallbackReasonLabel(result.fallbackReason)}`" />
      <ul v-if="!legacyAdmission && followUp.length"><li v-for="item in followUp" :key="item">{{ item }}</li></ul>
      <template v-if="compactRecommendation && hasRecommendation">
        <RecommendationCandidateList v-if="result.candidates?.length" :programs="result.candidates" :scores="scoreReferences" />
        <p v-if="result.scoreFilter" class="muted">{{ result.scoreFilter.notice }}</p>
        <p class="muted">报考资格及最新调整请核对当年招生章程。</p>
        <p class="muted">
          {{ result.scoreReferences?.length
            ? '历史复试线来自用户提供并经用户审核批准的统计。方向、学习方式和统考口径仍需核对。'
            : '本批候选暂无可用的历史复试总分线。' }}
        </p>
        <details v-if="result.unverifiedCandidates?.length" :open="!result.candidates?.length" class="recommendation-detail">
          <summary>目录线索（{{ result.unverifiedCandidates.length }} 项）</summary>
          <p v-if="catalogSummary" class="muted">{{ catalogSummary }}</p>
          <RecommendationCandidateList :programs="result.unverifiedCandidates" :scores="scoreReferences" />
        </details>
      </template>
      <template v-else>
        <article v-for="(candidate, index) in result.candidates" :key="candidate.programId" class="candidate">
        <h3>{{ index + 1 }}. <template v-if="candidate.scoreMatch">【{{ TIER_LABELS[candidate.scoreMatch.tier] }}】</template>{{ candidate.school }} · {{ candidate.major }}</h3>
        <p>{{ candidate.college }} · {{ candidate.year }}年 · {{ candidate.degreeType === 'academic' ? '学硕' : '专硕' }} · {{ candidate.region }}</p>
        <p v-if="candidate.scoreMatch" class="muted">{{ scoreMatchLine(candidate.scoreMatch) }}</p>
        <p>初试科目代码：{{ candidate.examSubjects.join(' / ') }}</p>
        <div><el-tag v-for="condition in candidate.matchedConditions" :key="condition" size="small">{{ condition }}</el-tag></div>
        <p class="answer">{{ candidate.explanation }}</p>
        <p v-for="check in candidate.pendingChecks" :key="check" class="muted">待确认：{{ check }}</p>
        </article>
        <p v-if="result.scoreFilter" class="muted">{{ result.scoreFilter.notice }}</p>
      </template>
      <component :is="compactRecommendation ? 'details' : 'div'" v-if="result.learningSnapshot || historicalComparisons.length" :class="{ 'recommendation-detail': compactRecommendation }">
        <summary v-if="compactRecommendation">学情与历史 408 单科对照</summary>
        <div v-if="result.learningSnapshot" class="source">
          <p>
            画像版本 {{ result.learningSnapshot.profileRevision }} · 蓝图覆盖 {{ Math.round(result.learningSnapshot.coverage * 100) }}%
            <template v-if="!compactRecommendation"> · {{ result.triggerReason === 'MANUAL' ? '手动生成' : '随学情或条件更新' }}</template>
          </p>
          <p>408 实验性参考分：{{ result.learningSnapshot.referenceScore ?? '证据不足' }}，未经整卷校准。</p>
        </div>
        <p v-if="compactRecommendation && !historicalComparisons.length" class="muted">暂无可比的历史 408 单科线。</p>
        <div v-for="comparison in historicalComparisons" :key="comparison.programId" class="source">
          <p>{{ compactRecommendation ? candidateNames[comparison.programId] || comparison.programId : comparison.programId }} · {{ comparison.year ? `${comparison.year}年408单科线：${comparison.score}` : '暂无可比资料' }}<span v-if="comparison.gap != null"> · 实验性参考差值 {{ comparison.gap }}</span></p>
          <p v-if="!compactRecommendation">{{ comparison.notice }}</p>
          <a v-if="comparison.source && safeUrl(comparison.source.url)" :href="safeUrl(comparison.source.url)" target="_blank" rel="noopener noreferrer">{{ comparison.source.title }} · {{ comparison.source.locator }}</a>
        </div>
      </component>
      <p v-if="result.accuracy !== undefined">本次有效作答正确率：{{ result.accuracy }}%（不代表考试能力）</p>
      <p v-if="result.weakPoints?.length">本次错题涉及：{{ result.weakPoints.join('、') }}</p>
      <details v-if="result.references?.length" :open="!compactRecommendation && !hasRecommendation" :class="{ 'recommendation-detail': compactRecommendation }">
        <summary>查看依据（{{ result.references.length }}）</summary>
        <div v-for="source in result.references" :key="source.id" class="source">
          <a v-if="safeUrl(source.url)" :href="safeUrl(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }}</a>
          <strong v-else>{{ source.title }}</strong>
          <p>{{ source.locator }} · {{ source.version }} · 核验 {{ source.retrievedAt }}</p>
          <p>{{ source.excerpt }}</p>
        </div>
      </details>
    </template>
    <template v-else-if="task.resultPayload">
      <el-alert type="warning" :closable="false" title="旧格式历史记录，未经过本轮来源校验，仅供回顾" />
      <pre class="answer">{{ JSON.stringify(task.resultPayload, null, 2) }}</pre>
    </template>
    <el-empty v-else description="处理中，请稍后刷新任务历史" />
  </section>
</template>
<script setup lang="ts">
import ExportButton from './ExportButton.vue'
import AdmissionLinksView from './AdmissionLinksView.vue'
import SchoolCatalogView from './SchoolCatalogView.vue'
import RecommendationCandidateList from './RecommendationCandidateList.vue'
import { computed } from 'vue'
import { resultNavigation } from '@/utils/assistant-navigation'
import { useUserStore } from '@/stores/user'
import type { Task } from '@/types/api'
import SafeMarkdown from '@/components/SafeMarkdown.vue'
import { resourceRoute, safeSourceUrl } from '@/utils/assistant-resource'
import { fallbackReasonLabel } from '@/utils/fallback-reason'
import { TIER_LABELS, scoreMatchLine } from '@/utils/score-match'
import { ADMISSION_LEGACY_NO_LINK, ADMISSION_SAFE_ANSWER, ADMISSION_LINK_UNVERIFIED, legacyLinks, projectLinks, registeredAdmissionUrls } from '@/utils/admission-links'
const props = defineProps<{ task: Task; compactRecommendation?: boolean }>()
const result = computed(() => {
  const value = props.task.resultPayload
  return value && ((value.outcome && value.explanationMode) || value.admissionLinks || value.admissionCheck) ? value : null
})
const legacyAdmission = computed(() => Boolean(props.task.resultPayload?.admissionCheck))
const links = computed(() => projectLinks(result.value?.admissionLinks) ?? legacyLinks(result.value?.admissionCheck))
const hasRecommendation = computed(() => Boolean(result.value?.candidates?.length || result.value?.unverifiedCandidates?.length))
const scoreReferences = computed(() => Object.fromEntries((result.value?.scoreReferences ?? []).map(item => [item.programId, item])))
const candidateNames = computed(() => Object.fromEntries((result.value?.candidates ?? []).map(item => [item.programId, item.school])))
const historicalComparisons = computed(() => (result.value?.historicalComparisons ?? [])
  .filter(item => !props.compactRecommendation || item.year != null))
const catalogSummary = computed(() => result.value?.unverifiedCandidates?.length
  ? result.value.answer.split('\n').find(line => line.startsWith('院校目录中有'))
  : undefined)
const displayAnswer = computed(() => {
  if (!result.value) return ''
  if (legacyAdmission.value) return links.value ? ADMISSION_SAFE_ANSWER : ADMISSION_LEGACY_NO_LINK
  if (result.value.admissionLinks && !links.value) return ADMISSION_LINK_UNVERIFIED
  if (result.value.admissionLinks && !result.value.candidates?.length && !result.value.schoolCatalog) return ADMISSION_SAFE_ANSWER
  if (props.compactRecommendation && catalogSummary.value) {
    // The legacy catalog bullets repeat the structured entries below.
    const lines = result.value.answer.split('\n')
    const first = lines.indexOf(catalogSummary.value)
    let last = first + 1
    while (lines[last]?.startsWith('- ')) last++
    lines.splice(first, last - first)
    return lines.join('\n').trim()
  }
  return result.value.answer
})
const answerUrls = computed(() => [
  ...(result.value?.references ?? []).map(source => source.url).filter(url => Boolean(safeUrl(url))),
  ...registeredAdmissionUrls(),
])
const followUp = computed(() => (result.value?.followUp ?? [])
  .filter(item => !props.compactRecommendation || !displayAnswer.value.includes(item)))
const user = useUserStore()
const navigation = computed(() => result.value ? resultNavigation(result.value, user.isAdmin) : [])
const practice = computed(() => result.value?.actions?.some(action => action.type === 'PRACTICE_CREATE'))
const outcomeLabels = { COMPLETED: '已完成', NEEDS_INPUT: '需补充条件', UNSUPPORTED: '资料未覆盖' }
const expertLabels = { LEARNING: '学情分析', SCHOOL: '院校比较', KNOWLEDGE: '知识辅导', PRACTICE: '练习建议', NOTE: '笔记建议', STUDY_PLAN: '复习安排' }
const sectionOutcomeLabels = { COMPLETED: '已完成', NEEDS_INPUT: '需补充条件', UNSUPPORTED: '未完成' }
const modeLabels = { rules: '规则结果', ai: 'AI解释', fallback: '已降级' }
const retrievalLabels = { READY: '', BUILDING: '题目索引准备中', BUSY: '题目索引准备中', FAILED: '题目索引构建失败', UNAVAILABLE: '题目检索暂不可用' }
const citation = computed(() => result.value?.citationSupport)
const sourceLabels = computed(() => {
  const labels: Record<string, string> = {}
  ;(result.value?.references ?? []).forEach((reference, index) => { labels[reference.id] = `S${index + 1}` })
  return labels
})
const citationLabels: Record<string, string> = {
  SUPPORTED: '引用已核实', PARTIAL: '部分引用待核对', UNSUPPORTED: '引用未通过核对', NOT_CHECKED: '未做引用核对',
}
const reasonLabels: Record<string, string> = {
  low_overlap: '与原文重合不足', no_overlap: '原文无对应内容', number_mismatch: '数字与原文不一致',
  unknown_source: '引用编号无效', empty_claim: '空结论', missing_excerpt: '原文缺失', polarity_mismatch: '结论与原文的肯定或否定相反',
}
function citationType(status?: string): 'success' | 'warning' | 'danger' | 'info' {
  return status === 'SUPPORTED' ? 'success' : status === 'PARTIAL' ? 'warning' : status === 'UNSUPPORTED' ? 'danger' : 'info'
}
function citationLabel(status?: string) { return status ? citationLabels[status] || status : '未做引用核对' }
function reasonLabel(reason: string) { return reasonLabels[reason] || reason }
function sourceLabel(id: string) { return sourceLabels.value[id] || id }
function safeUrl(value: string) { return safeSourceUrl(value) }
</script>
<style scoped>
.export-actions { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 }.export-actions :deep(.el-button) { margin:0 }
.navigation-links { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 }
.navigation-link { border:1px solid var(--c-line); border-radius:6px; padding:4px 10px; text-decoration:none }
summary { cursor:pointer }
.match-label { display:inline-block; margin:4px 0; padding:2px 6px; border:1px solid var(--c-line); border-radius:4px; color:var(--c-primary); background:var(--c-primary-light); font-size:12px; white-space:normal }
.task-result { overflow-wrap: anywhere; }
.meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.grounding { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
.grounding details { width: 100%; }
.grounding ul { margin: 6px 0 0; padding-left: 20px; font-size: 13px; }
.claim-list li { margin: 6px 0; line-height: 1.6; }
.answer { white-space: pre-wrap; line-height: 1.8; }
.candidate, .source { padding: 16px; border: 1px solid var(--c-line); border-radius: 10px; margin: 14px 0; }
.candidate h3 { margin: 0 0 10px; }
.candidate .el-tag { margin: 0 6px 6px 0; }
.source p, .muted { color: var(--c-ink-2); font-size: 13px; }
.recommendation-detail { padding: 9px 0; border-top: 1px solid var(--c-line); }
summary { cursor: pointer; font-weight: 600; }
</style>
