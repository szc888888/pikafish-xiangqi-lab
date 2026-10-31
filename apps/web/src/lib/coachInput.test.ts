import { describe, expect, it, vi } from 'vitest'
import { handleCoachInputKeydown } from './coachInput'

function keyboardEvent(overrides: Partial<KeyboardEvent> = {}) {
  return {
    key: 'Enter',
    shiftKey: false,
    isComposing: false,
    preventDefault: vi.fn(),
    ...overrides,
  } as unknown as KeyboardEvent
}

describe('coach input keyboard handling', () => {
  it('submits on Enter without inserting a newline', () => {
    const event = keyboardEvent()
    const submit = vi.fn()

    handleCoachInputKeydown(event, submit)

    expect(event.preventDefault).toHaveBeenCalledOnce()
    expect(submit).toHaveBeenCalledOnce()
  })

  it('keeps Shift+Enter available for a newline', () => {
    const event = keyboardEvent({ shiftKey: true })
    const submit = vi.fn()

    handleCoachInputKeydown(event, submit)

    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(submit).not.toHaveBeenCalled()
  })

  it('does not submit while an IME composition is active', () => {
    const event = keyboardEvent({ isComposing: true })
    const submit = vi.fn()

    handleCoachInputKeydown(event, submit)

    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(submit).not.toHaveBeenCalled()
  })
})
