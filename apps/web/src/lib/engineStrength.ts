export type OpponentDifficulty = 'companion' | 'beginner' | 'progress' | 'serious' | 'full' | 'custom'

export interface SavedOpponentSettings {
  difficulty: OpponentDifficulty
  depth: number
  movetime_ms: number
  threads: number
  hash_mb: number
}

export const opponentPresets = {
  companion: { label: '轻松陪练', description: '较弱候选中稳定选择，适合熟悉规则', depth: 1, movetime: 100, threads: 1, hashMb: 16 },
  beginner: { label: '入门练习', description: '降低搜索强度，保留明显战术', depth: 2, movetime: 250, threads: 1, hashMb: 32 },
  progress: { label: '进阶对手', description: '兼顾棋力与陪练体验', depth: 4, movetime: 700, threads: 1, hashMb: 64 },
  serious: { label: '认真对弈', description: '较强对手，适合日常对局', depth: 8, movetime: 1500, threads: 2, hashMb: 256 },
  full: { label: '全力挑战', description: '始终选择最佳合法候选，搜索更深入', depth: 15, movetime: 5000, threads: 4, hashMb: 1024 },
} as const

export const opponentProfiles = Object.entries(opponentPresets).map(([key, profile]) => ({ key, ...profile }))

function bounded(value: unknown, fallback: number, low: number, high: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  return Math.max(low, Math.min(Math.trunc(value), high))
}

export function normalizeSavedEngineSettings(value: unknown): SavedOpponentSettings {
  const game = value && typeof value === 'object' ? value as Record<string, any> : {}
  const stored = game.difficultySettings && typeof game.difficultySettings === 'object'
    ? game.difficultySettings as Record<string, unknown>
    : game
  const rawDifficulty = game.difficulty ?? stored.difficulty
  const migrated = rawDifficulty === 'regular' ? 'progress' : rawDifficulty === 'elite' ? 'full' : rawDifficulty
  const difficulty: OpponentDifficulty = migrated === 'companion' || migrated === 'beginner' || migrated === 'progress' || migrated === 'serious' || migrated === 'full' || migrated === 'custom'
    ? migrated
    : 'progress'
  const defaults = difficulty === 'custom' ? opponentPresets.progress : opponentPresets[difficulty]
  if (difficulty !== 'custom') {
    return {
      difficulty,
      depth: defaults.depth,
      movetime_ms: defaults.movetime,
      threads: defaults.threads,
      hash_mb: defaults.hashMb,
    }
  }
  return {
    difficulty,
    depth: bounded(stored.depth ?? game.depth, defaults.depth, 1, 64),
    movetime_ms: bounded(stored.movetime_ms ?? game.movetime, defaults.movetime, 0, 120_000),
    threads: bounded(stored.threads, defaults.threads, 1, 16),
    hash_mb: bounded(stored.hash_mb ?? game.hashMb, defaults.hashMb, 16, 8192),
  }
}
