export function createRequestSequence() {
  let sequence = 0

  return {
    next: () => ++sequence,
    invalidate: () => { sequence += 1 },
    isCurrent: (request: number) => request === sequence,
  }
}
