<script setup lang="ts">
import { onMounted, ref } from 'vue'

defineProps<{
  features: { label: string; text: string; state: string }[]
  services: { key: string; label: string; text: string; state: string }[]
  checkedLabel: string
  error: string
  busy: boolean
}>()
const emit = defineEmits<{ close: []; refresh: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
onMounted(() => dialog.value?.showModal())
function close() { dialog.value?.close() }
</script>

<template>
  <dialog ref="dialog" class="service-dialog" aria-labelledby="service-title" @close="emit('close')" @click="event => { if (event.target === dialog) close() }">
    <div class="service-dialog-head"><div><p class="eyebrow">帮助与支持</p><h2 id="service-title">服务状态</h2></div><button autofocus @click="close">关闭</button></div>
    <div class="feature-status-list"><div v-for="feature in features" :key="feature.label"><span>{{ feature.label }}</span><strong><span class="service-dot" :class="feature.state"/>{{ feature.text }}</strong></div></div>
    <details class="service-diagnostics"><summary>诊断详情</summary><div class="service-grid"><div v-for="service in services" :key="service.key" class="service-item"><span class="service-dot" :class="service.state"/><span>{{ service.label }}</span><strong>{{ service.text }}</strong></div></div><p v-if="error" class="service-error help">{{ error }}</p></details>
    <div class="service-dialog-footer"><p class="help" role="status">{{ checkedLabel }}</p><button :disabled="busy" @click="emit('refresh')">{{ busy ? '检测中…' : '重新检测' }}</button></div>
  </dialog>
</template>
