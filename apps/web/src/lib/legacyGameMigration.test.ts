import { describe, expect, it, vi } from 'vitest'
import { importLegacyVersion, migrateLegacyGames } from './legacyGameMigration'

describe('legacy browser game migration', () => {
  it('preserves a conflicting local version and reuses its import identity after a lost response', async () => {
    const payload = { legacy_id: 'old-id', initial_fen: 'start', moves: ['a0a1'], events: [{ id: 'hint-1' }], user_side: 'red' }
    const stored = new Map<string, typeof payload>([['old-id', { ...payload, moves: ['b0c2'] }]])
    let loseResponse = true
    const importer = async (value: typeof payload) => {
      if (value.legacy_id === 'old-id') throw Object.assign(new Error('conflict'), { status: 409, code: 'legacy_game_conflict' })
      stored.set(value.legacy_id, value)
      if (loseResponse) { loseResponse = false; throw new Error('network') }
      return value
    }
    await expect(importLegacyVersion(payload, importer)).rejects.toThrow('network')
    const remote = await importLegacyVersion(payload, importer)
    expect(stored.size).toBe(2)
    expect(stored.get('old-id')?.moves).toEqual(['b0c2'])
    expect(remote).toEqual({ ...payload, legacy_id: expect.stringMatching(/^local-version-[a-f0-9]{64}$/) })
    expect(payload.legacy_id).toBe('old-id')
  })

  it('does not retry validation, account, or unrelated conflict errors', async () => {
    for (const error of [Object.assign(new Error('invalid'), {status: 422}), Object.assign(new Error('consent'), {status: 403}), Object.assign(new Error('other conflict'), {status: 409, code: 'other'})]) {
      const importer = vi.fn().mockRejectedValue(error)
      await expect(importLegacyVersion({ legacy_id: 'id', initial_fen: 'start', moves: [], events: [] }, importer)).rejects.toBe(error)
      expect(importer).toHaveBeenCalledTimes(1)
    }
  })

  it('imports only browser-only records and keeps failed records available for retry', async () => {
    const importer = vi.fn()
      .mockResolvedValueOnce({ id: 'server-1' })
      .mockRejectedValueOnce(new Error('棋谱无效'))
    const games = [
      { id: 'legacy-1', serverVersion: undefined },
      { id: 'cloud-1', serverVersion: 0 },
      { id: 'legacy-2', serverVersion: undefined },
    ]

    const result = await migrateLegacyGames(games, importer)

    expect(importer).toHaveBeenCalledTimes(2)
    expect(result.imported.map(({ game }) => game.id)).toEqual(['legacy-1'])
    expect(result.failed.map(({ game, message }) => [game.id, message])).toEqual([['legacy-2', '棋谱无效']])
  })
})
