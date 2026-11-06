<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { CoachMessage, ReviewItem, ReviewResponse } from '../lib/api'
import type { ReviewSnapshot } from '../lib/useReviewSession'
import { applyMove, fromUci, type Position } from '../lib/xiangqi'
import type { BoardTheme } from '../lib/boardTheme'
import BoardView from './BoardView.vue'
import ReviewSummary from './ReviewSummary.vue'
import { handleCoachInputKeydown } from '../lib/coachInput'

const props = defineProps<{ snapshot: ReviewSnapshot; result: ReviewResponse | null; busy: boolean; error: string; board: Position; selected: ReviewItem | null; moments: ReviewItem[]; messages: CoachMessage[]; chatBusy: boolean; chatError: string; stale: boolean; theme: BoardTheme; retryReason: string }>()
const emit = defineEmits<{ close: []; retry: []; select: [item: ReviewItem]; ask: [question: string] }>()
const dialog = ref<HTMLElement | null>(null), closeButton = ref<HTMLButtonElement | null>(null)
const question = ref(''), chatOpen = ref(false), preview = ref<'before' | 'actual' | 'better'>('before'), allMoves = ref(false)
const boardPosition = computed(() => {
  const move = preview.value === 'actual' ? props.selected?.move : preview.value === 'better' ? props.selected?.best_move : null
  if (!move) return props.board
  try { return applyMove(props.board, fromUci(move.slice(0, 2)), fromUci(move.slice(2))) } catch { return props.board }
})
function select(item: ReviewItem) { emit('select', item); preview.value = 'before'; chatOpen.value = false; question.value = '' }
function coach(item: ReviewItem) { if (props.selected?.ply !== item.ply) select(item); chatOpen.value = true; void nextTick(() => dialog.value?.querySelector('textarea')?.focus()) }
function ask(value = question.value) { if (!value.trim() || props.chatBusy) return; emit('ask', value); question.value = '' }
watch(() => props.selected?.ply, () => { preview.value = 'before'; question.value = '' })
watch(() => props.busy, busy => { if (busy) { chatOpen.value = false; preview.value = 'before'; allMoves.value = false; question.value = '' } })
let previousFocus: HTMLElement | null = null
let previousOverflow = ''
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); emit('close'); return }
  if (event.key !== 'Tab') return
  const focusable = [...(dialog.value?.querySelectorAll<HTMLElement>('button:not(:disabled), textarea, input, summary, [tabindex="0"]') ?? [])].filter(el => el.getClientRects().length)
  const first = focusable[0], last = focusable.at(-1)
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onMounted(() => { previousFocus = document.activeElement as HTMLElement; previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; closeButton.value?.focus(); document.addEventListener('keydown', keydown) })
onUnmounted(() => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', keydown); previousFocus?.focus() })
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop review-backdrop" @click.self="emit('close')">
      <section ref="dialog" class="review-dialog" role="dialog" aria-modal="true" aria-labelledby="review-dialog-title" tabindex="-1">
        <header class="review-dialog-head"><div><p class="eyebrow">轻量 AI 陪练</p><h2 id="review-dialog-title">{{ busy ? '正在回看这局棋…' : '看懂关键一步，下局进步一点' }}</h2><p class="help">本次复盘：{{ snapshot.moves.length }} 个半回合 · 关闭后继续当前对局</p></div><button ref="closeButton" class="compact" @click="emit('close')">关闭复盘</button></header>
        <p v-if="stale" class="review-notice" role="status">当前对局已变化，以下展示的是打开复盘时的棋谱快照。</p>
        <p v-if="busy" class="review-notice" role="status">正在逐局面分析，较长棋谱需要等待。可以关闭窗口继续下棋，结果就绪后再查看。</p>
        <p v-if="error" class="validation review-notice" role="alert">{{ error }}</p>
        <div class="review-dialog-grid">
          <div class="review-board-area"><BoardView :position="boardPosition" :interactive="false" :theme="theme" :last-move="preview === 'actual' ? selected?.move : null" :highlight-move="preview === 'better' ? selected?.best_move : preview === 'before' ? selected?.move : null"/><template v-if="selected"><p class="help">第 {{ Math.ceil(selected.ply / 2) }} 回合 · {{ selected.side === 'red' ? '红方' : '黑方' }} · {{ preview === 'before' ? '行棋前局面' : preview === 'actual' ? '实战走法后' : '推荐走法后' }}</p><div class="review-preview-controls"><button :aria-pressed="preview === 'before'" @click="preview = 'before'">行棋前</button><button :aria-pressed="preview === 'actual'" @click="preview = 'actual'">实战：{{ selected.label }}</button><button v-if="selected.best_move" :aria-pressed="preview === 'better'" @click="preview = 'better'">推荐：{{ selected.best_label }}</button></div></template><p v-else class="help">当前复盘快照的最后局面</p></div>
          <div class="review-dialog-content">
            <ReviewSummary v-if="result" :moments="moments" :selected-ply="selected?.ply ?? null" @select="select" @coach="coach"/>
            <p v-if="result?.stop" class="review-notice warning-text">仅分析合法前缀：第 {{ result.stop.ply }} 半回合因{{ result.stop.message }}停止。</p>
            <section v-if="chatOpen && selected" class="review-chat" aria-label="追问 AI 教练"><h2>聊聊这一步</h2><p class="help">教练围绕当前选中时刻回答；切换时刻会开启新对话。</p><div class="review-chat-list" aria-live="polite"><article v-for="(entry, index) in messages" :key="index" class="chat-message" :class="entry.role"><strong>{{ entry.role === 'user' ? '我' : '教练' }}</strong><p>{{ entry.content }}</p></article><p v-if="chatBusy" class="help">教练正在分析…</p></div><p v-if="chatError" class="validation" role="alert">{{ chatError }}</p><div class="review-quick-questions"><button :disabled="chatBusy" @click="ask('这步为什么不好？请用一句话解释。')">为什么不好？</button><button :disabled="chatBusy" @click="ask('推荐走法好在哪里？简短解释，区分引擎结论和教学推断。')">推荐好在哪？</button></div><form @submit.prevent="ask()"><textarea v-model="question" aria-label="向教练追问这一步" rows="2" maxlength="1200" placeholder="继续问教练…" @keydown="handleCoachInputKeydown($event, () => ask())"/><button class="primary compact" :disabled="chatBusy || !question.trim()">发送追问</button></form></section>
            <template v-if="result"><button class="text-button" :aria-expanded="allMoves" @click="allMoves = !allMoves">{{ allMoves ? '收起' : '查看' }}全部 {{ result.items.length }} 步</button><div v-if="allMoves" class="review-all-moves"><button v-for="item in result.items" :key="item.ply" :aria-pressed="selected?.ply === item.ply" @click="select(item)">第 {{ Math.ceil(item.ply / 2) }} 回合 {{ item.side === 'red' ? '红' : '黑' }} · {{ item.label }}</button></div></template>
          </div>
        </div>
        <footer class="review-dialog-footer"><span class="help">{{ retryReason || '可按当前对局进度重新分析' }}</span><button :disabled="busy || !!retryReason" :title="retryReason" @click="emit('retry')">{{ error ? '重试复盘' : '重新分析当前棋谱' }}</button></footer>
      </section>
    </div>
  </Teleport>
</template>
