export function undoMoves(moves: string[], count: number, future: string[] = []) {
  const steps = Math.max(0, Math.min(count, moves.length))
  if (!steps) return { moves: [...moves], future: [...future] }
  return {
    moves: moves.slice(0, -steps),
    future: [...moves.slice(-steps), ...future],
  }
}

export function advanceMoves(moves: string[], future: string[], count = 1) {
  const steps = Math.max(0, Math.min(count, future.length))
  return {
    moves: [...moves, ...future.slice(0, steps)],
    future: future.slice(steps),
  }
}
