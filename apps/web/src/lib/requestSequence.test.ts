import { describe, expect, it } from 'vitest'
import { createRequestSequence } from './requestSequence'

describe('request sequence', () => {
  it('invalidates an earlier request when a newer request starts', () => {
    const sequence = createRequestSequence()
    const earlier = sequence.next()
    const current = sequence.next()

    expect(sequence.isCurrent(earlier)).toBe(false)
    expect(sequence.isCurrent(current)).toBe(true)
  })

  it('invalidates pending requests when the workflow is cleared', () => {
    const sequence = createRequestSequence()
    const pending = sequence.next()

    sequence.invalidate()

    expect(sequence.isCurrent(pending)).toBe(false)
  })
})
