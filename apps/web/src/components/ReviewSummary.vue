<script setup lang="ts">
import type { ReviewItem } from '../lib/api'
import { momentExplanation, reviewGradeNames } from '../lib/reviewSummary'
defineProps<{ moments: ReviewItem[]; selectedPly: number | null }>()
const emit = defineEmits<{ select: [item: ReviewItem]; coach: [item: ReviewItem] }>()
</script>

<template>
  <section class="review-summary" aria-label="关键时刻">
    <div class="card-title"><div><h2>这局值得回看的 {{ moments.length }} 个时刻</h2><p class="help">先看自己的棋，每次记住一个改进就好。</p></div><span class="pill">轻量陪练</span></div>
    <p v-if="!moments.length" class="help">本次快速复盘没有筛出明确的改进时刻，不必凑满三条；这也不代表每步都已得到充分验证。</p>
    <article v-for="item in moments" :key="item.ply" class="review-moment" :class="[{ active: selectedPly === item.ply }, `grade-${item.grade}`]">
      <button class="moment-select" :aria-pressed="selectedPly === item.ply" @click="emit('select', item)"><strong>第 {{ Math.ceil(item.ply / 2) }} 回合 · {{ item.side === 'red' ? '红方' : '黑方' }} {{ item.label }}</strong><span>{{ reviewGradeNames[item.grade] }}</span></button>
      <p>{{ momentExplanation(item) }}</p>
      <p class="moment-better">引擎推荐：<strong>{{ item.best_label }}</strong></p>
      <button class="text-button" @click="emit('coach', item)">追问教练</button>
    </article>
    <p class="help">结论来自引擎快速搜索，分值不是胜率；解释仅作学习参考。</p>
  </section>
</template>
