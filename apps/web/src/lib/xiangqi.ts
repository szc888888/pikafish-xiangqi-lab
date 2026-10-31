export type Color = 'red' | 'black'
export type Piece = 'r' | 'n' | 'b' | 'a' | 'k' | 'c' | 'p' | 'R' | 'N' | 'B' | 'A' | 'K' | 'C' | 'P' | '.'
export type Board = Piece[][]

export const START_FEN = 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1'
export const FILES = 'abcdefghi'
export const RED_FILE_LABELS = [9, 8, 7, 6, 5, 4, 3, 2, 1]
export const BLACK_FILE_LABELS = [1, 2, 3, 4, 5, 6, 7, 8, 9]
export const PIECE_LABELS: Record<string, string> = { r: '車', n: '馬', b: '象', a: '士', k: '将', c: '炮', p: '卒', R: '車', N: '馬', B: '相', A: '仕', K: '帅', C: '炮', P: '兵' }

export interface Position {
  board: Board
  redToMove: boolean
}

export function parseFen(fen: string): Position {
  const fields = fen.trim().split(/\s+/)
  const rows = fields[0]?.split('/') ?? []
  if (rows.length !== 10 || !['w', 'b'].includes(fields[1] ?? '')) throw new Error('FEN 必须包含 10 行棋盘和 w/b 行棋方')
  const board = rows.map((row) => {
    const cells: Piece[] = []
    for (const char of row) {
      if (/\d/.test(char)) cells.push(...Array(Number(char)).fill('.') as Piece[])
      else if ('rnbakcpRNBKACP'.includes(char)) cells.push(char as Piece)
      else throw new Error(`未知棋子: ${char}`)
    }
    if (cells.length !== 9) throw new Error('FEN 每行必须有 9 个格子')
    return cells
  })
  return { board, redToMove: fields[1] === 'w' }
}

export function toUci(row: number, col: number): string { return `${FILES[col]}${9 - row}` }
export function fromUci(square: string): [number, number] { return [9 - Number(square[1]), FILES.indexOf(square[0])] }
export function colorOf(piece: Piece): Color | null { return piece === '.' ? null : piece === piece.toUpperCase() ? 'red' : 'black' }
export function clonePosition(position: Position): Position { return { board: position.board.map((row) => [...row]), redToMove: position.redToMove } }

export function setPiece(position: Position, row: number, col: number, piece: Piece): Position {
  if (row < 0 || row >= 10 || col < 0 || col >= 9) throw new Error('棋盘位置无效')
  const next = clonePosition(position)
  next.board[row][col] = piece
  return next
}

// 摆棋移动只编辑棋盘，不改变行棋方，也不套用实战走法合法性。
export function movePiece(position: Position, source: [number, number], target: [number, number]): Position {
  if (![source, target].every(([row, col]) => row >= 0 && row < 10 && col >= 0 && col < 9)) throw new Error('棋盘位置无效')
  const piece = position.board[source[0]][source[1]]
  if (piece === '.') throw new Error('起点没有棋子')
  const next = clonePosition(position)
  next.board[target[0]][target[1]] = piece
  next.board[source[0]][source[1]] = '.'
  return next
}

export function validateSetupPosition(position: Position): string[] {
  const errors: string[] = []
  const counts: Record<string, number> = {}
  for (const row of position.board) for (const piece of row) if (piece !== '.') counts[piece] = (counts[piece] ?? 0) + 1
  if ((counts.K ?? 0) !== 1) errors.push('红方帅必须恰好一个')
  if ((counts.k ?? 0) !== 1) errors.push('黑方将必须恰好一个')
  const limits: Partial<Record<Piece, number>> = { K: 1, k: 1, A: 2, a: 2, B: 2, b: 2, R: 2, r: 2, C: 2, c: 2, N: 2, n: 2, P: 5, p: 5 }
  for (const [piece, limit] of Object.entries(limits)) if ((counts[piece] ?? 0) > limit) errors.push(String(PIECE_LABELS[piece]) + '数量不能超过' + String(limit) + '个')
  return errors
}

