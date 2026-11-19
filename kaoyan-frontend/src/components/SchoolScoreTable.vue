<template>
  <section class="score-table" aria-label="往年录取分数统计">
    <p class="score-notice">{{ notice || DEFAULT_NOTICE }}</p>
    <p v-if="total !== undefined && total > rows.length" class="score-count">共 {{ total }} 条，展示前 {{ rows.length }} 条。</p>
    <div class="score-scroll">
      <el-table :data="rows" stripe size="small">
        <el-table-column prop="year" label="年份" width="72" />
        <el-table-column label="学院 · 专业" min-width="220">
          <template #default="{ row }">
            <div>{{ row.majorName || '专业名称未登记' }}（{{ row.majorCode || '代码未登记' }}）</div>
            <div class="score-sub">{{ row.college || '学院未登记' }} · 科目 {{ row.examCombo }}</div>
          </template>
        </el-table-column>
        <el-table-column label="复试线" width="80"><template #default="{ row }">{{ show(row.retestLine) }}</template></el-table-column>
        <el-table-column label="最低" width="72"><template #default="{ row }">{{ show(row.minScore) }}</template></el-table-column>
        <el-table-column label="中位" width="72"><template #default="{ row }">{{ show(row.medianScore) }}</template></el-table-column>
        <el-table-column label="平均" width="80"><template #default="{ row }">{{ show(row.avgScore) }}</template></el-table-column>
        <el-table-column label="最高" width="72"><template #default="{ row }">{{ show(row.maxScore) }}</template></el-table-column>
        <el-table-column label="公布录取" width="84"><template #default="{ row }">{{ row.admittedCount }} 人</template></el-table-column>
        <el-table-column label="数据提示" min-width="180">
          <template #default="{ row }">
            <el-tag v-for="flag in row.flags" :key="flag" type="warning" size="small" class="score-flag">{{ flagLabel(flag) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { ScoreFlag, ScoreStatistic } from '@/types/api'

defineProps<{ rows: ScoreStatistic[]; notice?: string; total?: number }>()

const DEFAULT_NOTICE = '用户提供数据，经用户审核批准，非学校官网原文；公布录取数可能为多个专业共用的录取池，不能相加；往年数据不代表今后分数线。'
const FLAG_LABELS: Record<ScoreFlag, string> = {
  POSSIBLE_SAME_POOL: '可能与其他专业同一录取池',
  SAME_SCORES_DIFFERENT_CODES: '与其他专业代码分数完全相同',
  MAX_BELOW_MEDIAN: '最高分低于中位分',
  MIN_ABOVE_MEDIAN: '最低分高于中位分',
  AVG_OUT_OF_RANGE: '平均分超出范围',
  LINE_ABOVE_MIN: '复试线高于最低分',
}

/** Unknown flags from older snapshots still read as a warning, never as a code. */
function flagLabel(flag: string): string {
  return FLAG_LABELS[flag as ScoreFlag] ?? '数据待核对'
}

/** Missing values are shown as unrecorded, never as zero. */
function show(value: number | null): string {
  return value === null || value === undefined ? '未登记' : String(value)
}
</script>

<style scoped>
.score-table { min-width: 0; }
.score-notice { margin: 0 0 8px; color: var(--el-color-warning-dark-2); font-size: 13px; }
.score-count { margin: 0 0 8px; color: var(--el-text-color-secondary); font-size: 13px; }
.score-scroll { max-width: 100%; overflow-x: auto; }
.score-scroll :deep(.el-table) { min-width: 760px; }
.score-sub { color: var(--el-text-color-secondary); font-size: 12px; }
.score-flag { margin: 0 4px 4px 0; }
</style>
