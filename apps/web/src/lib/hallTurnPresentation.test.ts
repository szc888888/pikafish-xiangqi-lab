import { describe, expect, it } from 'vitest'
import { optimisticHallUserMove } from './hallTurnPresentation'

describe('cloud hall turn presentation', () => {
  it('shows the user move immediately on the first request', () => {
    expect(optimisticHallUserMove(['a3a4'], 'h7e7', 'turn-1', null, null)).toEqual({
      moves: ['a3a4', 'h7e7'],
      pendingTurnId: 'turn-1',
      pendingUserUci: 'h7e7',
    })
  })

  it('does not duplicate the user move when retrying the same pending turn', () => {
    expect(optimisticHallUserMove(['a3a4', 'h7e7'], 'h7e7', 'turn-1', 'turn-1', 'h7e7')).toEqual({
      moves: ['a3a4', 'h7e7'],
      pendingTurnId: 'turn-1',
      pendingUserUci: 'h7e7',
    })
  })
})