export function toFen(position: Position): string {
  const rows = position.board.map((row) => {
    let result = ''; let empty = 0
    for (const piece of row) {
      if (piece === '.') empty++
      else { if (empty) result += empty; result += piece; empty = 0 }
    }
    if (empty) result += empty
    return result
  })
  return `${rows.join('/')} ${position.redToMove ? 'w' : 'b'} - - 0 1`
}

function inside(row: number, col: number): boolean { return row >= 0 && row < 10 && col >= 0 && col < 9 }
function palace(row: number, col: number, red: boolean): boolean { return col >= 3 && col <= 5 && (red ? row >= 7 : row <= 2) }
function same(piece: Piece, color: Color): boolean { return colorOf(piece) === color }

function pseudo(position: Position, source: [number, number]): [number, number][] {
  const { board } = position
  const [row, col] = source
  const piece = board[row][col]
  if (piece === '.') return []
  const red = colorOf(piece) === 'red'
  const kind = piece.toLowerCase()
  const moves: [number, number][] = []
  const add = (r: number, c: number) => { if (inside(r, c) && !same(board[r][c], red ? 'red' : 'black')) moves.push([r, c]) }
  if (kind === 'r' || kind === 'c') {
    for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      let r = row + dr; let c = col + dc; let jumped = false
      while (inside(r, c)) {
        const target = board[r][c]
        if (kind === 'c' && !jumped) { if (target === '.') moves.push([r, c]); else jumped = true }
        else if (kind === 'c') { if (target !== '.') { if (!same(target, red ? 'red' : 'black')) moves.push([r, c]); break } }
        else if (target === '.') moves.push([r, c])
        else { if (!same(target, red ? 'red' : 'black')) moves.push([r, c]); break }
        r += dr; c += dc
      }
    }
  } else if (kind === 'n') {
    for (const [dr, dc, lr, lc] of [[-2, -1, -1, 0], [-2, 1, -1, 0], [2, -1, 1, 0], [2, 1, 1, 0], [-1, -2, 0, -1], [1, -2, 0, -1], [-1, 2, 0, 1], [1, 2, 0, 1]]) if (inside(row + lr, col + lc) && board[row + lr][col + lc] === '.') add(row + dr, col + dc)
  } else if (kind === 'b') {
    for (const [dr, dc] of [[-2, -2], [-2, 2], [2, -2], [2, 2]]) { const r = row + dr; const c = col + dc; if (inside(r, c) && board[row + dr / 2][col + dc / 2] === '.' && (red ? r >= 5 : r <= 4)) add(r, c) }
  } else if (kind === 'a') {
    for (const [dr, dc] of [[-1, -1], [-1, 1], [1, -1], [1, 1]]) { const r = row + dr; const c = col + dc; if (palace(r, c, red)) add(r, c) }
  } else if (kind === 'k') {
    for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) { const r = row + dr; const c = col + dc; if (palace(r, c, red)) add(r, c) }
    const dr = red ? -1 : 1
    for (let r = row + dr; inside(r, col); r += dr) {
      const target = board[r][col]
      if (target !== '.') { if (target.toLowerCase() === 'k' && !same(target, red ? 'red' : 'black')) moves.push([r, col]); break }
    }
    const otherKing = king(position, !red)
    if (otherKing && otherKing[1] === col && board.slice(Math.min(row, otherKing[0]) + 1, Math.max(row, otherKing[0])).every((line) => line[col] === '.')) moves.push(otherKing)
  } else if (kind === 'p') {
    const forward = red ? -1 : 1
    add(row + forward, col)
    if (red ? row <= 4 : row >= 5) { add(row, col - 1); add(row, col + 1) }
  }
  return moves
}

