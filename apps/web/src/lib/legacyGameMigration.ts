export interface LegacyGameRecord { id: string; serverVersion?: number }

export interface LegacyMigrationResult<T extends LegacyGameRecord> {
  imported: Array<{ game: T; remote: unknown }>
  failed: Array<{ game: T; message: string }>
}

export async function migrateLegacyGames<T extends LegacyGameRecord>(games: T[], importer: (game: T) => Promise<unknown>): Promise<LegacyMigrationResult<T>> {
  const result: LegacyMigrationResult<T> = { imported: [], failed: [] }
  for (const game of games.filter((item) => item.serverVersion === undefined)) {
    try { result.imported.push({ game, remote: await importer(game) }) }
    catch (error) { result.failed.push({ game, message: error instanceof Error ? error.message : '棋局导入失败' }) }
  }
  return result
}
