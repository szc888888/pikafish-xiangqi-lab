import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, createSSRApp, nextTick, ssrContextKey } from 'vue'
import { renderToString } from '@vue/server-renderer'
import App from './App.vue'
import * as api from './lib/api'
import { START_FEN, toFen } from './lib/xiangqi'
import { createHintEvent } from './lib/gameEvents'
import { reviewSnapshotKey } from './lib/useReviewSession'

vi.mock('./lib/api', async importOriginal => ({
  ...await importOriginal<typeof import('./lib/api')>(),
  getAiFriends: vi.fn().mockResolvedValue({ friends: [], catalog_version: 'v1' }),
  getAuthMethods: vi.fn().mockResolvedValue({}),
  getPrivacyConfig: vi.fn().mockResolvedValue({}),
  getMe: vi.fn().mockRejectedValue(new Error('guest')),
  getHealth: vi.fn().mockResolvedValue({ engine_ready: true }),
  getOpenings: vi.fn().mockResolvedValue({ matches: [] }),
  createHallGame: vi.fn(),
  importGame: vi.fn(),
  getGame: vi.fn(),
  getGames: vi.fn().mockResolvedValue([]),
  createGame: vi.fn().mockRejectedValue(new Error('guest')),
  getGameStats: vi.fn().mockResolvedValue({ total: 0, wins: 0, losses: 0, draws: 0, red_wins: 0, black_wins: 0 }),
  deleteGame: vi.fn(),
  resignHallGame: vi.fn(),
  recommendMatch: vi.fn(),
  randomMatch: vi.fn(),
  submitHallTurn: vi.fn(),
  engineMove: vi.fn(() => new Promise(() => {})),
  review: vi.fn().mockResolvedValue({ items: [], analyzed_plies: 0, final_score: null }),
  persistReview: vi.fn(),
}))

// Mount the real App setup without a browser or child component rendering.
const renderer = createRenderer<object, object>({
  patchProp() {}, insert() {}, remove() {}, setText() {}, setElementText() {},
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  parentNode: () => null, nextSibling: () => null,
})
let unmount: (() => void) | undefined

async function mountApp() {
  const app = renderer.createApp({ ...App, render: () => null })
  app.provide(ssrContextKey, {})
  const proxy = app.mount({})
  unmount = () => app.unmount()
  await vi.waitFor(() => expect(api.getHealth).toHaveBeenCalled())
  await vi.waitFor(() => expect(api.getMe).toHaveBeenCalledTimes(2))
  await nextTick()
  return (proxy.$ as unknown as { setupState: Record<string, any> }).setupState
}

async function forwardButton(state: Record<string, any>) {
  const html = await renderToString(createSSRApp({ ...App, setup: () => state }))
  const duel = html.split('<h2>人机对弈</h2>')[1]?.split('<h2>棋局状态</h2>')[0]
  return duel?.match(/<button\b[^>]*>前进<\/button>/)?.[0]
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getGameStats).mockReset().mockResolvedValue({ total: 0, wins: 0, losses: 0, draws: 0, red_wins: 0, black_wins: 0 })
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  })
  vi.stubGlobal('window', { location: { hash: '' }, setInterval: () => 1, clearInterval() {} })
})
afterEach(() => { unmount?.(); unmount = undefined; vi.unstubAllGlobals() })

describe('public homepage', () => {
  it('opens the hall without a board or technical service panel', async () => {
    const state = await mountApp()
    const html = await renderToString(createSSRApp({ ...App, setup: () => state }))
    expect(state.tab).toBe('hall')
    expect(html).toContain('放心下')
    expect(html).toContain('无限提示')
    expect(html).not.toContain('class="board-column"')
    expect(html).not.toContain('API 后端')
    expect(html).not.toContain('重启引擎')
  })

  it('starts unlimited practice for a signed-in user and preserves the previous formal game', async () => {
    const state = await mountApp()
    const old = { ...state.createGameRecord('formal-old', '2026-11-15', '2026-11-15'), mode: 'ai_hall', status: 'active', serverVersion: 2 }
    state.savedGames = [old]
    state.currentGameId = old.id
    state.hallMode = true
    state.hallCloud = true
    state.currentUser = { id: 'user-1', status: 'active', privacy_accepted: true }
    state.side = 'black'
    state.startPractice('beginner')
    await nextTick()
    expect(state.tab).toBe('duel')
    expect(state.hallMode).toBe(false)
    expect(state.hallCloud).toBe(false)
    expect(state.side).toBe('red')
    expect(state.difficulty).toBe('beginner')
    expect(state.currentGameId).toBeNull()
    expect(state.canRequestHint).toBe(true)
    expect(state.savedGames[0]).toEqual(old)
    expect(api.createHallGame).not.toHaveBeenCalled()
    expect(api.engineMove).not.toHaveBeenCalled()
    state.history = ['a3a4', 'a6a5']
    expect(state.canUndo).toBe(true)
    state.hintUsed = 999
    expect(state.canRequestHint).toBe(true)
  })

  it('does not abandon an in-flight hall request to start practice', async () => {
    const state = await mountApp()
    state.hallBusy = true
    state.hallMode = true
    state.startPractice('beginner')
    expect(state.hallMode).toBe(true)
    expect(state.tab).toBe('hall')
  })
})