function king(position: Position, red: boolean): [number, number] | null { for (let r = 0; r < 10; r++) for (let c = 0; c < 9; c++) if (position.board[r][c] === (red ? 'K' : 'k')) return [r, c]; return null }
function attacked(position: Position, target: [number, number], byRed: boolean): boolean { for (let r = 0; r < 10; r++) for (let c = 0; c < 9; c++) { const piece = position.board[r][c]; if (colorOf(piece) === (byRed ? 'red' : 'black') && pseudo(position, [r, c]).some(([tr, tc]) => tr === target[0] && tc === target[1])) return true } return false }
export function isInCheck(position: Position, red: boolean): boolean { const k = king(position, red); return !k || attacked(position, k, !red) }

export function legalTargets(position: Position, source: [number, number]): [number, number][] {
  const piece = position.board[source[0]][source[1]]
  if (piece === '.') return []
  const red = colorOf(piece) === 'red'
  return pseudo(position, source).filter((target) => { const next = clonePosition(position); next.board[target[0]][target[1]] = piece; next.board[source[0]][source[1]] = '.'; return !isInCheck(next, red) })
}

function repetitionKey(position: Position): string { return `${position.board.map((row) => row.join('')).join('/')} ${position.redToMove ? 'w' : 'b'}` }
function materialKey(position: Position): string { return position.board.flat().filter((piece) => piece !== '.').sort().join('') }

// Positions includes the starting position. A repeated key is a perpetual check
// only when the same side gives check on every move in each repeated cycle.
export function perpetualCheckSide(positions: Position[], moves: string[] = []): Color | null {
  if (positions.length < 3) return null
  const occurrences = new Map<string, number[]>()
  positions.forEach((position, index) => { const key = repetitionKey(position); occurrences.set(key, [...(occurrences.get(key) ?? []), index]) })
  for (const indexes of occurrences.values()) {
    if (indexes.length < 3) continue
    const cycleIndexes = indexes.slice(-3)
    for (const side of ['red', 'black'] as Color[]) {
      let valid = true
      for (let cycle = 1; cycle < cycleIndexes.length && valid; cycle++) {
        let checked = false
        for (let index = cycleIndexes[cycle - 1]; index < cycleIndexes[cycle]; index++) {
          const mover = positions[index].redToMove ? 'red' : 'black'
          if (mover === side) {
            checked = true
            if (!isInCheck(positions[index + 1], side === 'red' ? false : true)) valid = false
          }
        }
        if (!checked) valid = false
      }
      if (valid) return side
    }
  }
  if (moves.length === positions.length - 1) {
    for (const side of ['red', 'black'] as Color[]) {
      const checks: { index: number; move: string }[] = []
      for (let index = 0; index < positions.length - 1; index++) {
        const mover = positions[index].redToMove ? 'red' : 'black'
        if (mover !== side) continue
        if (!isInCheck(positions[index + 1], side === 'red' ? false : true)) { checks.length = 0; continue }
        checks.push({ index, move: moves[index] })
        if (checks.length >= 3) {
          const window = checks.slice(-3)
          const repeatedMove = new Set(window.map((item) => item.move)).size < window.length
          const unchangedMaterial = materialKey(positions[window[0].index]) === materialKey(positions[index + 1])
          if (repeatedMove && unchangedMaterial) return side
        }
      }
    }
  }
  return null
}

function moveSquares(move: string): [[number, number], [number, number]] | null {
  if (!/^[a-i][0-9][a-i][0-9]$/.test(move)) return null
  return [fromUci(move.slice(0, 2)), fromUci(move.slice(2))]
}

function attacksPiece(position: Position, source: [number, number], target: [number, number]): boolean {
  const piece = position.board[source[0]]?.[source[1]]
  const targetPiece = position.board[target[0]]?.[target[1]]
  if (!piece || piece === '.' || !targetPiece || targetPiece === '.' || colorOf(piece) === colorOf(targetPiece)) return false
  return legalTargets(position, source).some(([row, col]) => row === target[0] && col === target[1])
}

