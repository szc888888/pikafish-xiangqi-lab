<script setup lang="ts">
export interface SavedGameView { id: string; name?: string; startedAt: string; updatedAt: string; moves: string[]; side: 'red'|'black'|'watch' }
defineProps<{ games: SavedGameView[] }>()
const emit = defineEmits<{ continue: [game: SavedGameView]; replay: [game: SavedGameView]; remove: [game: SavedGameView] }>()
function date(value: string) { const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false }) }
</script>

<template><section class="card"><div class="card-title"><div><h2>已保存棋局</h2><p class="help">棋局保存在当前浏览器，保存后的摆棋局面也可以下次继续。</p></div><span class="count">{{ games.length }}</span></div><div v-if="games.length" class="game-list"><article v-for="game in games" :key="game.id" class="game-item"><div class="game-info"><strong>{{ game.name || date(game.startedAt) }}</strong><span>{{ game.name ? `创建于 ${date(game.startedAt)} · ` : '' }}{{ game.moves.length }} 半回合 · {{ game.side === 'red' ? '执红' : game.side === 'black' ? '执黑' : '观战' }} · 更新于 {{ date(game.updatedAt) }}</span></div><div class="game-actions"><button @click="emit('continue',game)">继续</button><button @click="emit('replay',game)">重开</button><button class="delete-button" @click="emit('remove',game)">删除</button></div></article></div><p v-else class="empty-games">点击“保存为新棋局”后，当前局面会出现在这里。</p></section></template>
