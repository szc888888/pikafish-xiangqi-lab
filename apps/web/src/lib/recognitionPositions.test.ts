import { describe, expect, it } from 'vitest'
import { parseFen } from './xiangqi'
import { listRecognizedPieces } from './recognitionPositions'

describe('recognized piece positions', () => {
  it('lists every piece with side-relative Chinese board coordinates and UCI square', () => {
    const pieces = listRecognizedPieces(parseFen('r3k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1'))

    expect(pieces).toEqual([
      expect.objectContaining({ side: 'black', label: '黑方車', square: 'a9', location: '第1路第1排' }),
      expect.objectContaining({ side: 'black', label: '黑方将', square: 'e9', location: '第5路第1排' }),
      expect.objectContaining({ side: 'red', label: '红方車', square: 'a0', location: '第9路第1排' }),
      expect.objectContaining({ side: 'red', label: '红方帅', square: 'e0', location: '第5路第1排' }),
    ])
  })

  it('does not include empty squares and preserves board order', () => {
    const pieces = listRecognizedPieces(parseFen('4k4/9/9/9/9/9/9/9/1P7/4K4 b - - 0 1'))

    expect(pieces.map((piece) => piece.square)).toEqual(['e9', 'b1', 'e0'])
  })
})
