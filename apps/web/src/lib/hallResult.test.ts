import { describe, expect, it } from 'vitest'
import { hallResultLabel, terminationLabel } from './hallResult'

describe('hall result presentation', () => {
  it('shows wins and losses from either user side without guessing old records', () => {
    expect(hallResultLabel('red_win', 'red')).toBe('你获胜')
    expect(hallResultLabel('red_win', 'black')).toBe('AI 棋友获胜')
    expect(hallResultLabel('black_win', 'black')).toBe('你获胜')
    expect(hallResultLabel('draw', 'red')).toBe('和棋')
    expect(hallResultLabel('red_win')).toBe('红胜')
    expect(hallResultLabel(null)).toBe('进行中')
  })
  it('explains rule endings and preserves uncertainty for missing reasons', () => {
    expect(terminationLabel('checkmate')).toBe('将死')
    expect(terminationLabel('stalemate')).toBe('困毙')
    expect(terminationLabel('rule_draw')).toBe('规则性和棋')
    expect(terminationLabel('resignation')).toBe('主动认输')
    expect(terminationLabel(null)).toBe('')
    expect(terminationLabel('future_reason')).toBe('其他结束原因')
  })
})
