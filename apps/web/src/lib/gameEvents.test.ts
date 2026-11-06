import { describe, expect, it } from 'vitest'
import { createHintEvent, createUndoEvent } from './gameEvents'

describe('game events', () => {
  it('captures the pre-undo moves and the exact moves removed by a multi-ply undo', () => {
    expect(createUndoEvent(['a3a4', 'a6a5', 'b3b4'], 2, 'fen-after-undo', '2026-11-06T00:00:00.000Z')).toEqual({
      id: expect.stringContaining('2026-11-06T00:00:00.000Z'),
      type: 'undo',
      createdAt: '2026-11-06T00:00:00.000Z',
      ply: 2,
      positionMoves: ['a3a4'],
      positionFen: 'fen-after-undo',
      undoneMoves: ['a6a5', 'b3b4'],
    })
  })

  it('stores the legal candidates shown for a hint at the current position', () => {
    expect(createHintEvent(['a3a4'], 'fen-hint', [{ move: 'a6a5', label: '卒 1 进 1', score: { type: 'cp', value: 12 } }], '2026-11-06T00:00:00.000Z')).toEqual({
      id: expect.stringContaining('2026-11-06T00:00:00.000Z'),
      type: 'hint',
      createdAt: '2026-11-06T00:00:00.000Z',
      ply: 2,
      positionMoves: ['a3a4'],
      positionFen: 'fen-hint',
      candidates: [{ move: 'a6a5', label: '卒 1 进 1', score: { type: 'cp', value: 12 } }],
    })
  })
})
