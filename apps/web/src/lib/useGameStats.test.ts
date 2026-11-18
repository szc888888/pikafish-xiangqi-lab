import { effectScope, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getGameStats, type GameStats } from './api'
import { useGameStats } from './useGameStats'

vi.mock('./api', () => ({ getGameStats: vi.fn() }))
const stats: GameStats = { total: 6, wins: 3, losses: 2, draws: 1, red_wins: 4, black_wins: 1 }
const scopes: ReturnType<typeof effectScope>[] = []
function setup(userId: string | null = 'alice') {
  const user = ref(userId), revision = ref('')
  const scope = effectScope(); scopes.push(scope)
  const state = scope.run(() => useGameStats(() => user.value, () => revision.value))!
  return { user, revision, state }
}
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.resetAllMocks() })

describe('formal game stats', () => {
  it('does not query or fabricate stats for guests', () => {
    const { state } = setup(null)
    expect(getGameStats).not.toHaveBeenCalled()
    expect(state.data.value).toBeNull()
    expect(state.busy.value).toBe(false)
  })
  it('loads server stats and refreshes when finished games change', async () => {
    vi.mocked(getGameStats).mockResolvedValueOnce(stats).mockResolvedValueOnce({ ...stats, total: 5, wins: 2 })
    const { state, revision } = setup()
    await vi.waitFor(() => expect(state.data.value?.total).toBe(6))
    revision.value = 'deleted-one'
    await vi.waitFor(() => expect(state.data.value?.total).toBe(5))
    expect(state.data.value?.wins).toBe(2)
  })
  it('clears an old account immediately and ignores its delayed response', async () => {
    let finish!: (value: GameStats) => void
    vi.mocked(getGameStats).mockResolvedValueOnce(stats).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { user, state } = setup()
    await vi.waitFor(() => expect(state.data.value).toEqual(stats))
    const pending = state.refresh()
    user.value = null
    expect(state.data.value).toBeNull()
    finish(stats); await pending; await nextTick()
    expect(state.data.value).toBeNull()
    expect(state.busy.value).toBe(false)
  })
  it('does not let the previous account overwrite the next account', async () => {
    let finish!: (value: GameStats) => void
    vi.mocked(getGameStats).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce({ total: 0, wins: 0, losses: 0, draws: 0, red_wins: 0, black_wins: 0 })
    const { user, state } = setup()
    user.value = 'bob'
    await vi.waitFor(() => expect(state.data.value?.total).toBe(0))
    finish(stats); await nextTick()
    expect(state.data.value?.total).toBe(0)
  })
  it('exposes failed requests and can retry without showing zero wins as a fallback', async () => {
    vi.mocked(getGameStats).mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce(stats)
    const { state } = setup()
    await vi.waitFor(() => expect(state.error.value).toBe('网络中断'))
    expect(state.data.value).toBeNull()
    await state.refresh()
    expect(state.error.value).toBe('')
    expect(state.data.value).toEqual(stats)
  })
})