describe('long review entry', () => {
  it('saves a previously local review after consent becomes valid without requiring a new snapshot', async () => {
    const state = await mountApp()
    const moves = Array.from({ length: 33 }, () => ['b0c2', 'b9c7', 'c2b0', 'c7b9']).flat()
    const game = { ...state.createGameRecord('consent-long', '2026-11-16', '2026-11-16'), moves, serverVersion: 132, syncedMoves: 132 }
    state.savedGames = [game]
    state.history = moves
    state.currentGameId = game.id
    state.quickReview.restore(state.currentReviewSnapshot, { items: [], analyzed_plies: 132, final_score: null })
    state.currentUser = { id: 'owner', status: 'active', privacy_accepted: true }
    vi.mocked(api.persistReview).mockResolvedValueOnce({ items: [], analyzed_plies: 132, final_score: null, review_id: 'consent-saved', game_id: game.id })
    state.openReview()
    await vi.waitFor(() => expect(state.quickReview.result.value?.review_id).toBe('consent-saved'))
  })
  it('uses cloud persistence for an owned long game and explicitly regenerates on request', async () => {
    const state = await mountApp()
    const moves = Array.from({ length: 33 }, () => ['b0c2', 'b9c7', 'c2b0', 'c7b9']).flat()
    state.currentUser = { id: 'owner', status: 'active', privacy_accepted: true }
    const game = { ...state.createGameRecord('owned-long', '2026-11-16', '2026-11-16'), moves, serverVersion: 132, syncedMoves: 132 }
    state.savedGames = [game]
    vi.mocked(api.persistReview).mockResolvedValue({ items: [], analyzed_plies: 132, final_score: null, review_id: 'cloud-review', game_id: game.id })
    state.useSavedGame(game)
    await vi.waitFor(() => expect(state.quickReview.result.value?.review_id).toBe('cloud-review'))
    expect(api.persistReview).toHaveBeenLastCalledWith(game.id, expect.objectContaining({ moves }), expect.any(Function), false)
    expect(api.review).not.toHaveBeenCalled()
    await state.startQuickReview(true)
    expect(api.persistReview).toHaveBeenLastCalledWith(game.id, expect.any(Object), expect.any(Function), true)
  })
  it('uploads a consenting user’s local practice through the existing import flow before saving its review', async () => {
    const state = await mountApp()
    const moves = Array.from({ length: 33 }, () => ['b0c2', 'b9c7', 'c2b0', 'c7b9']).flat()
    state.currentUser = { id: 'owner', status: 'active', privacy_accepted: true }
    const game = { ...state.createGameRecord('local-long', '2026-11-16', '2026-11-16'), moves }
    const remote = { id: 'uploaded-long', version: 132, moves: moves.map(uci => ({ uci })), events: [] }
    state.savedGames = [game]
    vi.mocked(api.importGame).mockResolvedValue(remote as any)
    vi.mocked(api.getGame).mockResolvedValue(remote as any)
    vi.mocked(api.persistReview).mockResolvedValue({ items: [], analyzed_plies: 132, final_score: null, review_id: 'uploaded-review', game_id: remote.id })
    state.useSavedGame(game)
    await vi.waitFor(() => expect(state.quickReview.result.value?.review_id).toBe('uploaded-review'))
    expect(api.importGame).toHaveBeenCalledWith(expect.objectContaining({ legacy_id: 'local-long', moves }))
    expect(state.currentGameId).toBe(remote.id)
    expect(state.quickReview.snapshot.value.gameId).toBe(remote.id)
    expect(state.savedGames[0].reviewCache?.result.review_id).toBe('uploaded-review')
    expect(api.review).not.toHaveBeenCalled()
  })
  it('keeps cloud save failures visible and retries the same stored progress', async () => {
    const state = await mountApp()
    const moves = Array.from({ length: 33 }, () => ['b0c2', 'b9c7', 'c2b0', 'c7b9']).flat()
    state.currentUser = { id: 'owner', status: 'active', privacy_accepted: true }
    const game = { ...state.createGameRecord('retry-long', '2026-11-16', '2026-11-16'), moves, serverVersion: 132, syncedMoves: 132 }
    state.savedGames = [game]
    vi.mocked(api.persistReview).mockRejectedValueOnce(new Error('云端保存失败'))
    state.useSavedGame(game)
    await vi.waitFor(() => expect(state.quickReview.error.value).toBe('云端保存失败'))
    expect(api.review).not.toHaveBeenCalled()
    expect(state.quickReview.result.value).toBeNull()
    vi.mocked(api.persistReview).mockResolvedValueOnce({ items: [], analyzed_plies: 132, final_score: null, review_id: 'retried', game_id: game.id })
    await state.startQuickReview(true)
    expect(api.persistReview).toHaveBeenLastCalledWith(game.id, expect.any(Object), expect.any(Function), false)
  })
  it('opens and caches a long game review with progress without changing the live game', async () => {
    const state = await mountApp()
    const moves = Array.from({ length: 33 }, () => ['b0c2', 'b9c7', 'c2b0', 'c7b9']).flat()
    const game = { ...state.createGameRecord('long-game', '2026-11-16', '2026-11-16'), moves }
    state.savedGames = [game]
    vi.mocked(api.review).mockImplementationOnce(async (payload, progress) => {
      expect(payload.moves).toEqual(moves)
      progress?.(30, moves.length)
      expect(state.quickReview.progress.value).toEqual({ completed: 30, total: 132 })
      progress?.(132, 132)
      return { items: [], final_score: null, analyzed_plies: 132, status: 'complete' }
    })
    state.useSavedGame(game)
    const positionBefore = toFen(state.position)
    expect(state.quickReviewReason).toBe('')
    state.openReview()
    await vi.waitFor(() => expect(state.quickReview.busy.value).toBe(false))
    expect(state.reviewDialogOpen).toBe(true)
    expect(state.quickReview.result.value?.analyzed_plies).toBe(132)
    expect(state.savedGames[0].reviewCache?.result.analyzed_plies).toBe(132)
    expect(toFen(state.position)).toBe(positionBefore)
    expect(state.history).toEqual(moves)
  })
  it('also caches completed long reviews from the full review tab', async () => {
    const state = await mountApp()
    const moves = Array.from({ length: 33 }, () => ['b0c2', 'b9c7', 'c2b0', 'c7b9']).flat()
    state.history = moves
    state.currentGameId = 'long-tab'
    state.savedGames = [state.createGameRecord('long-tab', '2026-11-16', '2026-11-16')]
    vi.mocked(api.review).mockResolvedValueOnce({ items: [], analyzed_plies: 132, final_score: null, status: 'complete' })
    await state.runReview()
    expect(state.savedGames[0].reviewCache?.result.analyzed_plies).toBe(132)
  })
})

