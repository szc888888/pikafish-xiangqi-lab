import { describe, expect, it } from 'vitest'
import { createHintEvent, createUndoEvent, eventHighlightMove, eventMoveLabels, eventPosition, eventSide } from './gameEvents'
import { applyMove, fromUci, parseFen, START_FEN, toFen } from './xiangqi'

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

  it('replays event snapshots and highlights the relevant move', () => {
    const afterRed = applyMove(parseFen(START_FEN), fromUci('a3'), fromUci('a4'))
    const afterBlack = applyMove(afterRed, fromUci('a6'), fromUci('a5'))
    const hint = createHintEvent(['a3a4'], toFen(afterRed), [{ move: 'a6a5', label: '卒 1 进 1', score: null }], '2026-11-06T00:00:00.000Z')
    const undo = createUndoEvent(['a3a4', 'a6a5'], 1, toFen(afterRed), '2026-11-06T00:00:01.000Z')

    expect(toFen(eventPosition(START_FEN, hint))).toBe(toFen(afterRed))
    expect(eventHighlightMove(hint)).toBe('a6a5')
    expect(toFen(eventPosition(START_FEN, undo))).toBe(toFen(afterRed))
    expect(eventHighlightMove(undo)).toBe('a6a5')
  })

  it('describes undone moves from the position before the undo', () => {
    const undo = createUndoEvent(['a3a4', 'a6a5'], 1, toFen(applyMove(parseFen(START_FEN), fromUci('a3'), fromUci('a4'))), '2026-11-06T00:00:01.000Z')
    expect(eventMoveLabels(START_FEN, undo)).toEqual(['卒1进1'])
  })

  it('reports the side to move for a hint event from its frozen position', () => {
    const hint = createHintEvent([], START_FEN, [{ move: 'a3a4', label: '兵九进一', score: null }])
    expect(eventSide(START_FEN, hint)).toBe('red')
  })
})
