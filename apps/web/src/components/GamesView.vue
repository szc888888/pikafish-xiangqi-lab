<script setup lang="ts">
export interface SavedGameEventView { id: string; type: 'undo' | 'hint'; createdAt: string; ply: number; positionMoves: string[]; positionFen: string; undoneMoves?: string[]; candidates?: { move: string; label: string; score: { type: 'cp' | 'mate'; value: number } | null }[] }
export interface SavedGameView { id: string; name?: string; startedAt: string; updatedAt: string; moves: string[]; side: 'red'|'black'|'watch'; events: SavedGameEventView[]; mode?: 'legacy'|'ai_hall'; opponentSnapshot?: { name: string; avatar_key: string }; result?: string|null; status?: string; terminationReason?: string|null }
defineProps<{ games: SavedGameView[] }>()
const emit = defineEmits<{ continue: [game: SavedGameView]; replay: [game: SavedGameView]; remove: [game: SavedGameView] }>()
function date(value: string) { const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false }) }
function eventLabel(event: SavedGameEventView) { return event.type === 'undo' ? `悔棋：撤回 ${event.undoneMoves?.length ?? 0} 个半回合` : `提示：${event.candidates?.[0]?.label ?? '已记录候选着法'}` }
function gameStatus(game: SavedGameView) {
  if (game.status === 'awaiting_ai') return '等待 AI 应手，可继续恢复'
  if (game.status === 'finished') {
    if (game.result === 'draw') return '和棋'
    if (game.result === 'red_win') return '红胜'
    if (game.result === 'black_win') return '黑胜'
    return '已结束'
  }
  return '进行中'
}
</script>

<template><section class="card"><div class="card-title"><div><h2>已保存棋局</h2><p class="help">棋局保存在当前浏览器或账号云端。</p></div><span class="count">{{ games.length }}</span></div><div v-if="games.length" class="game-list"><article v-for="game in games" :key="game.id" class="game-item"><div class="game-info"><strong>{{ game.opponentSnapshot?.name || game.name || date(game.startedAt) }} <span v-if="game.mode === 'ai_hall'" class="ai-label">AI 棋友</span></strong><span>{{ game.name ? `创建于 ${date(game.startedAt)} · ` : '' }}{{ game.moves.length }} 半回合 · {{ game.side === 'red' ? '执红' : game.side === 'black' ? '执黑' : '观战' }} · 更新于 {{ date(game.updatedAt) }}</span><span v-if="game.mode === 'ai_hall'" class="game-events">{{ gameStatus(game) }}<template v-if="game.terminationReason"> · {{ game.terminationReason }}</template></span><span v-if="game.events.length" class="game-events">操作记录：{{ game.events.length }} 条</span><details v-if="game.events.length" class="game-event-details"><summary>查看悔棋与提示记录</summary><ul><li v-for="event in game.events" :key="event.id"><span>{{ date(event.createdAt) }} · 第 {{ event.ply }} 半回合 · {{ eventLabel(event) }}</span><small>局面棋谱：{{ event.positionMoves.join(' ') || '起始局面' }}</small><small v-if="event.type === 'hint'">候选着法：{{ event.candidates?.map(candidate => candidate.label).join('、') }}</small></li></ul></details></div><div class="game-actions"><button @click="emit('continue',game)">继续</button><button @click="emit('replay',game)">重开</button><button class="delete-button" @click="emit('remove',game)">删除</button></div></article></div><p v-else class="empty-games">还没有保存的棋局。</p></section></template>
