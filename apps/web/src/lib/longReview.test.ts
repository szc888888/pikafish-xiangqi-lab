import { afterEach, expect, it, vi } from 'vitest'
import { review, persistReview } from './api'

afterEach(() => { vi.unstubAllGlobals() })

function mockSegments(failAt = -1, stopAt = -1) {
  return vi.fn(async (url: string, options: RequestInit) => {
    expect(url).toBe('/api/engine/review/segment')
    const p = JSON.parse(options.body as string)
    const failed = p.start_ply === failAt
    const stopped = p.start_ply === stopAt
    const end = stopped ? p.start_ply + 1 : p.moves.length
    return { ok: !failed, status: failed ? 503 : 200, headers: new Headers(), text: async () => JSON.stringify(failed ? { detail: '引擎暂不可用' } : {
      items: Array.from({ length: end - p.start_ply }, (_, i) => ({ ply: p.start_ply + i + 1 })), analyzed_plies: end, final_score: { type: 'cp', value: end },
      status: stopped ? 'stopped_rule_violation' : 'complete', stop: stopped ? { ply: end + 1, kind: 'perpetual_chase' } : null,
    }) }
  })
}

it('sequentially reviews every ply with complete original prefixes and progress', async () => {
  const moves = Array.from({ length: 131 }, (_, i) => `move-${i}`)
  const fetch = mockSegments(), progress = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const result = await review({ fen: 'original-fen', moves }, progress)
  expect(fetch).toHaveBeenCalledTimes(5)
  for (let i = 0; i < 5; i++) {
    const payload = JSON.parse(fetch.mock.calls[i][1].body as string)
    expect(payload).toMatchObject({ fen: 'original-fen', start_ply: i * 30, moves: moves.slice(0, Math.min((i + 1) * 30, 131)) })
  }
  expect(result.items.map(i => i.ply)).toEqual(Array.from({ length: 131 }, (_, i) => i + 1))
  expect(progress).toHaveBeenLastCalledWith(131, 131)
  expect(result.final_score?.value).toBe(131)
})

it('stops at a rule violation and never requests subsequent segments', async () => {
  const fetch = mockSegments(-1, 30)
  vi.stubGlobal('fetch', fetch)
  const result = await review({ fen: 'fen', moves: Array(131).fill('move') })
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(result.status).toBe('stopped_rule_violation')
  expect(result.analyzed_plies).toBe(31)
  expect(result.items).toHaveLength(31)
})

it('reports failures instead of presenting a partial review as complete', async () => {
  vi.stubGlobal('fetch', mockSegments(30))
  await expect(review({ fen: 'fen', moves: Array(131).fill('move') })).rejects.toThrow('引擎暂不可用')
})

it('persists long reviews in server segments and reads the final saved response', async () => {
  const fetch = vi.fn(async (url: string, options: RequestInit) => {
    const payload = JSON.parse(options.body as string)
    const completed = url.endsWith('/segmented') ? 0 : Math.min(payload.start_ply + 30, 131)
    const done = completed === 131
    return { ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify({
      review_id: 'saved-review', completed_plies: completed, total_plies: 131, status: done ? 'complete' : 'in_progress',
      result: done ? { review_id: 'saved-review', items: [], analyzed_plies: 131, final_score: null } : null,
    }) }
  })
  vi.stubGlobal('fetch', fetch)
  const result = await persistReview('cloud-id', { fen: 'fen', moves: Array(131).fill('move') })
  expect(result.analyzed_plies).toBe(131)
  expect(result).toHaveProperty('review_id', 'saved-review')
  expect(fetch.mock.calls[0][0]).toBe('/api/games/cloud-id/reviews/segmented')
  expect(fetch.mock.calls).toHaveLength(6)
  expect(fetch.mock.calls.slice(1).map(([url, options]) => [url, JSON.parse(options.body as string).start_ply])).toEqual([0, 30, 60, 90, 120].map(start => ['/api/reviews/saved-review/advance', start]))
})

it.each([1, 27, 120, 131])('restores a %i-ply cloud review without new engine requests even when the local cache is empty', async plies => {
  const fetch = vi.fn(async () => ({ ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify({
    review_id: 'saved', completed_plies: plies, total_plies: plies, status: 'complete',
    result: { review_id: 'saved', items: [], analyzed_plies: plies, final_score: null },
  }) }))
  vi.stubGlobal('fetch', fetch)
  const progress = vi.fn()
  expect((await persistReview('cloud', { fen: 'fen', moves: Array(plies).fill('move') }, progress)).analyzed_plies).toBe(plies)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch.mock.calls[0]).toEqual(expect.arrayContaining(['/api/games/cloud/reviews/segmented']))
  expect(progress).toHaveBeenLastCalledWith(plies, plies)
})

it.each([false, true])('persists a new short review and sends explicit refresh=%s', async refresh => {
  const fetch = vi.fn(async (url: string) => ({ ok: true, status: 200, headers: new Headers(), text: async () => JSON.stringify({
    review_id: 'short', completed_plies: url.endsWith('/advance') ? 27 : 0, total_plies: 27,
    status: url.endsWith('/advance') ? 'complete' : 'in_progress',
    result: url.endsWith('/advance') ? { review_id: 'short', items: [], analyzed_plies: 27, final_score: null } : null,
  }) }))
  vi.stubGlobal('fetch', fetch)
  await persistReview('cloud', { fen: 'fen', moves: Array(27).fill('move') }, undefined, refresh)
  expect(fetch).toHaveBeenCalledTimes(2)
  const calls = fetch.mock.calls as unknown as [string, RequestInit][]
  expect(calls[0][0]).toBe('/api/games/cloud/reviews/segmented')
  expect(JSON.parse(calls[0][1].body as string).reuse).toBe(!refresh)
  expect(calls[1][0]).toBe('/api/reviews/short/advance')
})

it('resumes from stored cloud progress and fails clearly when the next segment cannot be saved', async () => {
  const fetch = vi.fn(async (url: string) => ({ ok: url.endsWith('/segmented'), status: url.endsWith('/segmented') ? 200 : 503, headers: new Headers(), text: async () => JSON.stringify(url.endsWith('/segmented') ? {
    review_id: 'pending', completed_plies: 60, total_plies: 131, status: 'in_progress', result: null,
  } : { detail: '引擎暂不可用' }) }))
  vi.stubGlobal('fetch', fetch)
  await expect(persistReview('cloud', { fen: 'fen', moves: Array(131).fill('move') })).rejects.toThrow('引擎暂不可用')
  expect(fetch.mock.calls[1][0]).toBe('/api/reviews/pending/advance')
  expect(JSON.parse((fetch.mock.calls[1] as unknown as [string, RequestInit])[1].body as string).start_ply).toBe(60)
})
