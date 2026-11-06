import { describe, expect, it } from 'vitest'
import { useReviewSession } from './useReviewSession'
import { START_FEN, toFen } from './xiangqi'
import type { ReviewResponse } from './api'

const result: ReviewResponse = { items: [{ ply: 1, side: 'red', move: 'a3a4', label: '兵九进一', best_move: 'h2e2', best_label: '炮二平五', before_score: { type: 'cp', value: 0 }, after_score: { type: 'cp', value: -100 }, grade: 'mistake', loss_cp: 100, pv: ['h2e2'] }], final_score: null, analyzed_plies: 1 }
const snapshot = () => ({ fen: START_FEN, moves: ['a3a4'], side: 'red' as const, gameId: 'one' })
describe('isolated review session', () => {
  it('replays and chats from the frozen pre-move position without touching live history', async () => {
    const live = snapshot()
    let payload: any
    const session = useReviewSession(async () => result, async p => { payload = p; return { answer: '先改善子力位置。', ai_available: true, ai_message: null } })
    await session.start(live)
    live.moves.push('a6a5')
    session.select(result.items[0])
    expect(session.snapshot.value?.moves).toEqual(['a3a4'])
    expect(toFen(session.board.value!)).toBe(START_FEN)
    await session.ask('为什么？')
    expect(payload.fen).toBe(START_FEN)
    expect(payload.moves).toEqual([])
    expect(payload.context).toContain('炮二平五')
    expect(live.moves).toEqual(['a3a4', 'a6a5'])
    expect(session.messages.value.at(-1)?.content).toContain('改善')
  })
  it('ignores late results from a superseded review', async () => {
    let resolveFirst!: (r: ReviewResponse) => void
    let count = 0
    const session = useReviewSession(() => ++count === 1 ? new Promise(r => { resolveFirst = r }) : Promise.resolve({ ...result, items: [], analyzed_plies: 2 }))
    const first = session.start(snapshot())
    await session.start({ ...snapshot(), moves: ['a3a4', 'a6a5'] })
    resolveFirst(result)
    await first
    expect(session.result.value?.analyzed_plies).toBe(2)
    expect(session.busy.value).toBe(false)
  })
  it('does not put a late AI answer into a different moment conversation', async () => {
    let finish!: (r: any) => void
    const second = { ...result.items[0], ply: 2, side: 'black' as const, move: 'a6a5', label: '卒1进1', best_move: 'b9c7', best_label: '马2进3' }
    const session = useReviewSession(async () => ({ ...result, items: [...result.items, second], analyzed_plies: 2 }), () => new Promise(r => { finish = r }))
    await session.start({ ...snapshot(), moves: ['a3a4', 'a6a5'] })
    session.select(result.items[0])
    const question = session.ask('解释')
    session.select(second)
    finish({ answer: '旧回答', ai_available: true })
    await question
    expect(session.messages.value).toEqual([])
    expect(session.chatBusy.value).toBe(false)
  })
  it('shows only the analyzed legal prefix when review stops at a rule violation', async () => {
    const session = useReviewSession(async () => ({ ...result, items: [], analyzed_plies: 6, status: 'stopped_rule_violation', stop: { ply: 7, side: 'red', kind: 'perpetual_chase', message: '长捉' } }))
    await session.start({ ...snapshot(), fen: '4k4/9/9/9/R1r1P4/9/9/9/9/4K4 w - - 0 1', moves: ['a5b5', 'c5c6', 'b5b6', 'c6c5', 'b6b5', 'c5c6', 'b5b6'] })
    expect(session.board.value?.board[4][1]).toBe('R')
    expect(session.board.value?.redToMove).toBe(true)
  })
  it('keeps errors retryable and detects changed games even when FEN happens to match', async () => {
    const session = useReviewSession(async () => { throw new Error('引擎暂不可用') })
    await session.start(snapshot())
    expect(session.error.value).toBe('引擎暂不可用')
    expect(session.isStale(snapshot())).toBe(false)
    expect(session.isStale({ ...snapshot(), gameId: 'two' })).toBe(true)
    expect(session.isStale({ ...snapshot(), moves: [] })).toBe(true)
  })
})
