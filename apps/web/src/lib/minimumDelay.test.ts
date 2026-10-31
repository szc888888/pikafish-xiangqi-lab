import { afterEach, describe, expect, it, vi } from 'vitest'
import { waitForMinimumElapsed } from './minimumDelay'

describe('waitForMinimumElapsed', () => {
  afterEach(() => { vi.useRealTimers() })

  it('waits for the remaining response delay after a fast engine search', async () => {
    vi.useFakeTimers()
    const startedAt = Date.now()
    const waiting = waitForMinimumElapsed(startedAt, 1500)

    expect(vi.getTimerCount()).toBe(1)
    await vi.advanceTimersByTimeAsync(1499)
    expect(vi.getTimerCount()).toBe(1)
    await vi.advanceTimersByTimeAsync(1)
    await expect(waiting).resolves.toBeUndefined()
  })

  it('does not add a delay after search already took longer than the minimum', async () => {
    vi.useFakeTimers()
    const startedAt = Date.now()
    await vi.advanceTimersByTimeAsync(1600)

    await expect(waitForMinimumElapsed(startedAt, 1500)).resolves.toBeUndefined()
    expect(vi.getTimerCount()).toBe(0)
  })
})
