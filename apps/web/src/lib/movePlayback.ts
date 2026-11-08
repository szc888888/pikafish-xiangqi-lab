import { waitForMinimumElapsed } from './minimumDelay'

export const MOVE_PLAYBACK_STEP_MS = 140

export async function playMoveSteps<T>(steps: T[], apply: (step: T, index: number) => void, stepDelayMs = MOVE_PLAYBACK_STEP_MS): Promise<void> {
  for (const [index, step] of steps.entries()) {
    if (index > 0) await waitForMinimumElapsed(Date.now(), stepDelayMs)
    apply(step, index)
  }
}
