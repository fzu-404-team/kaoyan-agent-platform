import type { ScoreMatch } from '@/types/api'

/** score-match-v1 tier labels (see 搭建文档 按分数择校契约2026-11-19). */
export const TIER_LABELS: Record<ScoreMatch['tier'], string> = { REACH: '冲', MATCH: '稳', SAFE: '保' }

/** Prefixes a plus sign to positive differences, e.g. 20 → “+20”. */
export function signed(value: number): string {
  return value > 0 ? `+${value}` : String(value)
}

/** “2026年录取最低300／中位330，差+20” — the gap is the student's total minus the minimum. */
export function scoreMatchLine(match: ScoreMatch): string {
  return `${match.statYear}年录取最低${match.minScore}／中位${match.medianScore}，差${signed(match.gapToMin)}`
}
