import type { EngineLine } from './api'

export function collectHintCandidates(
  lines: EngineLine[],
  bestmove: string,
  isBlocked: (move: string) => boolean = () => false,
  makeBestLine: (move: string) => EngineLine = move => ({ rank: 1, move, label: move, score: null, depth: null, pv: [move] }),
): EngineLine[] {
  const candidates = lines
    .filter(line => line.move !== '0000' && !isBlocked(line.move))
    .slice()
    .sort((left, right) => left.rank - right.rank)
  if (bestmove !== '0000' && !isBlocked(bestmove) && !candidates.some(line => line.move === bestmove)) {
    candidates.unshift(makeBestLine(bestmove))
  }
  return candidates
}
