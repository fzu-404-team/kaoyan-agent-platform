<template>
  <ul class="programs">
    <li v-for="program in programs" :key="program.programId" class="program">
      <div class="program-head">
        <h3>
          <el-tag v-if="program.scoreMatch" :type="TIER_TAG_TYPES[program.scoreMatch.tier]" size="small" effect="plain" class="tier">
            {{ TIER_LABELS[program.scoreMatch.tier] }}
          </el-tag>
          {{ program.school }}
        </h3>
        <span>{{ program.region || '地区未登记' }} · {{ studyModeLabel(program.studyMode) }}</span>
      </div>
      <p>{{ program.college }} · {{ program.major }}（{{ program.majorCode }}）</p>
      <p class="muted">
        {{ program.year }} 年 · {{ program.degreeType === 'academic' ? '学硕' : '专硕' }}
        <template v-if="program.examSubjects.length"> · 初试 {{ program.examSubjects.join(' / ') }}</template>
      </p>
      <p v-if="program.track || program.admissionCategory === 'special'" class="muted">
        <template v-if="program.track">{{ program.track }}</template>
        <template v-if="program.track && program.admissionCategory === 'special'"> · </template>
        <template v-if="program.admissionCategory === 'special'">专项资格待核对</template>
      </p>
      <p v-if="program.scoreMatch" class="score">{{ scoreMatchLine(program.scoreMatch) }}</p>
      <p v-else-if="scores[program.programId]" class="score">
        {{ scores[program.programId].year }} 年参考复试线 {{ scores[program.programId].retestLine }} 分
        <span v-if="scores[program.programId].gap != null"> · 模考分差 {{ signed(scores[program.programId].gap!) }} 分</span>
      </p>
      <!-- Evidence level stays accurate but low-key: shown inside the folded notes. -->
      <details v-if="evidenceLabel(program) || ('explanation' in program && (program.citationSupport || extraChecks(program).length))">
        <summary>项目说明</summary>
        <template v-if="'explanation' in program">
          <p v-if="program.citationSupport">{{ program.explanation }}</p>
          <p v-for="check in extraChecks(program)" :key="check">{{ check }}</p>
        </template>
        <p v-if="evidenceLabel(program)" class="muted">资料等级：{{ evidenceLabel(program) }}</p>
      </details>
    </li>
  </ul>
</template>

<script setup lang="ts">
import type { RecommendationScoreReference, SchoolCandidate, SchoolCatalogCandidate, ScoreMatch } from '@/types/api'
import { TIER_LABELS, scoreMatchLine, signed } from '@/utils/score-match'

const TIER_TAG_TYPES: Record<ScoreMatch['tier'], 'danger' | 'primary' | 'success'> = {
  REACH: 'danger', MATCH: 'primary', SAFE: 'success',
}

defineProps<{
  programs: (SchoolCandidate | SchoolCatalogCandidate)[]
  scores: Record<string, RecommendationScoreReference>
}>()

function extraChecks(program: SchoolCandidate) {
  return program.pendingChecks.filter(check => check !== '报考资格、方向及最新调整请核对招生章程；未据本科背景推定资格')
}

const LEVEL_LABELS = {
  OFFICIAL_VERIFIED: '官方文件已复核',
  CATALOG_CHECKED: '此前已核对目录，待官网确认',
  USER_APPROVED: '目录批量入库，待官网核实',
  SCORE_HISTORY: '仅有往年录取统计，今年招生未核实',
} as const

function evidenceLabel(program: SchoolCandidate | SchoolCatalogCandidate) {
  if ('evidenceLevel' in program && program.evidenceLevel) return LEVEL_LABELS[program.evidenceLevel]
  if ('catalogReview' in program && program.catalogReview) return LEVEL_LABELS[program.catalogReview]
  // Older formal candidates have neither field and were all officially verified.
  return 'matchedConditions' in program ? LEVEL_LABELS.OFFICIAL_VERIFIED : ''
}

function studyModeLabel(mode: string) {
  return { part_time: '非全日制', full_time: '全日制' }[mode] ?? '学习方式未知'
}
</script>

<style scoped>
.programs { list-style: none; padding: 0; margin: 10px 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.program { padding: 12px 14px; border: 1px solid var(--c-line); border-radius: 10px; overflow-wrap: anywhere; }
.program-head { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 4px 10px; }
.program h3, .program p { margin: 0; }
.program h3 { font-size: 16px; }
.tier { margin-right: 6px; vertical-align: 2px; }
.program p, details { margin-top: 6px; line-height: 1.5; }
.program-head span, .muted { color: var(--c-ink-2); font-size: 13px; }
.score { color: var(--c-primary); font-weight: 600; font-size: 13px; }
summary { cursor: pointer; }
@media (max-width: 680px) { .programs { grid-template-columns: minmax(0, 1fr); } }
</style>
