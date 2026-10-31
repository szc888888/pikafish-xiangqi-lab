export const BOARD_THEMES = ['classic', 'high-contrast', 'wood'] as const
export type BoardTheme = typeof BOARD_THEMES[number]

export function parseBoardTheme(value: unknown): BoardTheme {
  return BOARD_THEMES.includes(value as BoardTheme) ? value as BoardTheme : 'classic'
}
