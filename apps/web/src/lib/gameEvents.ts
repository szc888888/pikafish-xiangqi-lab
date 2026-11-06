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

export function createUndoEvent(moves: string[], count: number, positionFen: string, createdAt = new Date().toISOString()): UndoGameEvent {
  const steps = Math.max(0, Math.min(count, moves.length))
  return { id: `${createdAt}-${Math.random().toString(36).slice(2, 8)}`, type: 'undo', createdAt, ply: moves.length - steps + 1, positionMoves: moves.slice(0, -steps), positionFen, undoneMoves: steps ? moves.slice(-steps) : [] }
}

export function createHintEvent(moves: string[], positionFen: string, candidates: HintEventCandidate[], createdAt = new Date().toISOString()): HintGameEvent {
  return { id: `${createdAt}-${Math.random().toString(36).slice(2, 8)}`, type: 'hint', createdAt, ply: moves.length + 1, positionMoves: [...moves], positionFen, candidates: candidates.map(candidate => ({ ...candidate, score: candidate.score ? { ...candidate.score } : null })) }
}
