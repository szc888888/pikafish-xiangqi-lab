<script setup lang="ts">
import type { GameStats } from '../lib/api'
defineProps<{ eligible: boolean; data: GameStats | null; busy: boolean; error: string }>()
defineEmits<{ refresh: [] }>()
</script>

<template>
  <section class="card hall-stats" aria-labelledby="hall-stats-title" :aria-busy="busy">
    <div class="card-title"><h2 id="hall-stats-title">我的正式战绩</h2><button v-if="eligible" class="text-button" :disabled="busy" @click="$emit('refresh')">刷新战绩</button></div>
    <p v-if="!eligible" class="help">登录并同意隐私政策后，可查看云端正式对局战绩。</p>
    <p v-else-if="busy" class="help" role="status">正在加载战绩…</p>
    <p v-else-if="error" class="hall-error" role="alert">{{ error }}，请点击刷新战绩重试。</p>
    <template v-else-if="data">
      <dl class="hall-stats-grid"><div><dt>总对局</dt><dd>{{ data.total }}</dd></div><div><dt>胜</dt><dd>{{ data.wins }}</dd></div><div><dt>负</dt><dd>{{ data.losses }}</dd></div><div><dt>和</dt><dd>{{ data.draws }}</dd></div></dl>
      <p v-if="!data.total" class="help">还没有已完成的云端正式对局，去挑战一位 AI 棋友吧。</p>
    </template>
    <p class="help">仅统计已结束的云端正式大厅对局；游客局、导入局和未完成局不计入。</p>
  </section>
</template>
