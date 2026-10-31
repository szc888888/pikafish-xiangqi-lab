<script setup lang="ts">
import { ref } from 'vue'

type Difficulty = 'companion' | 'beginner' | 'progress' | 'serious' | 'full' | 'custom'
type HintSpeed = 'beginner' | 'regular' | 'elite' | 'custom'

const props = defineProps<{
  difficulty: Difficulty
  hintDifficulty: HintSpeed
  depth: number
  movetime: number
  threads: number
  hashMb: number
  maxThreads: number
  hintDepth: number
  hintMovetime: number
  hintMultiPv: number
  showHintCandidates: boolean
}>()

const emit = defineEmits<{
  save: []
  'update:difficulty': [value: Difficulty]
  'update:hint-difficulty': [value: HintSpeed]
  'update:depth': [value: number]
  'update:movetime': [value: number]
  'update:threads': [value: number]
  'update:hash-mb': [value: number]
  'update:hint-depth': [value: number]
  'update:hint-movetime': [value: number]
  'update:hint-multipv': [value: number]
  'update:show-hint-candidates': [value: boolean]
}>()

const open = ref(false)
const difficultyOptions = [
  { value: 'companion', label: '轻松陪练' },
  { value: 'beginner', label: '入门练习' },
  { value: 'progress', label: '进阶对手' },
  { value: 'serious', label: '认真对弈' },
  { value: 'full', label: '全力挑战' },
  { value: 'custom', label: '自定义' },
] as const
const hintSpeedOptions = [
  { value: 'beginner', label: '快速' },
  { value: 'regular', label: '标准' },
  { value: 'elite', label: '深入' },
  { value: 'custom', label: '自定义' },
] as const
</script>

<template>
  <article class="card engine-settings-card">
    <div class="card-title">
      <div>
        <h2>引擎参数</h2>
        <p class="help">固定档位使用预设参数；自定义档位可编辑搜索参数。提示速度独立于对手水平。</p>
      </div>
      <div class="settings-actions">
        <button v-if="open" class="secondary compact" @click="emit('save')">保存参数</button>
        <button class="secondary compact" @click="open = !open">{{ open ? '收起设置' : '设置参数' }}</button>
      </div>
    </div>
    <div v-if="open" class="settings-groups">
      <div class="settings-group">
        <h3>对弈难度</h3>
        <div class="settings-grid">
          <label>对手水平<select :value="props.difficulty" @change="emit('update:difficulty', ($event.target as HTMLSelectElement).value as Difficulty)"><option v-for="option in difficultyOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
          <label>搜索深度<input :value="props.depth" type="number" min="1" max="64" :disabled="props.difficulty !== 'custom'" @input="emit('update:depth', Number(($event.target as HTMLInputElement).value))"></label>
          <label>思考时间（毫秒）<input :value="props.movetime" type="number" min="0" max="120000" :disabled="props.difficulty !== 'custom'" @input="emit('update:movetime', Number(($event.target as HTMLInputElement).value))"></label>
          <label>CPU 线程<input :value="props.threads" type="number" min="1" :max="props.maxThreads" :disabled="props.difficulty !== 'custom'" @input="emit('update:threads', Number(($event.target as HTMLInputElement).value))"></label>
          <label>Hash（MB）<input :value="props.hashMb" type="number" min="16" max="8192" :disabled="props.difficulty !== 'custom'" @input="emit('update:hash-mb', Number(($event.target as HTMLInputElement).value))"></label>
        </div>
      </div>
      <div class="settings-group">
        <h3>提示速度</h3>
        <div class="settings-grid">
          <label>提示速度<select :value="props.hintDifficulty" @change="emit('update:hint-difficulty', ($event.target as HTMLSelectElement).value as HintSpeed)"><option v-for="option in hintSpeedOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
          <label>搜索深度<input :value="props.hintDepth" type="number" min="1" max="64" @input="emit('update:hint-depth', Number(($event.target as HTMLInputElement).value))"></label>
          <label>思考时间（毫秒）<input :value="props.hintMovetime" type="number" min="0" max="120000" @input="emit('update:hint-movetime', Number(($event.target as HTMLInputElement).value))"></label>
          <label>候选数量<select :value="props.hintMultiPv" @change="emit('update:hint-multipv', Number(($event.target as HTMLSelectElement).value))"><option v-for="count in 5" :key="count" :value="count">{{ count }} 条</option></select></label>
          <label class="setting-toggle"><span>显示候选着法</span><input :checked="props.showHintCandidates" type="checkbox" @change="emit('update:show-hint-candidates', ($event.target as HTMLInputElement).checked)"><small>{{ props.showHintCandidates ? '开启后逐条显示' : '关闭后只提示最优着法' }}</small></label>
        </div>
      </div>
    </div>
  </article>
</template>
