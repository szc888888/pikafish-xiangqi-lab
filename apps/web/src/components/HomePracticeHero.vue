<script setup lang="ts">
import { ref } from 'vue'
import { opponentPresets } from '../lib/engineStrength'

defineProps<{ busy: boolean; engineReady: boolean; checking: boolean }>()
const emit = defineEmits<{ start: [level: keyof typeof opponentPresets] }>()
const level = ref<keyof typeof opponentPresets>('progress')
</script>

<template>
  <section class="practice-hero" aria-labelledby="practice-title">
    <div class="practice-copy">
      <p class="eyebrow">你的 AI 象棋练习场</p>
      <h1 id="practice-title">放心下，<br>走错了就重来。</h1>
      <p class="practice-lead">不会走时看一招，走错之后换个思路再试。<br>和 AI 慢慢练，找到自己的下棋节奏。</p>
      <div class="practice-benefits" aria-label="练习模式特点"><span>无限提示</span><span>无限悔棋</span><span>五档 AI 对手</span></div>
      <div class="practice-start">
        <label for="practice-level">选择练习对手</label>
        <div class="practice-start-controls">
          <select id="practice-level" v-model="level" :disabled="busy"><option v-for="(preset, key) in opponentPresets" :key="key" :value="key">{{ preset.label }}</option></select>
          <button class="primary" :disabled="busy || !engineReady" @click="emit('start', level)">开始练习 <span aria-hidden="true">→</span></button>
        </div>
      </div>
      <p class="practice-scope">练习模式不限提示与悔棋次数，不计入正式战绩。执红先行，进入后可切换。</p>
      <p v-if="!engineReady" class="practice-unavailable" role="status">{{ checking ? '正在检查对弈服务…' : '对弈服务暂不可用，请在帮助中重新检测。' }}</p>
      <a class="browse-friends" href="#ai-friends">也可以挑选一位 AI 棋友 ↓</a>
    </div>
    <div class="practice-art" aria-hidden="true">
      <div class="art-caption">落子有思路，试错有余地</div>
      <div class="art-grid"><span class="art-river">楚河　　汉界</span><span class="art-piece art-jiang">将</span><span class="art-piece art-pao">炮</span><span class="art-piece art-ma">馬</span><span class="art-piece art-shuai">帅</span><span class="art-target"></span></div>
      <div class="art-note"><span>想试另一种走法？</span><strong>悔一步，再想一想。</strong></div>
    </div>
  </section>
</template>
