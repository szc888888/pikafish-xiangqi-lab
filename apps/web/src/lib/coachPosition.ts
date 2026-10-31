export function coachPosition(baseFen: string, currentFen: string, moves: string[], replayableHistory: boolean) {
  return replayableHistory
    ? { fen: baseFen, moves }
    : { fen: currentFen, moves: [] as string[] }
}
