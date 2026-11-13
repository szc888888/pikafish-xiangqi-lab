import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, createSSRApp, nextTick, ssrContextKey } from 'vue'
import { renderToString } from '@vue/server-renderer'
import App from './App.vue'
import * as api from './lib/api'
import { START_FEN, toFen } from './lib/xiangqi'

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
  submitHallTurn: vi.fn(),
  engineMove: vi.fn(() => new Promise(() => {})),
  review: vi.fn().mockResolvedValue({ items: [], analyzed_plies: 0, final_score: null }),
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
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  })
  vi.stubGlobal('window', { location: { hash: '' }, setInterval: () => 1, clearInterval() {} })
})
afterEach(() => { unmount?.(); unmount = undefined; vi.unstubAllGlobals() })

describe('saved game navigation', () => {
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
