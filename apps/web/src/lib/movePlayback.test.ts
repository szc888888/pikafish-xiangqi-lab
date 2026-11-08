import { afterEach, describe, expect, it, vi } from 'vitest'
import { playMoveSteps } from './movePlayback'

describe('playMoveSteps', () => {
  afterEach(() => { vi.useRealTimers() })

  it('shows the first move immediately and delays the second move', async () => {
    vi.useFakeTimers()
    const seen: string[] = []
    const playback = playMoveSteps(['after-one', 'after-two'], move => seen.push(move), 140)

    expect(seen).toEqual(['after-one'])
    await vi.advanceTimersByTimeAsync(139)
    expect(seen).toEqual(['after-one'])
    await vi.advanceTimersByTimeAsync(1)
    await playback

    expect(seen).toEqual(['after-one', 'after-two'])
  })
})
