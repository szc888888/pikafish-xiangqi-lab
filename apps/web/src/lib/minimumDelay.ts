export function waitForMinimumElapsed(startedAt: number, minimumDurationMs: number): Promise<void> {
  const remainingMs = minimumDurationMs - (Date.now() - startedAt)
  if (remainingMs <= 0) return Promise.resolve()
  return new Promise(resolve => globalThis.setTimeout(resolve, remainingMs))
}