describe('saved game navigation', () => {
  it('shows the loaded game name on the duel page and keeps it through undo and redo', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('named', '2026-11-21', '2026-11-21', '残局练习'), moves: ['a3a4', 'a6a5'] }
    state.savedGames = [game]
    state.useSavedGame(game)
    const html = await renderToString(createSSRApp({ ...App, setup: () => state }))
    expect(html).toContain('aria-label="当前棋局">残局练习</p>')
    await state.undo()
    await state.redo()
    expect(state.currentGameName).toBe('残局练习')
    state.resetGame()
    expect(state.currentGameName).toBe('自由练习')
  })

  it('continues an old watch-mode archive as the current side without changing its history', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('old-cloud', '2026-11-21', '2026-11-21'), side: 'watch', moves: ['a3a4'] }
    state.savedGames = [game]
    state.continueSavedGame(game)
    expect(state.currentGameName).toBe('未命名棋局')
    expect(state.side).toBe('black')
    expect(state.canHumanMove).toBe(true)
    expect(game.side).toBe('watch')
    expect(state.history).toEqual(['a3a4'])
    expect(api.engineMove).not.toHaveBeenCalled()
    vi.mocked(api.engineMove).mockResolvedValueOnce({ bestmove: 'b0c2', lines: [] } as any)
    state.clickSquare(3, 0)
    state.clickSquare(4, 0)
    expect(state.history).toEqual(['a3a4', 'a6a5'])
    expect(api.engineMove).toHaveBeenCalledTimes(1)
    await vi.waitFor(() => expect(state.status).toBe('idle'), { timeout: 2500 })
    expect(state.history).toEqual(['a3a4', 'a6a5', 'b0c2'])
    expect(state.canHumanMove).toBe(true)
  })

  it('keeps a terminal archive closed when continuing it', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('finished-practice', '2026-11-21', '2026-11-21'),
      side: 'red', baseFen: 'R3k4/9/4R4/9/9/4P4/9/9/9/4K4 b - - 0 1', moves: [] }
    state.savedGames = [game]
    state.continueSavedGame(game)
    await nextTick()
    expect(state.gameTerminal).toBe('checkmate')
    expect(state.canHumanMove).toBe(false)
    expect(api.engineMove).not.toHaveBeenCalled()
  })

  it('offers an explicit way to continue the current watch position', async () => {
    const state = await mountApp()
    state.tab = 'duel'
    state.side = 'watch'
    const html = await renderToString(createSSRApp({ ...App, setup: () => state }))
    expect(html).toContain('>继续对弈</button>')
    state.resumePractice()
    expect(state.side).toBe('red')
    expect(state.canHumanMove).toBe(true)
    expect(api.engineMove).not.toHaveBeenCalled()
  })

  it('requests the pending ordinary AI move once when opening a saved game', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('pending-practice', '2026-11-21', '2026-11-21'), moves: ['a3a4'] }
    state.savedGames = [game]
    state.useSavedGame(game)
    await nextTick()
    expect(state.side).toBe('red')
    expect(api.engineMove).toHaveBeenCalledTimes(1)
    expect(api.engineMove).toHaveBeenCalledWith(expect.objectContaining({ moves: ['a3a4'], game_id: game.id }))
    state.resumePractice()
    expect(api.engineMove).toHaveBeenCalledTimes(1)
  })

  it('resumes a black player’s pending red opening without duplicate requests', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('black-opening', '2026-11-21', '2026-11-21'), side: 'black' }
    state.savedGames = [game]
    state.useSavedGame(game)
    await nextTick()
    expect(api.engineMove).toHaveBeenCalledTimes(1)
  })

  it('can retry a failed pending ordinary AI turn', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('retry-practice', '2026-11-21', '2026-11-21'), moves: ['a3a4'] }
    state.savedGames = [game]
    vi.mocked(api.engineMove).mockRejectedValueOnce(new Error('引擎暂不可用'))
    state.useSavedGame(game)
    await vi.waitFor(() => expect(state.status).toBe('error'))
    expect(state.history).toEqual(['a3a4'])
    state.resumePractice()
    expect(api.engineMove).toHaveBeenCalledTimes(2)
    expect(api.engineMove).toHaveBeenLastCalledWith(expect.objectContaining({ moves: ['a3a4'], game_id: game.id }))
  })

  it('sends the selected side when saving a new named practice', async () => {
    const state = await mountApp()
    state.side = 'black'
    state.savePositionAsGame('执黑练习')
    expect(api.createGame).toHaveBeenCalledWith(expect.objectContaining({ name: '执黑练习', user_side: 'black' }))
  })

  it('keeps a known local side when an old cloud record has no user side', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('merge-side', '2026-11-21', '2026-11-21'), side: 'black', serverVersion: 0 }
    state.savedGames = [game]
    vi.mocked(api.getMe).mockResolvedValueOnce({ id: 'owner', status: 'active', privacy_accepted: true } as any)
    vi.mocked(api.getGames).mockResolvedValueOnce([{
      id: game.id, name: null, initial_fen: START_FEN, moves: [], events: [], version: 0,
      created_at: game.startedAt, updated_at: game.updatedAt, user_side: null, engine_settings: game.difficultySettings,
    }] as any)
    await state.loadServerGames()
    expect(state.savedGames[0].side).toBe('black')
  })

  it('reuses a cached quick review when reopening the same saved game', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('chanju2', '2026-11-20', '2026-11-20'), moves: ['a3a4', 'a6a5'] }
    state.savedGames = [game]
    vi.mocked(api.review).mockResolvedValue({ items: [], analyzed_plies: 2, final_score: null, status: 'complete' })

    state.useSavedGame(game)
    await vi.waitFor(() => expect(state.quickReview.busy.value).toBe(false))
    expect(api.review).toHaveBeenCalledTimes(1)
    expect(state.savedGames[0].reviewCache).toBeDefined()

    state.useSavedGame(game)
    await nextTick()
    expect(api.review).toHaveBeenCalledTimes(1)
    expect(state.quickReview.result.value?.analyzed_plies).toBe(2)
  })

  it('keeps the quick review cache when saved event records are merged', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('event-cache', '2026-11-20', '2026-11-20'), moves: ['a3a4', 'a6a5'], events: [] }
    state.savedGames = [game]
    vi.mocked(api.review).mockResolvedValue({ items: [], analyzed_plies: 2, final_score: null, status: 'complete' })

    state.useSavedGame(game)
    await vi.waitFor(() => expect(state.quickReview.busy.value).toBe(false))
    game.events = [createHintEvent(game.moves, toFen(state.position), [{ move: 'b2b3', label: '炮八进一', score: null }])]
    state.useSavedGame(game)
    await nextTick()
    expect(api.review).toHaveBeenCalledTimes(1)
  })

  it('restores a legacy cached summary after event changes without regenerating it', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('legacy-cache', '2026-11-20', '2026-11-20'), moves: ['a3a4', 'a6a5'], events: [] }
    state.savedGames = [game]
    state.useSavedGame(game)
    await vi.waitFor(() => expect(state.quickReview.busy.value).toBe(false))
    game.reviewCache = {
      snapshotKey: reviewSnapshotKey(state.currentReviewSnapshot),
      result: { items: [], analyzed_plies: 2, final_score: null, status: 'complete' },
      generatedAt: '2026-11-20T00:00:00Z',
    }
    game.events = [createHintEvent(game.moves, toFen(state.position), [{ move: 'b2b3', label: '炮八进一', score: null }])]
    vi.mocked(api.review).mockClear()

    state.useSavedGame(game)
    await nextTick()
    expect(api.review).not.toHaveBeenCalled()
    expect(state.quickReview.result.value?.analyzed_plies).toBe(2)
    expect(JSON.parse(game.reviewCache.snapshotKey)).toEqual([game.baseFen, game.moves, game.side])
  })

  it('restores a short review after the local game receives a cloud identity', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('guest-game', '2026-11-20', '2026-11-20'), moves: ['a3a4', 'a6a5'] }
    state.savedGames = [game]
    state.useSavedGame(game)
    await vi.waitFor(() => expect(state.quickReview.busy.value).toBe(false))
    expect(api.review).toHaveBeenCalledTimes(1)

    game.id = 'cloud-game'
    game.serverVersion = 2
    state.currentGameId = game.id
    state.useSavedGame(game)
    await nextTick()
    expect(api.review).toHaveBeenCalledTimes(1)
  })

  it('uploads one local game with its events and replaces its local identity only after verification', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('local-game', '2026-11-12', '2026-11-12'), moves: ['a3a4', 'a6a5'], events: [{ id: 'event-1' }] }
    state.savedGames = [game]
    state.currentUser = { id: 'user-1', status: 'active', privacy_accepted: true }
    state.currentGameId = game.id
    const remote = { id: 'cloud-game', version: 2, moves: [{ uci: 'a3a4' }, { uci: 'a6a5' }], events: game.events }
    vi.mocked(api.importGame).mockResolvedValue(remote as any)
    vi.mocked(api.getGame).mockResolvedValue(remote as any)
    await state.uploadSavedGame(game)
    expect(api.importGame).toHaveBeenCalledWith(expect.objectContaining({ legacy_id: 'local-game', moves: game.moves, events: game.events, user_side: 'red' }))
    expect(state.savedGames).toHaveLength(1)
    expect(state.savedGames[0]).toMatchObject({ id: 'cloud-game', serverVersion: 2, syncedEvents: 1 })
    expect(state.currentGameId).toBe('cloud-game')
  })
  it('shows forward beside undo and restores loaded moves after undoing to the start', async () => {
    const state = await mountApp()
    const game = {
      ...state.createGameRecord('saved-game', '2026-11-12', '2026-11-12'),
      moves: ['a3a4', 'a6a5'],
    }
    state.savedGames = [game]
    state.useSavedGame(game)
    await nextTick()

    expect(state.tab).toBe('duel')
    expect(await forwardButton(state)).toBeDefined()
    expect(await forwardButton(state)).toContain('disabled')
    const html = await renderToString(createSSRApp({ ...App, setup: () => state }))
    expect(html.match(/>前进<\/button>/g)).toHaveLength(1)

    await state.undo()
    await nextTick()
    expect(state.history).toEqual([])
    expect(toFen(state.position)).toBe(START_FEN)
    expect(await forwardButton(state)).toBeDefined()
    expect(await forwardButton(state)).not.toContain('disabled')

    await state.redo()
    await nextTick()
    expect(state.history).toEqual(['a3a4', 'a6a5'])
    expect(toFen(state.position)).toBe('rnbakabnr/9/1c5c1/2p1p1p1p/p8/P8/2P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1')
    expect(await forwardButton(state)).toContain('disabled')
    expect(api.engineMove).not.toHaveBeenCalled()
  })

  it('hides forward in a new game and after restarting a loaded game', async () => {
    const state = await mountApp()
    state.tab = 'duel'
    expect(await forwardButton(state)).toBeUndefined()

    const game = {
      ...state.createGameRecord('loaded-game', '2026-11-12', '2026-11-12'),
      moves: ['a3a4', 'a6a5'],
    }
    state.savedGames = [game]
    state.useSavedGame(game)
    expect(await forwardButton(state)).toBeDefined()

    state.resetGame()
    expect(await forwardButton(state)).toBeUndefined()
  })
})

