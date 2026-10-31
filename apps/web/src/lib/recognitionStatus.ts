export function recognitionStatusLabel(
  recognizing: boolean,
  error: string,
  pieceCount: number | null,
): string {
  if (recognizing) return '正在识别棋盘（最长等待约 10 分钟）'
  if (error) return '识别未成功'
  if (pieceCount !== null) return `识别到 ${pieceCount} 枚棋子`
  return ''
}
