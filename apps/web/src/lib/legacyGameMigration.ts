export interface LegacyGameRecord { id: string; serverVersion?: number }

interface LegacyVersionPayload { legacy_id: string; initial_fen: string; moves: string[]; events: unknown[] }

export async function importLegacyVersion<T extends LegacyVersionPayload, R>(payload: T, importer: (payload: T) => Promise<R>): Promise<R> {
  try { return await importer(payload) }
  catch (error) {
    if (!(error instanceof Error && 'status' in error && error.status === 409 && 'code' in error && error.code === 'legacy_game_conflict')) throw error
    // A locally edited/undone version must not overwrite the earlier cloud game.
    // Content-derived identity also makes retries safe after a lost response.
    const content = JSON.stringify([payload.legacy_id, payload.initial_fen, payload.moves, payload.events])
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content))
    const fingerprint = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
    return importer({ ...payload, legacy_id: `local-version-${fingerprint}` })
  }
}

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
