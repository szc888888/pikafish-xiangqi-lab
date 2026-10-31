<script setup lang="ts">
import { computed } from 'vue'
import { describeUci, formatPv, type Position } from '../lib/xiangqi'
import type { Analysis, OpeningLine } from '../lib/api'

const props = defineProps<{ analysis: Analysis | null; position: Position; busy: boolean; multipv: number; fen: string; openings: OpeningLine[]; selectedLine: number | null }>()
const emit = defineEmits<{ analyze: []; 'update:multipv': [value: number]; 'update:fen': [value: string]; loadFen: []; selectLine: [move: string]; coach: [context: string] }>()
const score = computed(() => {
  const value = props.analysis?.score
  if (!value) return '—'
  if (value.type === 'mate') return value.value > 0 ? `将死 ${value.value} 步` : `被将死 ${Math.abs(value.value)} 步`
  return `${value.value > 0 ? '+' : ''}${value.value} 分`
})
function pv(line: string[]) { return formatPv(props.position, line) }
function explain(move: string, label: string, variation: string) { emit('coach', `请解释候选着法 ${label}（${move}）。主变化：${variation || '暂无'}。`) }
</script>

<template>
  <section class="view-stack">
    <article class="card">
      <div class="card-title"><div><h2>局面分析</h2><p class="help">引擎分值是搜索评估，不是胜率。</p></div><button class="secondary" :disabled="busy" @click="emit('analyze')">{{ busy ? '分析中…' : '分析当前局面' }}</button></div>
      <div class="controls analysis-controls"><label>候选着法数量<select :value="multipv" @change="emit('update:multipv', Number(($event.target as HTMLSelectElement).value))"><option v-for="n in 5" :key="n" :value="n">{{ n }} 条</option></select></label><div class="metrics"><div><span>最佳着法</span><strong>{{ analysis?.lines[0]?.label ?? (analysis ? describeUci(position, analysis.bestmove) : '—') }}</strong></div><div><span>当前评估</span><strong>{{ score }}</strong></div><div><span>搜索深度</span><strong>{{ analysis?.depth ?? '—' }}</strong></div><div><span>搜索速度</span><strong>{{ analysis?.nps?.toLocaleString() ?? '—' }}</strong></div></div></div>
      <p v-if="analysis?.filter_summary?.rejected.length" class="help">已过滤 {{ analysis.filter_summary.rejected.length }} 条不合法或违反棋规的候选，当前显示 {{ analysis.filter_summary.returned }} 条。</p>
      <h3 class="section-heading">候选着法</h3>
      <p v-if="!analysis" class="empty-games">分析后显示排名、分值与主变化。</p>
      <article v-for="line in analysis?.lines ?? []" :key="line.rank" class="candidate" :class="{ active: selectedLine === line.rank }" @click="emit('selectLine', line.move)">
        <div class="candidate-head"><strong>{{ line.rank }}. {{ line.label }}</strong><span>{{ line.score?.type === 'mate' ? `将死 ${line.score.value}` : line.score ? `${line.score.value > 0 ? '+' : ''}${line.score.value} cp` : '无分值' }}</span></div>
        <p class="pv">{{ pv(line.pv) }}</p><button class="text-button" @click.stop="explain(line.move,line.label,pv(line.pv))">问教练</button>
      </article>
      <p v-if="analysis && !analysis.lines.length" class="help">引擎没有返回候选变化。</p>
    </article>
    <article class="card"><div class="card-title"><h2>局面编辑</h2></div><textarea :value="fen" rows="3" spellcheck="false" @input="emit('update:fen', ($event.target as HTMLTextAreaElement).value)"/><button class="secondary" @click="emit('loadFen')">加载 FEN</button></article>
    <article class="card"><div class="card-title"><div><h2>开局库</h2><p class="help">内置示例主线，偏离后不会猜测名称。</p></div></div><p v-if="!openings.length" class="empty-games">当前棋谱未匹配到内置开局。</p><div v-for="opening in openings" :key="opening.name" class="opening-item"><strong>{{ opening.name }}</strong><small>{{ opening.aliases.join(' · ') }}</small><p class="help">{{ opening.source }}</p><div class="opening-moves"><button v-for="next in opening.next_moves" :key="next.move" @click="emit('selectLine', next.move)">{{ next.label }}</button></div></div></article>
  </section>
</template>
