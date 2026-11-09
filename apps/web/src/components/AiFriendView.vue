<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AiFriend } from '../lib/api'

export interface HallRecentGame {
  id: string
  name: string
  startedAt: string
  moveCount: number
  opponentName?: string
  result?: string | null
  status: string
}

const props = defineProps<{
  friends: AiFriend[]
  recentGames: HallRecentGame[]
  loading: boolean
  busy: boolean
  error: string
}>()
const emit = defineEmits<{
  recommend: [experience: AiFriend['category']]
  random: []
  challenge: [botId: string, side: 'red' | 'black']
  openGames: []
}>()

const experience = ref<AiFriend['category']>('practice')
const category = ref<'all' | AiFriend['category']>('all')
const selectedId = ref<string | null>(null)
const side = ref<'red' | 'black'>('red')
const filtered = computed(() => props.friends.filter(friend => category.value === 'all' || friend.category === category.value))
const selectedFriend = computed(() => props.friends.find(friend => friend.bot_id === selectedId.value) ?? null)
const experienceNames = { casual: '休闲娱乐', practice: '日常练习', challenge: '挑战高手' }
const categoryNames = { casual: '休闲', practice: '练习', challenge: '挑战' }
function date(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('zh-CN')
}
function resultLabel(result?: string | null) {
  if (result === 'draw') return '和棋'
  if (result === 'red_win') return '红胜'
  if (result === 'black_win') return '黑胜'
  return '进行中'
}
</script>

<template>
  <main class="hall-view">
    <section class="hall-intro">
      <div class="hall-title">
        <p class="eyebrow">AI XIANGQI FRIENDS</p>
        <h2>选择一位 AI 棋友</h2>
        <p>20 位风格各异的 AI 棋友，随时可以开始一盘象棋。</p>
      </div>
      <div class="hall-controls">
        <fieldset>
          <legend>推荐目标</legend>
          <div class="segmented">
            <button v-for="(label, key) in experienceNames" :key="key" :class="{ active: experience === key }" @click="experience = key">{{ label }}</button>
          </div>
        </fieldset>
        <fieldset>
          <legend>执棋方</legend>
          <div class="segmented side-toggle">
            <button :class="{ active: side === 'red' }" @click="side = 'red'">执红</button>
            <button :class="{ active: side === 'black' }" @click="side = 'black'">执黑</button>
          </div>
        </fieldset>
        <div class="hall-actions">
          <button class="primary" :disabled="busy || loading" @click="emit('recommend', experience)">推荐棋友</button>
          <button :disabled="busy || loading" @click="emit('random')">随机挑战</button>
        </div>
      </div>
    </section>

    <p v-if="error" class="hall-error" role="alert">{{ error }}</p>
    <div class="hall-section-title">
      <h3>AI 棋友</h3>
      <span>{{ friends.length }} 位</span>
      <div class="category-filter" role="group" aria-label="棋友分类">
        <button v-for="item in [{ id: 'all', label: '全部' }, { id: 'casual', label: '休闲' }, { id: 'practice', label: '练习' }, { id: 'challenge', label: '挑战' }]" :key="item.id" :class="{ active: category === item.id }" @click="category = item.id as typeof category">{{ item.label }}</button>
      </div>
    </div>

    <div v-if="loading" class="hall-empty">正在加载棋友…</div>
    <div v-else class="friend-grid">
      <article v-for="friend in filtered" :key="friend.bot_id" class="friend-card" :class="{ selected: selectedId === friend.bot_id }">
        <button class="friend-main" :aria-pressed="selectedId === friend.bot_id" @click="selectedId = selectedId === friend.bot_id ? null : friend.bot_id">
          <span class="friend-avatar" :data-avatar="friend.avatar_key" aria-hidden="true">{{ friend.name.slice(0, 1) }}</span>
          <span class="friend-copy">
            <span class="friend-name">{{ friend.name }} <span class="ai-label">AI</span></span>
            <span class="friend-description">{{ friend.description }}</span>
            <span class="friend-meta">{{ categoryNames[friend.category] }} · {{ friend.style.join(' / ') }}</span>
          </span>
        </button>
        <div v-if="selectedId === friend.bot_id" class="friend-detail">
          <p>{{ friend.personality.join(' · ') }} · {{ friend.strength_profile }}</p>
          <button class="primary compact" :disabled="busy" @click="emit('challenge', friend.bot_id, side)">挑战 {{ friend.name }}</button>
        </div>
      </article>
      <p v-if="!filtered.length && !loading" class="hall-empty">当前分类暂无可用棋友。</p>
    </div>

    <section class="hall-recent">
      <div class="hall-section-title"><h3>最近棋局</h3><button class="text-button" @click="emit('openGames')">查看全部</button></div>
      <div v-if="recentGames.length" class="recent-list">
        <article v-for="game in recentGames.slice(0, 4)" :key="game.id" class="recent-game">
          <div><strong>{{ game.opponentName || game.name || '历史棋局' }}</strong><span>{{ date(game.startedAt) }} · {{ game.moveCount }} 半回合</span></div>
          <span class="recent-result">{{ resultLabel(game.result) }}</span>
        </article>
      </div>
      <p v-else class="hall-empty">还没有已保存的棋局</p>
    </section>
  </main>
</template>
