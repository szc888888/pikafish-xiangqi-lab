import { describe, expect, it } from 'vitest'
import { opponentProfiles, normalizeSavedEngineSettings } from './engineStrength'

describe('engine strength profiles', () => {
  it('presents the five user-facing opponent levels', () => {
    expect(opponentProfiles.map(profile => profile.label)).toEqual([
      '轻松陪练', '入门练习', '进阶对手', '认真对弈', '全力挑战',
    ])
  })

  it('migrates legacy and missing saved profiles to the documented levels', () => {
    expect(normalizeSavedEngineSettings({ difficulty: 'regular' }).difficulty).toBe('progress')
    expect(normalizeSavedEngineSettings({ difficulty: 'elite' }).difficulty).toBe('full')
    expect(normalizeSavedEngineSettings({}).difficulty).toBe('progress')
  })

  it('preserves valid custom parameters and repairs out-of-range saved values', () => {
    expect(normalizeSavedEngineSettings({ difficulty: 'custom', depth: 3, movetime_ms: 500, threads: 2, hash_mb: 128 }))
      .toMatchObject({ difficulty: 'custom', depth: 3, movetime_ms: 500, threads: 2, hash_mb: 128 })
    expect(normalizeSavedEngineSettings({ difficulty: 'custom', depth: 0, movetime_ms: -1, threads: 0, hash_mb: 8 }))
      .toMatchObject({ difficulty: 'custom', depth: 1, movetime_ms: 0, threads: 1, hash_mb: 16 })
  })

  it('normalizes fixed profiles to their preset parameters even when a legacy save has stale values', () => {
    expect(normalizeSavedEngineSettings({ difficulty: 'progress', depth: 12, movetime_ms: 9000, threads: 4, hash_mb: 2048 }))
      .toMatchObject({ difficulty: 'progress', depth: 4, movetime_ms: 700, threads: 1, hash_mb: 64 })
  })
})