describe('duel new game', () => {
  it('starts a playable red game after watching', async () => {
    const state = await mountApp()
    state.side = 'watch'
    await nextTick()
    expect(state.canHumanMove).toBe(false)

    state.resetGame()
    await nextTick()

    expect(state.side).toBe('red')
    expect(state.canHumanMove).toBe(true)
    expect(state.canRequestHint).toBe(true)
    expect(api.engineMove).not.toHaveBeenCalled()
    state.clickSquare(6, 0)
    state.clickSquare(5, 0)
    expect(state.history).toEqual(['a3a4'])
    expect(api.engineMove).toHaveBeenCalledTimes(1)
    expect(api.engineMove).toHaveBeenCalledWith(expect.objectContaining({ moves: ['a3a4'] }))
  })

  it('starts an ordinary game using the selected level after a hall game', async () => {
    const state = await mountApp()
    const friend = { bot_id: 'tea-sparrow', name: '茶香雀', strength_profile: 'companion' }
    const oldGame = {
      ...state.createGameRecord('hall-old', '2026-11-11', '2026-11-11'),
      mode: 'ai_hall', opponentSnapshot: friend, status: 'active', serverVersion: 0, syncedMoves: 0,
    }
    state.savedGames = [oldGame]
    state.currentGameId = oldGame.id
    state.hallMode = true
    state.hallCloud = true
    state.hallOpponent = friend
    state.applyDifficulty('serious')
    state.quickReview.restore({ fen: START_FEN, moves: [], side: 'red', gameId: oldGame.id }, {
      items: [], analyzed_plies: 0, final_score: null,
    })
    state.reviewDialogOpen = true

    state.resetGame()
    await nextTick()

    expect(api.createHallGame).not.toHaveBeenCalled()
    expect(state.hallMode).toBe(false)
    expect(state.hallCloud).toBe(false)
    expect(state.hallOpponent).toBeNull()
    expect(state.currentGameId).toBeNull()
    expect(state.difficulty).toBe('serious')
    expect(state.side).toBe('red')
    expect(state.history).toEqual([])
    expect(toFen(state.position)).toBe(START_FEN)
    expect(state.quickReview.snapshot.value).toBeNull()
    expect(state.reviewDialogOpen).toBe(false)
    expect(state.savedGames[0]).toEqual(oldGame)
    expect(JSON.parse(localStorage.getItem('pikafish-lab-games-v1')!)[0]).toEqual(oldGame)

    state.clickSquare(6, 0)
    state.clickSquare(5, 0)
    expect(api.engineMove).toHaveBeenCalledWith(expect.objectContaining({ difficulty: 'serious', moves: ['a3a4'] }))
    expect(api.submitHallTurn).not.toHaveBeenCalled()
  })

  it('keeps the previous ordinary game when starting a new game', async () => {
    const state = await mountApp()
    state.currentGameId = 'ordinary-old'
    state.history = ['a3a4']
    state.applyDifficulty('beginner')

    state.resetGame()

    expect(state.savedGames[0].id).toBe('ordinary-old')
    expect(state.savedGames[0].moves).toEqual(['a3a4'])
    expect(state.difficulty).toBe('beginner')
    expect(state.currentGameId).toBeNull()
    expect(state.message).toBe('新局已开始')
  })

  it('uses the ordinary engine for the first red move when the user plays black', async () => {
    const state = await mountApp()
    state.side = 'black'
    await nextTick()
    vi.mocked(api.engineMove).mockClear()
    state.status = 'idle'
    state.hallMode = true
    state.hallOpponent = { bot_id: 'tea-sparrow', name: '茶香雀' }
    state.applyDifficulty('beginner')

    state.resetGame()
    await nextTick()

    expect(state.side).toBe('black')
    expect(api.engineMove).toHaveBeenCalledTimes(1)
    expect(api.engineMove).toHaveBeenCalledWith(expect.objectContaining({ difficulty: 'beginner', moves: [] }))
    expect(api.createHallGame).not.toHaveBeenCalled()
    expect(api.submitHallTurn).not.toHaveBeenCalled()
  })

  it('leaves an in-flight hall turn intact until its request finishes', async () => {
    const state = await mountApp()
    state.currentGameId = 'pending-hall'
    state.hallMode = true
    state.hallBusy = true
    state.hallTurnId = 'turn-1'
    state.status = 'thinking'

    state.resetGame()

    expect(state.currentGameId).toBe('pending-hall')
    expect(state.hallMode).toBe(true)
    expect(state.hallTurnId).toBe('turn-1')
    expect(api.engineMove).not.toHaveBeenCalled()
  })
})


