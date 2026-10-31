import { describe, expect, it } from 'vitest'
import { collectHintCandidates } from './hintCandidates'
import type { EngineLine } from './api'

const line = (rank: number, move: string): EngineLine => ({
  rank,
  move,
  label: move,
  score: { type: 'cp', value: 10 - rank },
  depth: 15,
  pv: [move],
})

describe('collectHintCandidates', () => {
  it('keeps engine ranking and filters each illegal candidate', () => {
    const result = collectHintCandidates([line(3, 'c3c4'), line(1, 'a1a2'), line(2, 'b2b3')], 'a1a2', move => move === 'b2b3')

    expect(result.map(candidate => candidate.move)).toEqual(['a1a2', 'c3c4'])
    expect(result.map(candidate => candidate.rank)).toEqual([1, 3])
  })

  it('adds a legal bestmove when the engine omitted it from lines', () => {
    const result = collectHintCandidates([line(2, 'b2b3')], 'a1a2', () => false, move => line(1, move))

    expect(result.map(candidate => candidate.move)).toEqual(['a1a2', 'b2b3'])
    expect(result[0].rank).toBe(1)
  })

  it('returns no candidates when every move is blocked', () => {
    expect(collectHintCandidates([line(1, 'a1a2')], 'a1a2', () => true)).toEqual([])
  })
})
