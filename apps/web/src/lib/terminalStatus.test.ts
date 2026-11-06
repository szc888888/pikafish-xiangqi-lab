import { expect, it } from 'vitest'
import { parseFen, START_FEN, terminalStatus } from './xiangqi'

it('distinguishes check, checkmate and stalemate using legal moves', () => {
  expect(terminalStatus(parseFen(START_FEN))).toBe(null)
  expect(terminalStatus(parseFen('4k4/9/4R4/9/9/4P4/9/9/9/4K4 b - - 0 1'))).toBe(null)
  expect(terminalStatus(parseFen('R3k4/9/4R4/9/9/4P4/9/9/9/4K4 b - - 0 1'))).toBe('checkmate')
  expect(terminalStatus(parseFen('4k4/3R5/5R3/9/9/4P4/9/9/9/4K4 b - - 0 1'))).toBe('stalemate')
})
