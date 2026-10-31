import type { CoachMessage } from './api'

export const NEXT_STEP_QUESTION = '根据当前棋局和棋谱，下一步如何走？请给出推荐着法、理由和需要注意的变化。'

export function nextStepSession(): { question: string; messages: CoachMessage[]; context: string } {
  return { question: NEXT_STEP_QUESTION, messages: [], context: '' }
}
