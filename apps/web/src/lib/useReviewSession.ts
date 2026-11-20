import { computed, ref } from 'vue'
import { coachChat, review, type CoachMessage, type ReviewItem, type ReviewResponse, type ReviewProgress } from './api'
import { applyMove, fromUci, parseFen } from './xiangqi'
import { createRequestSequence } from './requestSequence'
import { keyMoments, momentExplanation, type ReviewSide } from './reviewSummary'
import type { GameEvent } from './gameEvents'

export interface ReviewSnapshot { fen: string; moves: string[]; side: ReviewSide; gameId: string | null; events?: GameEvent[] }
export function reviewSnapshotKey(value: ReviewSnapshot): string { return JSON.stringify([value.gameId, value.fen, value.moves, value.side, value.events ?? []]) }
export function reviewAnalysisKey(value: ReviewSnapshot): string { return JSON.stringify([value.fen, value.moves, value.side]) }
function cloneSnapshot(source: ReviewSnapshot): ReviewSnapshot {
  return { ...source, moves: [...source.moves], events: source.events?.map(event => ({ ...event, positionMoves: [...event.positionMoves], ...(event.type === 'undo' ? { undoneMoves: [...event.undoneMoves] } : { candidates: event.candidates.map(candidate => ({ ...candidate, score: candidate.score ? { ...candidate.score } : null })) }) })) }
}

export function useReviewSession(
  analyze: (snapshot: ReviewSnapshot, progress?: ReviewProgress, refresh?: boolean) => Promise<ReviewResponse> = (snapshot, progress) => review({ fen: snapshot.fen, moves: snapshot.moves, depth: 8, movetime_ms: 350, threads: 1, hash_mb: 128 }, progress),
  chat: typeof coachChat = coachChat,
) {
  const snapshot = ref<ReviewSnapshot | null>(null)
  const result = ref<ReviewResponse | null>(null)
  const busy = ref(false), error = ref(''), selected = ref<ReviewItem | null>(null)
  const progress = ref({ completed: 0, total: 0 })
  const messages = ref<CoachMessage[]>([]), chatBusy = ref(false), chatError = ref('')
  const requests = createRequestSequence(), chats = createRequestSequence()
  const moments = computed(() => keyMoments(result.value?.items ?? [], snapshot.value?.side ?? 'watch'))
  const board = computed(() => {
    if (!snapshot.value) return null
    let position = parseFen(snapshot.value.fen)
    const end = selected.value ? selected.value.ply - 1 : result.value?.analyzed_plies ?? snapshot.value.moves.length
    for (const move of snapshot.value.moves.slice(0, end)) position = applyMove(position, fromUci(move.slice(0, 2)), fromUci(move.slice(2)))
    return position
  })
  function select(item: ReviewItem | null) {
    selected.value = item
    chats.invalidate(); messages.value = []; chatError.value = ''; chatBusy.value = false
  }
  function restore(source: ReviewSnapshot, response: ReviewResponse) {
    requests.invalidate()
    snapshot.value = cloneSnapshot(source)
    result.value = response; busy.value = false; error.value = ''
    progress.value = { completed: response.analyzed_plies, total: source.moves.length }
    select(moments.value[0] ?? null)
  }
  async function start(source: ReviewSnapshot, refresh = false): Promise<ReviewResponse | null> {
    const request = requests.next()
    snapshot.value = cloneSnapshot(source)
    result.value = null; busy.value = true; error.value = ''; select(null)
    progress.value = { completed: 0, total: source.moves.length }
    const captured = snapshot.value!
    try {
      const response = await analyze(captured, (completed, total) => {
        if (!requests.isCurrent(request)) throw new Error('复盘已取消')
        progress.value = { completed, total }
      }, refresh)
      if (!requests.isCurrent(request)) return null
      if (response.game_id) snapshot.value!.gameId = response.game_id
      result.value = response
      select(moments.value[0] ?? null)
      return response
    } catch (e) { if (requests.isCurrent(request)) error.value = e instanceof Error ? e.message : '复盘失败，请重试'; return null }
    finally { if (requests.isCurrent(request)) busy.value = false }
  }
  async function ask(question: string) {
    const current = snapshot.value, item = selected.value
    if (!current || !item || chatBusy.value || !question.trim()) return
    const request = chats.next()
    const prior = messages.value.slice(-20).map(message => ({ ...message, content: message.content.slice(0, 2000) }))
    messages.value = [...messages.value, { role: 'user', content: question.trim() }]; chatBusy.value = true; chatError.value = ''
    try {
      const response = await chat({ fen: current.fen, moves: current.moves.slice(0, item.ply - 1), question: question.trim(), messages: prior,
        context: `用户正在复盘第 ${Math.ceil(item.ply / 2)} 回合${item.side === 'red' ? '红方' : '黑方'}的行棋前局面；实战走了${item.label}。引擎推荐${item.best_label ?? '未知'}。${momentExplanation(item)}主变化（供理解，输出使用中文记谱）：${item.pv.slice(0, 12).join(' ')}。请区分规则事实、引擎评估和教学推断，简短解释，不确定时说明。` })
      if (!chats.isCurrent(request)) return
      if (response.ai_available) messages.value.push({ role: 'assistant', content: response.answer })
      else chatError.value = response.ai_message ?? 'AI 教练暂不可用，仍可查看引擎复盘'
    } catch (e) { if (chats.isCurrent(request)) chatError.value = e instanceof Error ? e.message : 'AI 教练暂不可用' }
    finally { if (chats.isCurrent(request)) chatBusy.value = false }
  }
  function invalidate() { requests.invalidate(); chats.invalidate(); busy.value = false; chatBusy.value = false }
  return { snapshot, result, busy, progress, error, selected, messages, chatBusy, chatError, moments, board, start, restore, select, ask, invalidate,
    isStale: (live: ReviewSnapshot) => snapshot.value !== null && reviewSnapshotKey(snapshot.value) !== reviewSnapshotKey(live) }
}
