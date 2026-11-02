import { describe, expect, it, vi } from 'vitest'
import { migrateLegacyGames } from './legacyGameMigration'

describe('legacy browser game migration', () => {
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
