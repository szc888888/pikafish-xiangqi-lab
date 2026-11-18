export function hallResultLabel(result?: string | null, side?: string | null): string {
  if (result === 'draw') return '和棋'
  if (result !== 'red_win' && result !== 'black_win') return '进行中'
  if (side !== 'red' && side !== 'black') return result === 'red_win' ? '红胜' : '黑胜'
  return result === `${side}_win` ? '你获胜' : 'AI 棋友获胜'
}

export function terminationLabel(reason?: string | null): string {
  if (!reason) return ''
  const names: Record<string, string> = { checkmate: '将死', stalemate: '困毙', rule_draw: '规则性和棋', resignation: '主动认输' }
  return names[reason] ?? '其他结束原因'
}
