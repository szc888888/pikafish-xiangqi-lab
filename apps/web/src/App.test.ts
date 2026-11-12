import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, nextTick, ssrContextKey } from 'vue'
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
  submitHallTurn: vi.fn(),
  engineMove: vi.fn(() => new Promise(() => {})),
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

describe('duel new game', () => {
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
