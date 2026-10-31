import { colorOf, PIECE_LABELS, toUci, type Color, type Piece, type Position } from './xiangqi'

export interface RecognizedPiecePosition {
  piece: Piece
  label: string
  side: Color
  square: string
  location: string
  row: number
  col: number
}

/** Lists occupied squares using both the app's UCI square and side-relative board coordinates. */
export function listRecognizedPieces(position: Position): RecognizedPiecePosition[] {
  const pieces: RecognizedPiecePosition[] = []
  for (let row = 0; row < position.board.length; row++) {
    for (let col = 0; col < position.board[row].length; col++) {
      const piece = position.board[row][col]
      const side = colorOf(piece)
      if (piece === '.' || !side) continue
      const file = side === 'red' ? 9 - col : col + 1
      const rank = side === 'red' ? 10 - row : row + 1
      pieces.push({
        piece,
        label: `${side === 'red' ? '红方' : '黑方'}${PIECE_LABELS[piece]}`,
        side,
        square: toUci(row, col),
        location: `第${file}路第${rank}排`,
        row,
        col,
      })
    }
  }
  return pieces
}
