import { describe, expect, it } from 'vitest'
import { applyMove, BLACK_FILE_LABELS, legalTargets, movePiece, parseFen, perpetualCheckSide, perpetualChaseSide, RED_FILE_LABELS, START_FEN, toFen, setPiece, validateSetupPosition } from './xiangqi'

describe('xiangqi positions', () => {
  it('shows traditional file numbers from each player’s side', () => {
    expect(BLACK_FILE_LABELS).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9])
    expect(RED_FILE_LABELS).toEqual([9, 8, 7, 6, 5, 4, 3, 2, 1])
  })

  it('round-trips the initial position', () => {
    expect(toFen(parseFen(START_FEN))).toBe(START_FEN)
  })

  it('allows a red pawn to advance and rejects an empty square', () => {
    const position = parseFen(START_FEN)
    expect(legalTargets(position, [6, 0])).toContainEqual([5, 0])
    expect(legalTargets(position, [5, 0])).toEqual([])
    expect(applyMove(position, [6, 0], [5, 0]).redToMove).toBe(false)
  })

  it('honors the horse-leg rule', () => {
    const position = parseFen('4k4/9/9/9/9/9/9/9/3P5/3NK4 w - - 0 1')
    expect(legalTargets(position, [9, 3])).not.toContainEqual([7, 4])
  })

  it('keeps a cannon from capturing without exactly one screen', () => {
    const position = parseFen('4k4/9/9/9/3p5/9/9/9/4P4/3CK4 w - - 0 1')
    expect(legalTargets(position, [9, 3])).not.toContainEqual([4, 3])
  })

  it('edits a setup position and validates both kings', () => {
    const position = parseFen(START_FEN)
    const edited = setPiece(position, 0, 4, '.')
    expect(edited.board[0][4]).toBe('.')
    expect(validateSetupPosition(edited).some((error) => error.includes('黑方将'))).toBe(true)
    expect(validateSetupPosition(position)).toEqual([])
  })

  it('moves a setup piece to a new square without applying move legality', () => {
    const position = parseFen(START_FEN)
    const moved = movePiece(position, [9, 0], [8, 0])
    expect(moved.board[9][0]).toBe('.')
    expect(moved.board[8][0]).toBe('R')
    expect(moved.redToMove).toBe(position.redToMove)
  })

  it('detects a repeated cycle where red checks on every cycle', () => {
    const quiet = parseFen('4k4/9/9/9/R3p4/9/9/9/9/4K4 w - - 0 1')
    const check = parseFen('4k4/9/9/9/4R4/9/9/9/9/4K4 b - - 0 1')
    expect(perpetualCheckSide([quiet, check, quiet, check, quiet])).toBe('red')
  })

  it('does not classify an ordinary repeated cycle as perpetual check', () => {
    const quiet = parseFen('4k4/9/9/9/R3p4/9/9/9/9/4K4 w - - 0 1')
    expect(perpetualCheckSide([quiet, quiet, quiet])).toBeNull()
  })

  it('detects repeated attacks on the same unprotected piece as perpetual chase', () => {
    const start = parseFen('4k4/9/9/9/R1r1P4/9/9/9/9/4K4 w - - 0 1')
    const moves = ['a5b5', 'c5c6', 'b5b6', 'c6c5', 'b6b5', 'c5c6', 'b5b6', 'c6c5', 'e0d0']
    const positions = [start]
    for (const move of moves) positions.push(applyMove(positions[positions.length - 1], [9 - Number(move[1]), 'abcdefghi'.indexOf(move[0])], [9 - Number(move[3]), 'abcdefghi'.indexOf(move[2])]))

    expect(perpetualChaseSide(positions.slice(0, -2), moves.slice(0, -2))).toBe('red')
    expect(perpetualChaseSide(positions.slice(0, -1), moves.slice(0, -1))).toBeNull()
    expect(perpetualChaseSide(positions, moves)).toBeNull()
  })

  it('detects repeated checking moves even when the exact board cycle differs', () => {
    const positions = [
      parseFen('4k4/9/9/9/R8/9/9/9/9/3K5 w - - 0 1'),
      parseFen('4k4/9/9/9/4R4/9/9/9/9/3K5 b - - 0 1'),
      parseFen('4k4/9/9/9/1R7/9/9/9/9/3K5 w - - 0 1'),
      parseFen('4k4/9/9/9/9/4R4/9/9/9/3K5 b - - 0 1'),
      parseFen('4k4/9/9/9/2R6/9/9/9/9/3K5 w - - 0 1'),
      parseFen('4k4/9/9/9/9/9/4R4/9/9/3K5 b - - 0 1'),
    ]
    expect(perpetualCheckSide(positions, ['a5e5', 'a0a1', 'b5e4', 'a1a0', 'a5e5'])).toBe('red')
  })
})

