import { describe, expect, it } from 'vitest'
import { parseBoardTheme } from './boardTheme'

describe('parseBoardTheme', () => {
  it('accepts each supported board theme', () => {
    expect(parseBoardTheme('classic')).toBe('classic')
    expect(parseBoardTheme('high-contrast')).toBe('high-contrast')
    expect(parseBoardTheme('wood')).toBe('wood')
  })

  it('falls back to classic for missing or invalid saved values', () => {
    expect(parseBoardTheme(null)).toBe('classic')
    expect(parseBoardTheme('neon')).toBe('classic')
  })
})
