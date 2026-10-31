import { describe, expect, it } from 'vitest'
import { NEXT_STEP_QUESTION, nextStepSession } from './coachNextStep'

describe('coach next-step action', () => {
  it('creates a fresh session with the next-move question', () => {
    expect(nextStepSession()).toEqual({
      question: NEXT_STEP_QUESTION,
      messages: [],
      context: '',
    })
  })
})
