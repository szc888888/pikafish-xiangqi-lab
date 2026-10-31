<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { CoachMessage } from '../lib/api'
import { handleCoachInputKeydown } from '../lib/coachInput'
const props = defineProps<{ messages: CoachMessage[]; busy: boolean; unavailable: string }>()
const emit = defineEmits<{ send: [question: string]; nextStep: [] }>()
const question = ref('')
const scroller = ref<HTMLElement | null>(null)
watch(() => props.messages.length, async () => { await nextTick(); scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' }) })
function send() { const value = question.value.trim(); if (!value || props.busy) return; question.value = ''; emit('send', value) }
function nextStep() { if (props.busy) return; question.value = ''; emit('nextStep') }
</script>

<template>
  <section class="card coach-card"><div class="card-title"><div><h2>AI 教练</h2><p class="help">问题会结合当前浏览局面、本局棋谱和最近对话；刷新页面后会清空。</p></div><span class="pill">当前会话</span></div>
    <p v-if="unavailable" class="help warning-text">{{ unavailable }}</p>
    <div ref="scroller" class="chat-list"><p v-if="!messages.length" class="empty-games">可以问：“这步为什么不好？”“下一步计划应该考虑什么？”</p><article v-for="(message,index) in messages" :key="index" class="chat-message" :class="message.role"><strong>{{ message.role === 'user' ? '我' : '教练' }}</strong><p>{{ message.content }}</p></article><p v-if="busy" class="help">教练正在分析…</p></div>
    <form class="chat-form" @submit.prevent="send"><textarea v-model="question" rows="3" maxlength="1200" placeholder="输入你想了解的问题…" @keydown="handleCoachInputKeydown($event, send)"/><div class="chat-actions"><button class="primary" :disabled="busy || !question.trim()">发送</button><button type="button" class="secondary" :disabled="busy" @click="nextStep">下一步</button></div></form>
  </section>
</template>