describe('formal hall result lifecycle', () => {
  it('preserves a cloud game and its stats when deletion fails, then refreshes after success', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('cloud-finished', '2026-11-15', '2026-11-15'), mode: 'ai_hall', status: 'finished', result: 'red_win', serverVersion: 4 }
    state.savedGames = [game]
    state.currentGameId = game.id
    vi.mocked(api.getGameStats).mockResolvedValue({ total: 1, wins: 1, losses: 0, draws: 0, red_wins: 1, black_wins: 0 })
    state.currentUser = { id: 'alice', status: 'active', privacy_accepted: true }
    await vi.waitFor(() => expect(state.gameStats.data.value?.total).toBe(1))
    vi.mocked(api.deleteGame).mockRejectedValueOnce(new Error('删除失败'))
    await state.removeGame(game)
    expect(state.savedGames).toHaveLength(1)
    expect(state.currentGameId).toBe('cloud-finished')
    expect(state.message).toBe('删除失败')
    expect(state.gameStats.data.value?.total).toBe(1)
    vi.mocked(api.getGameStats).mockResolvedValue({ total: 0, wins: 0, losses: 0, draws: 0, red_wins: 0, black_wins: 0 })
    vi.mocked(api.deleteGame).mockResolvedValueOnce(undefined)
    await state.removeGame(game)
    expect(state.savedGames).toHaveLength(0)
    expect(state.currentGameId).toBeNull()
    await vi.waitFor(() => expect(state.gameStats.data.value?.total).toBe(0))
  })
  it('persists cloud resignation details and refreshes formal stats', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('cloud-active', '2026-11-15', '2026-11-15'), mode: 'ai_hall', status: 'active', serverVersion: 0 }
    state.savedGames = [game]; state.currentGameId = game.id
    state.hallCloud = true; state.hallMode = true
    state.currentUser = { id: 'alice', status: 'active', privacy_accepted: true }
    await nextTick()
    vi.mocked(api.resignHallGame).mockResolvedValueOnce({ status: 'finished', result: 'black_win', termination_reason: 'resignation', version: 1 } as any)
    vi.mocked(api.getGameStats).mockResolvedValue({ total: 1, wins: 0, losses: 1, draws: 0, red_wins: 0, black_wins: 1 })
    await state.resignHall()
    expect(state.hallResult).toBe('black_win')
    expect(state.hallEndReason).toBe('resignation')
    expect(JSON.parse(localStorage.getItem('pikafish-lab-games-v1')!)[0]).toMatchObject({ status: 'finished', result: 'black_win', terminationReason: 'resignation' })
    await vi.waitFor(() => expect(state.gameStats.data.value?.losses).toBe(1))
  })
})

