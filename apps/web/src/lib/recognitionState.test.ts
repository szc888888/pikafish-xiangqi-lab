import { describe, expect, it } from 'vitest'
import { recognitionControls } from './recognitionState'

describe('recognition setup controls', () => {
  it('keeps the preview visible after applying while unlocking the setup board', () => {
    expect(recognitionControls(true, false)).toEqual({ pending: true, canApply: true, canEdit: false, canFinish: false })
    expect(recognitionControls(true, true)).toEqual({ pending: false, canApply: false, canEdit: true, canFinish: true })
  })
})
