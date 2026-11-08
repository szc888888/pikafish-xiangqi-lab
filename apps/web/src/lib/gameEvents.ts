import { applyMove, describeUci, fromUci, parseFen, toFen, type Position } from './xiangqi'

export interface HintEventCandidate {
  move: string
  label: string
  score: { type: 'cp' | 'mate'; value: number } | null
}

export interface UndoGameEvent {
  id: string
  type: 'undo'
  createdAt: string
  ply: number
  positionMoves: string[]
  positionFen: string
  undoneMoves: string[]
}

export interface HintGameEvent {
  id: string
  type: 'hint'
  createdAt: string
  ply: number
  positionMoves: string[]
  positionFen: string
  candidates: HintEventCandidate[]
}

export type GameEvent = UndoGameEvent | HintGameEvent

export function eventPosition(initialFen: string, event: GameEvent): Position {
  let replayed = parseFen(initialFen)
  for (const move of event.positionMoves) replayed = applyMove(replayed, fromUci(move.slice(0, 2)), fromUci(move.slice(2)))
  const snapshot = parseFen(event.positionFen)
  if (toFen(replayed) !== toFen(snapshot)) throw new Error('事件局面与棋谱前缀不一致')
  return replayed
}

export function eventHighlightMove(event: GameEvent): string | null {
  return event.type === 'hint' ? event.candidates[0]?.move ?? null : event.undoneMoves.at(-1) ?? null
}

export function eventMoveLabels(initialFen: string, event: GameEvent): string[] {
  if (event.type !== 'undo') return event.candidates.map(candidate => candidate.label)
  let position = eventPosition(initialFen, event)
  return event.undoneMoves.map(move => {
    const label = describeUci(position, move)
    try { position = applyMove(position, fromUci(move.slice(0, 2)), fromUci(move.slice(2))) } catch { return move }
    return label
  })
}

export function eventSide(initialFen: string, event: GameEvent): 'red' | 'black' {
  return eventPosition(initialFen, event).redToMove ? 'red' : 'black'
}

export function createUndoEvent(moves: string[], count: number, positionFen: string, createdAt = new Date().toISOString()): UndoGameEvent {
  const steps = Math.max(0, Math.min(count, moves.length))
  return { id: `${createdAt}-${Math.random().toString(36).slice(2, 8)}`, type: 'undo', createdAt, ply: moves.length - steps + 1, positionMoves: moves.slice(0, -steps), positionFen, undoneMoves: steps ? moves.slice(-steps) : [] }
}

export function createHintEvent(moves: string[], positionFen: string, candidates: HintEventCandidate[], createdAt = new Date().toISOString()): HintGameEvent {
  return { id: `${createdAt}-${Math.random().toString(36).slice(2, 8)}`, type: 'hint', createdAt, ply: moves.length + 1, positionMoves: [...moves], positionFen, candidates: candidates.map(candidate => ({ ...candidate, score: candidate.score ? { ...candidate.score } : null })) }
}