describe('recoverable hall turns', () => {
  it('blocks board edits, undo and redo while a pending hall turn needs recovery', async () => {
    const state = await mountApp()
    const game = { ...state.createGameRecord('pending', '2026-11-15', '2026-11-15'), mode: 'ai_hall', moves: ['a3a4', 'a6a5'], status: 'awaiting_ai' }
    state.savedGames = [game]; state.useSavedGame(game)
    state.hallTurnId = 'same-turn'; state.hallTurnMove = 'a3a4'
    state.status = 'error'; state.futureMoves = ['c3c4']
    expect(state.canHumanMove).toBe(false)
    expect(state.canUndo).toBe(false)
    expect(state.canRedo).toBe(false)
    await state.undo()
    expect(state.history).toEqual(['a3a4', 'a6a5'])
  })
  it('keeps a resigned local board closed even if pieces still have legal moves', async () => {
    const state = await mountApp()
    state.hallMode = true; state.hallResult = 'black_win'
    expect(state.canHumanMove).toBe(false)
    state.clickSquare(6, 0); state.clickSquare(5, 0)
    expect(state.history).toEqual([])
  })
  it('returns a local pending game to active after a successful retry without replaying the user move', async () => {
    const state = await mountApp()
    const friend = { bot_id: 'north-star', name: '北斗', strength_profile: 'progress' }
    const game = { ...state.createGameRecord('guest-pending', '2026-11-15', '2026-11-15'), mode: 'ai_hall', opponentSnapshot: friend, moves: ['a3a4'], status: 'awaiting_ai', pendingTurnId: 'local-turn', pendingUserUci: 'a3a4' }
    state.savedGames = [game]; state.useSavedGame(game)
    state.health = { engine_ready: true }
    vi.mocked(api.engineMove).mockResolvedValueOnce({ bestmove: 'a6a5', lines: [] } as any)
    await state.playHallMove('a3a4')
    expect(state.history).toEqual(['a3a4', 'a6a5'])
    expect(state.savedGames[0].status).toBe('active')
    expect(state.savedGames[0].pendingTurnId).toBeNull()
    expect(state.hallTurnId).toBeNull()
  })
  it('restores a cloud pending turn with its original id and version', async () => {
    const state = await mountApp()
    const friend = { bot_id: 'north-star', name: '北斗', strength_profile: 'progress' }
    const game = { ...state.createGameRecord('cloud-pending', '2026-11-15', '2026-11-15'), mode: 'ai_hall', opponentSnapshot: friend, moves: ['a3a4'], status: 'awaiting_ai', serverVersion: 1, pendingTurnId: 'original-turn', pendingUserUci: 'a3a4', pendingExpectedVersion: 0 }
    state.savedGames = [game]
    vi.mocked(api.submitHallTurn).mockResolvedValueOnce({ game: { moves: [{ uci: 'a3a4' }, { uci: 'a6a5' }], status: 'active', version: 2, updated_at: '2026-11-15', result: null }, ai_move: null } as any)
    state.continueSavedGame(game)
    await vi.waitFor(() => expect(state.history).toEqual(['a3a4', 'a6a5']))
    expect(api.submitHallTurn).toHaveBeenCalledWith('cloud-pending', { turn_id: 'original-turn', expected_version: 0, user_uci: 'a3a4' })
    expect(state.savedGames[0].status).toBe('active')
    expect(state.hallTurnId).toBeNull()
  })
})

