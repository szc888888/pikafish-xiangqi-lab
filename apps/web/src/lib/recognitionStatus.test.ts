import { describe, expect, it } from 'vitest'
import { recognitionStatusLabel } from './recognitionStatus'

describe('recognition status label', () => {
  it('shows an error state after recognition fails while keeping the preview', () => {
    expect(recognitionStatusLabel(false, '图片中的棋盘未能完整识别', null)).toBe('识别未成功')
  })

  it('shows the pending state only while the request is active', () => {
    expect(recognitionStatusLabel(true, '', null)).toBe('正在识别棋盘（最长等待约 10 分钟）')
  })

  it('shows the recognized piece count when a result is available', () => {
    expect(recognitionStatusLabel(false, '', 32)).toBe('识别到 32 枚棋子')
  })
})
