export interface RecognitionControls {
  pending: boolean
  canApply: boolean
  canEdit: boolean
  canFinish: boolean
}

export function recognitionControls(hasResult: boolean, applied: boolean): RecognitionControls {
  const pending = hasResult && !applied
  return { pending, canApply: pending, canEdit: !pending, canFinish: !pending }
}
