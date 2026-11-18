// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import AiFriendView from './AiFriendView.vue'
import type { AiFriend } from '../lib/api'
import { renderComponent } from '../test/renderComponent'

const friends: AiFriend[] = Array.from({ length: 20 }, (_, i) => ({ bot_id: `friend-${i}`, name: `棋友${i}`, avatar_key: `friend-${i}`, description: '日常练习', category: i < 10 ? 'practice' : 'challenge', style: ['稳健'], personality: ['耐心'], strength_profile: 'progress', config_version: 'v1', experiences: ['practice'], enabled: true, is_ai: true }))
const views: ReturnType<typeof renderComponent>[] = []
function render(extra: Record<string, any> = {}) { const view = renderComponent(AiFriendView, { friends, recentGames: [], loading: false, busy: false, error: '', ...extra }); views.push(view); return view }
afterEach(() => { views.splice(0).forEach(view => view.unmount()) })

describe('AI friend hall interaction', () => {
  it('shows all twenty AI friends and filters the selected category', async () => {
    const view = render()
    expect(view.all('article')).toHaveLength(20)
    await view.click('挑战')
    expect(view.all('article')).toHaveLength(10)
    expect(view.text()).not.toContain('棋友0')
    await view.click('全部')
    expect(view.all('article')).toHaveLength(20)
  })
  it('keeps the selected black side for recommendations and random challenges', async () => {
    const recommend = vi.fn(), random = vi.fn()
    const view = render({ onRecommend: recommend, onRandom: random })
    await view.click('执黑'); await view.click('挑战高手'); await view.click('推荐棋友'); await view.click('随机挑战')
    expect(recommend).toHaveBeenCalledWith('challenge', 'black')
    expect(random).toHaveBeenCalledWith('black')
  })
  it('opens friend details and challenges the chosen friend as black', async () => {
    const challenge = vi.fn(), view = render({ onChallenge: challenge })
    const card = view.root.querySelector<HTMLButtonElement>('[aria-pressed="false"]')!
    card.click(); await view.click('执黑'); await view.click('挑战 棋友0')
    expect(challenge).toHaveBeenCalledWith('friend-0', 'black')
  })
  it('prevents matching while busy and exposes a retry after a load failure', async () => {
    const view = render({ busy: true })
    expect(view.button('推荐棋友').disabled).toBe(true)
    expect(view.button('随机挑战').disabled).toBe(true)
    const retry = vi.fn(), failed = render({ friends: [], error: '目录加载失败', onRetry: retry })
    expect(failed.text()).toContain('目录加载失败')
    await failed.click('重新加载棋友')
    expect(retry).toHaveBeenCalledOnce()
  })
  it('distinguishes an unfinished recoverable game from a formal ending', () => {
    const view = render({ recentGames: [{ id: 'pending', name: '待恢复', startedAt: '2026-11-15', moveCount: 1, status: 'awaiting_ai' }, { id: 'done', name: '已结束', startedAt: '2026-11-15', moveCount: 20, status: 'finished', result: 'black_win', userSide: 'red', terminationReason: 'resignation' }] })
    expect(view.text()).toContain('等待 AI 应手')
    expect(view.text()).toContain('AI 棋友获胜')
    expect(view.text()).toContain('主动认输')
  })
})