// Detects three consecutive attacks on the same moving opposing piece by one side.
// This is the project's long-chase rule; ordinary repeated positions remain allowed.
export function perpetualChaseSide(positions: Position[], moves: string[] = []): Color | null {
  if (moves.length !== positions.length - 1 || moves.length < 5) return null
  for (const side of ['red', 'black'] as Color[]) {
    const attacks: { index: number; attackerTo: [number, number]; targetFrom: [number, number]; targetTo: [number, number] }[] = []
    for (let index = 0; index + 2 < moves.length; index += 1) {
      const mover = positions[index].redToMove ? 'red' : 'black'
      if (mover !== side) continue
      const first = moveSquares(moves[index]); const reply = moveSquares(moves[index + 1]); const follow = moveSquares(moves[index + 2])
      if (!first || !reply || !follow || follow[0][0] !== first[1][0] || follow[0][1] !== first[1][1]) continue
      const afterFirst = positions[index + 1]
      if (!attacksPiece(afterFirst, first[1], reply[0])) continue
      const afterFollow = positions[index + 3]
      if (!attacksPiece(afterFollow, follow[1], reply[1])) continue
      attacks.push({ index, attackerTo: first[1], targetFrom: reply[0], targetTo: reply[1] })
    }
    for (let start = 0; start < attacks.length; start += 1) {
      let count = 1
      for (let next = start + 1; next < attacks.length; next += 1) {
        const previous = attacks[next - 1]; const current = attacks[next]
        if (current.index !== previous.index + 2 || current.targetFrom[0] !== previous.targetTo[0] || current.targetFrom[1] !== previous.targetTo[1]) break
        count += 1
        if (count >= 3 && current.index + 2 === moves.length - 1) return side
      }
    }
  }
  return null
}

export function applyMove(position: Position, source: [number, number], target: [number, number]): Position {
  if (!legalTargets(position, source).some(([r, c]) => r === target[0] && c === target[1])) throw new Error('不合法的走法')
  const next = clonePosition(position); next.board[target[0]][target[1]] = next.board[source[0]][source[1]]; next.board[source[0]][source[1]] = '.'; next.redToMove = !next.redToMove; return next
}

const CN_NUM = ['一', '二', '三', '四', '五', '六', '七', '八', '九']

// 把 UCI 着法转成传统中文记法，例如 b2e2 -> 炮二平五。
export function describeUci(position: Position, uci: string): string {
  if (!/^[a-i][0-9][a-i][0-9]$/.test(uci)) return uci
  const from = fromUci(uci.slice(0, 2))
  const to = fromUci(uci.slice(2))
  const piece = position.board[from[0]][from[1]]
  if (piece === '.') return uci
  const red = colorOf(piece) === 'red'
  const name = PIECE_LABELS[piece]
  const fileOf = (col: number) => red ? CN_NUM[8 - col] : String(col + 1)
  const forward = red ? to[0] < from[0] : to[0] > from[0]
  const action = to[0] === from[0] ? '平' : forward ? '进' : '退'
  let dest: string
  if (to[0] === from[0]) dest = fileOf(to[1])
  else if (['r', 'c', 'p'].includes(piece.toLowerCase())) dest = red ? CN_NUM[Math.abs(to[0] - from[0]) - 1] : String(Math.abs(to[0] - from[0]))
  else dest = fileOf(to[1])
  return `${name}${fileOf(from[1])}${action}${dest}`
}

// 把 PV 转成带回合号的可读棋谱，例如 "1. 炮二平五 马8进7"。
export function formatPv(position: Position, pv: string[]): string {
  let pos = clonePosition(position)
  const parts: string[] = []
  let number = 1
  for (const move of pv) {
    const desc = describeUci(pos, move)
    if (pos.redToMove) parts.push(`${number}. ${desc}`)
    else parts.push(desc)
    try {
      pos = applyMove(pos, fromUci(move.slice(0, 2)), fromUci(move.slice(2)))
    } catch {
      parts.push(`(${move})`)
      break
    }
    if (pos.redToMove) number++
  }
  return parts.join(' ')
}

