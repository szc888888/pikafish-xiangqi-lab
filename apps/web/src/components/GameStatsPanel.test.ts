// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import GameStatsPanel from './GameStatsPanel.vue'
import { renderComponent } from '../test/renderComponent'

const views: ReturnType<typeof renderComponent>[] = []
function render(props: Record<string, any>) { const view = renderComponent(GameStatsPanel, { eligible: true, data: null, busy: false, error: '', ...props }); views.push(view); return view }
afterEach(() => views.splice(0).forEach(view => view.unmount()))
describe('formal stats panel', () => {
  it('requires login and privacy consent without displaying fake zeros', () => {
    const view = render({ eligible: false })
    expect(view.text()).toContain('登录并同意隐私政策')
    expect(view.all('dd')).toHaveLength(0)
  })
  it('shows server counts and the formal game inclusion policy', () => {
    const view = render({ data: { total: 6, wins: 3, losses: 2, draws: 1, red_wins: 4, black_wins: 1 } })
    expect(view.all('dd').map(item => item.textContent)).toEqual(['6', '3', '2', '1'])
    expect(view.text()).toContain('游客局、导入局和未完成局不计入')
  })
  it('shows an empty state only after a successful zero-count response', () => {
    expect(render({ data: { total: 0, wins: 0, losses: 0, draws: 0, red_wins: 0, black_wins: 0 } }).text()).toContain('还没有已完成的云端正式对局')
  })
  it('keeps loading and errors distinct and allows a failed request to retry', async () => {
    const pending = render({ busy: true })
    expect(pending.button('刷新战绩').disabled).toBe(true)
    expect(pending.text()).toContain('正在加载战绩')
    const refresh = vi.fn(), failed = render({ error: '网络中断', onRefresh: refresh })
    expect(failed.all('dd')).toHaveLength(0)
    expect(failed.text()).toContain('网络中断')
    await failed.click('刷新战绩')
    expect(refresh).toHaveBeenCalledOnce()
  })
})
