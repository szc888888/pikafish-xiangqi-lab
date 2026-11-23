import { describe, expect, it } from 'vitest'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import GamesView from './GamesView.vue'

describe('game source display', () => {
  it.each([
    ['pc', 'PC 端'], ['mini_program', '小程序端'], ['mobile_web', '手机网页'],
    ['unknown', '暂无记录'], [undefined, '暂无记录'], ['invalid', '暂无记录'],
  ])('shows %s per game, including legacy records', async (clientPlatform, label) => {
    const html = await renderToString(createSSRApp(GamesView, { games: [{
      id: 'game', clientPlatform, name: '测试棋局', startedAt: '2026-11-23', updatedAt: '2026-11-23',
      moves: [], events: [], side: 'red',
    }] }))
    expect(html).toContain(`对局来源：${label}`)
    expect(html).toContain('测试棋局')
    expect(html).toContain('继续')
  })
})
