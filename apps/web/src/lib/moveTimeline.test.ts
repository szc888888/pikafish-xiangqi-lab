import { describe, expect, it } from 'vitest'
import { advanceMoves, undoMoves } from './moveTimeline'

describe('move timeline', () => {
  it('restores the most recently undone moves in their original order', () => {
    const undone = undoMoves(['a', 'b', 'c', 'd'], 2)
    const advanced = advanceMoves(undone.moves, undone.future, 2)

    expect(advanced).toEqual({ moves: ['a', 'b', 'c', 'd'], future: [] })
  })

  it('keeps earlier undone moves queued when undo is repeated', () => {
    const firstUndo = undoMoves(['a', 'b', 'c', 'd', 'e', 'f'], 2)
    const secondUndo = undoMoves(firstUndo.moves, 2, firstUndo.future)
    const firstAdvance = advanceMoves(secondUndo.moves, secondUndo.future, 2)

    expect(firstAdvance).toEqual({ moves: ['a', 'b', 'c', 'd'], future: ['e', 'f'] })
    expect(advanceMoves(firstAdvance.moves, firstAdvance.future, 2)).toEqual({ moves: ['a', 'b', 'c', 'd', 'e', 'f'], future: [] })
  })
})
