import { describe, expect, it } from 'vitest'
import type { ReviewItem } from './api'
import { keyMoments, momentExplanation, reviewDisabledReason } from './reviewSummary'

const item = (ply: number, grade: ReviewItem['grade'], loss: number | null, side: ReviewItem['side'] = 'red'): ReviewItem => ({ ply, grade, loss_cp: loss, side, move: 'a3a4', label: '兵九进一', best_move: 'h2e2', best_label: '炮二平五', before_score: { type: 'cp', value: 0 }, after_score: { type: 'cp', value: -(loss ?? 0) }, pv: [] })
describe('lightweight review summary', () => {
  it('prioritizes the player, severity and loss, then fills from the opponent without mutating input', () => {
    const input = [item(1, 'inaccuracy', 40), item(3, 'mistake', 80), item(2, 'blunder', 300, 'black'), item(4, 'blunder', 220, 'black')]
    expect(keyMoments(input, 'red').map(i => i.ply)).toEqual([3, 1, 2])
    expect(input.map(i => i.ply)).toEqual([1, 3, 2, 4])
  })
  it('does not invent moments for good, unknown, repeated or unchanged recommendations', () => {
    const same = { ...item(5, 'blunder', 200), best_move: 'a3a4' }
    const missing = { ...item(7, 'mistake', 90), best_move: null }
    expect(keyMoments([item(1, 'good', 0), item(2, 'unknown', null), item(3, 'mistake', 80), item(3, 'mistake', 80), same, missing], 'watch').map(i => i.ply)).toEqual([3])
  })
  it('never presents mate as cp or as a rule-confirmed terminal result', () => {
    const mate = { ...item(1, 'blunder', 999), after_score: { type: 'mate' as const, value: -3 } }
    expect(momentExplanation(mate)).not.toContain('cp')
    expect(momentExplanation(mate)).toContain('引擎')
    expect(momentExplanation(mate)).not.toContain('棋局结束')
  })
  it('blocks invalid review states and accepts the 120-ply boundary', () => {
    const ready = { setup: false, thinking: false, engineReady: true, plies: 120 }
    expect(reviewDisabledReason(ready)).toBe('')
    for (const change of [{ setup: true }, { thinking: true }, { engineReady: false }, { plies: 0 }, { plies: 121 }]) expect(reviewDisabledReason({ ...ready, ...change })).not.toBe('')
  })
})
