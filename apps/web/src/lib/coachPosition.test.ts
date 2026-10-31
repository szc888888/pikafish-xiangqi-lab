import { describe, expect, it } from 'vitest'
import { coachPosition } from './coachPosition'

describe('coach position payload', () => {
  it('sends the base position with its replayable game history during live play', () => {
    expect(coachPosition('base fen', 'current fen', ['a3a4'], true)).toEqual({
      fen: 'base fen',
      moves: ['a3a4'],
    })
  })

  it('does not replay game history on a FEN that already represents the current board', () => {
    expect(coachPosition('base fen', 'current fen', ['a3a4'], false)).toEqual({
      fen: 'current fen',
      moves: [],
    })
  })
})
