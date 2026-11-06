import type { ReviewItem } from './api'

export type ReviewSide = 'red' | 'black' | 'watch'
export const reviewGradeNames: Record<ReviewItem['grade'], string> = { good: '正常 / 好棋', inaccuracy: '可改进', mistake: '失误', blunder: '严重失误', unknown: '无法判断' }

export function keyMoments(items: ReviewItem[], side: ReviewSide): ReviewItem[] {
  const severity = { good: 0, unknown: 0, inaccuracy: 1, mistake: 2, blunder: 3 }
  const sorted = items.filter(item => severity[item.grade] > 0 && item.best_move && item.best_label && item.best_move !== item.move)
    .sort((a, b) => Number(b.side === side) - Number(a.side === side) || severity[b.grade] - severity[a.grade] || (b.loss_cp ?? 0) - (a.loss_cp ?? 0) || a.ply - b.ply)
  return sorted.filter((item, index) => sorted.findIndex(other => other.ply === item.ply) === index).slice(0, 3)
}

export function momentExplanation(item: ReviewItem): string {
  if (item.before_score?.type === 'mate' || item.after_score?.type === 'mate') return '这步涉及引擎预测的将杀变化，建议先比较推荐走法，不能用普通分值衡量得失。'
  if (item.loss_cp !== null) return `这步让${item.side === 'red' ? '红方' : '黑方'}的引擎评估下降了 ${item.loss_cp} cp，优先考虑${item.best_label ?? '推荐走法'}来保留更好的局面。`
  return '这步的得失无法可靠量化，可以先比较引擎推荐走法再判断。'
}

export function reviewDisabledReason(state: { setup: boolean; thinking: boolean; engineReady: boolean; plies: number }): string {
  if (state.setup) return '请先完成或退出摆棋'
  if (state.thinking) return '请等待引擎完成思考'
  if (!state.plies) return '走出第一步后即可复盘'
  if (state.plies > 120) return '棋谱超过 120 个半回合，暂不能整局复盘'
  if (!state.engineReady) return '请先连接 Pikafish 引擎'
  return ''
}