it('starts a recommended black cloud game through one hall opening turn only', async () => {
  const state = await mountApp()
  const friend = { bot_id: 'north-star', name: '北斗', strength_profile: 'progress' }
  const remote = { id: 'black-game', version: 0, initial_fen: START_FEN, moves: [], events: [], created_at: '2026-11-15', updated_at: '2026-11-15', user_side: 'black', mode: 'ai_hall', status: 'active', opponent_snapshot: friend }
  state.currentUser = { id: 'alice', status: 'active', privacy_accepted: true }
  vi.mocked(api.recommendMatch).mockResolvedValueOnce({ opponent: friend } as any)
  vi.mocked(api.createHallGame).mockResolvedValueOnce(remote as any)
  vi.mocked(api.submitHallTurn).mockResolvedValueOnce({ game: { ...remote, version: 1, moves: [{ uci: 'a3a4' }] }, ai_move: null } as any)
  await state.matchHall('recommend', 'practice', 'black')
  expect(api.createHallGame).toHaveBeenCalledWith({ opponent_id: 'north-star', user_side: 'black' })
  expect(api.submitHallTurn).toHaveBeenCalledTimes(1)
  expect(api.engineMove).not.toHaveBeenCalled()
  expect(state.history).toEqual(['a3a4'])
  expect(state.canHumanMove).toBe(true)
  expect(state.canUndo).toBe(false)
})

it('offers pending-turn recovery on a manually loaded game even without a previous error', async () => {
  const state = await mountApp()
  const game = { ...state.createGameRecord('older-pending', '2026-11-14', '2026-11-14'), mode: 'ai_hall', moves: ['a3a4'], status: 'awaiting_ai', pendingTurnId: 'older-turn', pendingUserUci: 'a3a4' }
  state.savedGames = [game]; state.useSavedGame(game)
  expect(state.hallError).toBe('')
  const html = await renderToString(createSSRApp({ ...App, setup: () => state }))
  expect(html).toContain('重试当前回合')
})

it.each(['fen', 'setup'])('starts independent play from %s after a resigned hall game', async source => {
  const state = await mountApp()
  state.hallMode = true; state.hallCloud = true; state.hallResult = 'black_win'
  state.hallTurnId = 'old-turn'; state.hallOpponent = { name: '旧棋友' }
  if (source === 'fen') { state.fenInput = START_FEN; state.loadFen() }
  else { state.startSetup(); state.finishSetup() }
  expect(state.hallMode).toBe(false)
  expect(state.hallResult).toBeNull()
  expect(state.hallTurnId).toBeNull()
  expect(state.canHumanMove).toBe(true)
})
