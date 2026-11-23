// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import AdminView from './AdminView.vue'
import type { ClientPlatform } from '../lib/clientPlatform'
import { getAdminOverview, getAdminUsers } from '../lib/api'

vi.mock('../lib/api', () => ({
  getAdminOverview: vi.fn(),
  getAdminUsers: vi.fn(),
  resetAdminEngine: vi.fn(),
}))

const profiles = [
  { key: 'companion', label: '轻松陪练', depth: 1, movetime_ms: 100, threads: 1, hash_mb: 16 },
  { key: 'beginner', label: '入门练习', depth: 2, movetime_ms: 250, threads: 1, hash_mb: 32 },
  { key: 'progress', label: '进阶对手', depth: 4, movetime_ms: 700, threads: 1, hash_mb: 64 },
  { key: 'serious', label: '认真对弈', depth: 8, movetime_ms: 1500, threads: 2, hash_mb: 256 },
  { key: 'full', label: '全力挑战', depth: 15, movetime_ms: 5000, threads: 4, hash_mb: 1024 },
]

const overview = {
  users: { total: 1, active: 1, deletion_pending: 0 },
  games: { total: 2 },
  engine: {
    pool_size: 1, ready_engines: 1, max_inflight: 3, inflight: 0,
    configured: true, ready: true, error: null, engine_version: 'test', nnue_version: 'test',
    path: 'engine', eval_file: 'network',
    engines: [{ index: 1, pid: 1, ready: true, configured: true, path: 'engine', eval_file: 'network' }],
  },
  profiles,
}

const users = [{
  id: 'user-1', email: 'test@example.com', display_name: '测试用户', status: 'active', role: 'user' as const,
  created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-22T00:00:00Z', last_active_at: '2026-11-22T00:00:00Z',
  game_platforms: [{ platform: 'pc' as ClientPlatform, games: 7 }, { platform: 'mini_program' as ClientPlatform, games: 2 }],
  active_days: 3, games_total: 9, formal_games: 2, hints_used: 4, undos_used: 1, opponent_games: 9,
  opponent_strengths: [{ key: 'companion' as const, label: '轻松陪练', games: 9 }],
}]

describe('admin user strength details', () => {
  let root: HTMLDivElement | undefined
  let app: ReturnType<typeof createApp> | undefined

  afterEach(() => {
    app?.unmount()
    root?.remove()
    app = undefined
    root = undefined
    vi.clearAllMocks()
  })

  it('opens the strength breakdown from the game count and closes it on the next click', async () => {
    vi.mocked(getAdminOverview).mockResolvedValue(overview)
    vi.mocked(getAdminUsers).mockResolvedValue({ users })
    root = document.createElement('div')
    document.body.append(root)
    app = createApp(AdminView)
    app.mount(root)
    await vi.waitFor(() => expect(root?.querySelector('.admin-game-count')).not.toBeNull())
    await nextTick()

    expect(root.querySelector('.admin-game-platforms')?.textContent).toContain('PC 端 7 局')
    expect(root.querySelector('.admin-game-platforms')?.textContent).toContain('小程序端 2 局')

    const gameCount = root.querySelector<HTMLButtonElement>('.admin-game-count')!
    expect(gameCount.getAttribute('aria-expanded')).toBe('false')
    gameCount.click()
    await nextTick()
    expect(gameCount.getAttribute('aria-expanded')).toBe('true')
    expect(root.textContent).toContain('轻松陪练 9 局')
    expect(root.textContent).toContain('入门练习 0 局')
    expect(root.textContent).toContain('进阶对手 0 局')
    expect(root.textContent).toContain('认真对弈 0 局')
    expect(root.textContent).toContain('全力挑战 0 局')

    gameCount.click()
    await nextTick()
    expect(gameCount.getAttribute('aria-expanded')).toBe('false')
    expect(root.querySelector('.admin-strength-detail-row')).toBeNull()
  })
})
