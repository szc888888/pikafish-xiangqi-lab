import { onScopeDispose, ref, watch } from 'vue'
import { getGameStats, type GameStats } from './api'

export function useGameStats(userId: () => string | null, revision: () => string) {
  const data = ref<GameStats | null>(null)
  const busy = ref(false), error = ref('')
  let sequence = 0

  async function refresh() {
    const request = ++sequence, owner = userId()
    data.value = null; error.value = ''; busy.value = Boolean(owner)
    if (!owner) return
    try {
      const result = await getGameStats()
      if (request === sequence && userId() === owner) data.value = result
    } catch (cause) {
      if (request === sequence && userId() === owner) error.value = cause instanceof Error ? cause.message : '战绩加载失败'
    } finally {
      if (request === sequence) busy.value = false
    }
  }

  watch([userId, revision], () => { void refresh() }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { sequence++ })
  return { data, busy, error, refresh }
}
