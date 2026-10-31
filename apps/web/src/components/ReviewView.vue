<script setup lang="ts">
import type { ReviewResponse, ReviewItem } from '../lib/api'
import { computed, ref } from 'vue'

const props = defineProps<{ result: ReviewResponse | null; busy: boolean; error: string; selectedPly: number | null }>()
const emit = defineEmits<{ start: []; select: [item: ReviewItem]; coach: [item: ReviewItem] }>()
const filter = ref('all')
const filtered = computed(() => (props.result?.items ?? []).filter(item => filter.value === 'all' || item.grade === filter.value))
const names: Record<string, string> = { good: '正常 / 好棋', inaccuracy: '可改进', mistake: '失误', blunder: '严重失误', unknown: '无法判断' }
</script>

<template>
  <section class="view-stack">
    <article class="card"><div class="card-title"><div><h2>逐步复盘</h2><p class="help">快速搜索，最多复盘最近 120 个半回合；分值不是胜率。</p></div><button class="primary compact" :disabled="busy" @click="emit('start')">{{ busy ? '复盘中…' : '开始复盘' }}</button></div><p v-if="error" class="validation">{{ error }}</p><p v-if="busy" class="help">正在逐局面分析，当前对局不会被修改。</p><div class="filter-row"><label>筛选<select v-model="filter"><option value="all">全部着法</option><option value="inaccuracy">可改进</option><option value="mistake">失误</option><option value="blunder">严重失误</option><option value="unknown">无法判断</option></select></label><span v-if="result">已分析 {{ result.analyzed_plies }} 半回合</span></div></article>
    <article v-if="result?.status === 'stopped_rule_violation' && result.stop" class="card warning-text">复盘在第 {{ result.stop.ply }} 半回合停止：{{ result.stop.message }}</article>
    <article v-for="item in filtered" :key="item.ply" class="review-item" :class="[{ active: selectedPly === item.ply }, `grade-${item.grade}`]" @click="emit('select', item)">
      <div class="review-head"><strong>{{ Math.ceil(item.ply / 2) }}{{ item.side === 'red' ? '红' : '黑' }}：{{ item.label }}</strong><span>{{ names[item.grade] }}<template v-if="item.loss_cp !== null"> · {{ item.loss_cp }} cp</template></span></div>
      <p>最佳着法：{{ item.best_label ?? '—' }}<template v-if="item.best_move">（{{ item.best_move }}）</template></p>
      <p class="pv">{{ item.pv.join(' ') }}</p>
      <button class="text-button" @click.stop="emit('coach', item)">让教练解释这步</button>
    </article>
    <p v-if="result && !filtered.length" class="empty-games">没有符合筛选条件的着法。</p>
  </section>
</template>
