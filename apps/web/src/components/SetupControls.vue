<script setup lang="ts">
import type { Piece, Position } from '../lib/xiangqi'
import type { RecognizedPiecePosition } from '../lib/recognitionPositions'
import { recognitionStatusLabel } from '../lib/recognitionStatus'

const props = defineProps<{
  active: boolean
  position: Position | null
  selectedTool: 'move' | 'clear' | Piece
  canUndo: boolean
  redToMove: boolean
  errors: string[]
  recognizingImage: boolean
  recognitionError: string
  recognitionPreviewUrl: string
  recognitionPieceCount: number | null
  recognitionPieces: RecognizedPiecePosition[]
  recognitionApplied: boolean
  recognitionWarnings: string[]
  canApplyRecognition: boolean
}>()

const emit = defineEmits<{
  start: []
  cancel: []
  undo: []
  clear: []
  reset: []
  finish: []
  'update:selected-tool': [tool: 'move' | 'clear' | Piece]
  'update:red-to-move': [value: boolean]
  'recognize-image': [file: File]
  'cancel-recognition': []
  'apply-recognition': []
  'discard-recognition': []
}>()

const pieces: { piece: Piece; label: string }[] = [
  { piece: 'K', label: '帅' }, { piece: 'A', label: '仕' }, { piece: 'B', label: '相' },
  { piece: 'N', label: '马' }, { piece: 'R', label: '车' }, { piece: 'C', label: '炮' }, { piece: 'P', label: '兵' },
  { piece: 'k', label: '将' }, { piece: 'a', label: '士' }, { piece: 'b', label: '象' },
  { piece: 'n', label: '马' }, { piece: 'r', label: '车' }, { piece: 'c', label: '炮' }, { piece: 'p', label: '卒' },
]
</script>

<template>
  <article class="card setup-card">
    <div class="card-title">
      <div>
        <h2>摆棋</h2>
        <p class="help">在棋盘上编辑局面，完成后作为新的对弈起点。</p>
      </div>
      <button v-if="!active" class="secondary compact" @click="emit('start')">开始摆棋</button>
    </div>
    <template v-if="active">
      <div class="setup-toolbar">
        <button class="piece-choice setup-tool" :disabled="recognitionPieceCount !== null && !recognitionApplied" :class="{ selected: selectedTool === 'move' }" @click="emit('update:selected-tool', 'move')">移动</button>
        <button v-for="item in pieces" :key="item.piece" class="piece-choice" :disabled="recognitionPieceCount !== null && !recognitionApplied" :class="{ selected: selectedTool === item.piece, 'black-choice': item.piece === item.piece.toLowerCase() }" @click="emit('update:selected-tool', item.piece)">
          {{ item.label }}
        </button>
        <button class="piece-choice clear-choice" :disabled="recognitionPieceCount !== null && !recognitionApplied" :class="{ selected: selectedTool === 'clear' }" @click="emit('update:selected-tool', 'clear')">删除</button>
      </div>
      <div class="image-recognition">
        <label class="image-upload secondary compact">
          {{ recognizingImage ? '识别中…' : '从图片识别棋盘' }}
          <input type="file" accept="image/png,image/jpeg,image/webp" :disabled="recognizingImage" @change="(event) => { const file = (event.target as HTMLInputElement).files?.[0]; if (file) emit('recognize-image', file); (event.target as HTMLInputElement).value = '' }">
        </label>
        <button v-if="recognizingImage" class="secondary compact" @click="emit('cancel-recognition')">取消识别</button>
        <span class="help image-upload-help">PNG、JPEG 或 WebP，最大 8MB</span>
      </div>
      <div v-if="recognitionPreviewUrl" class="recognition-preview">
        <img :src="recognitionPreviewUrl" alt="待识别棋盘图片预览">
        <div class="recognition-summary">
          <strong>{{ recognitionStatusLabel(recognizingImage, recognitionError, recognitionPieceCount) }}</strong>
          <span v-if="recognitionPieceCount !== null">棋盘上方黑方、下方红方；行棋方：{{ redToMove ? '红方' : '黑方' }}</span>
          <span v-for="warning in recognitionWarnings" :key="warning" class="warning-text">{{ warning }}</span>
        </div>
        <div v-if="recognitionPieces.length" class="recognition-pieces">
          <strong>识别出的棋子位置</strong>
          <ul>
            <li v-for="item in recognitionPieces" :key="`${item.square}-${item.piece}`">
              <span>{{ item.label }}</span>
              <span>{{ item.location }}</span>
              <code>{{ item.square }}</code>
            </li>
          </ul>
        </div>
        <div v-if="recognitionPieceCount !== null" class="recognition-actions">
          <button class="primary compact" :disabled="!canApplyRecognition" @click="emit('apply-recognition')">{{ recognitionApplied ? '已摆入左侧棋盘' : '摆入左侧棋盘' }}</button>
          <button class="secondary compact" @click="emit('discard-recognition')">取消</button>
        </div>
      </div>
      <p v-if="recognitionError" class="validation">{{ recognitionError }}</p>
      <label class="setup-turn">轮到
        <select :value="redToMove ? 'red' : 'black'" :disabled="recognitionPieceCount !== null && !recognitionApplied" @change="emit('update:red-to-move', ($event.target as HTMLSelectElement).value === 'red')">
          <option value="red">红方</option>
          <option value="black">黑方</option>
        </select>
      </label>
      <p v-if="errors.length" class="validation">{{ errors.join('；') }}</p>
      <div class="button-row">
        <button :disabled="!canUndo || (recognitionPieceCount !== null && !recognitionApplied)" @click="emit('undo')">撤销一步</button>
        <button :disabled="recognitionPieceCount !== null && !recognitionApplied" @click="emit('clear')">清空棋盘</button>
        <button :disabled="recognitionPieceCount !== null && !recognitionApplied" @click="emit('reset')">恢复初始局面</button>
        <button class="primary compact" :disabled="!position || (recognitionPieceCount !== null && !recognitionApplied) || recognizingImage" @click="emit('finish')">完成并开始对弈</button>
        <button class="secondary compact" @click="emit('cancel')">取消</button>
      </div>
      <p class="help">“移动”：先点棋子，再点目标格；选择棋子可添加或替换；“删除”可移除棋子。取消会恢复进入摆棋前的局面。</p>
    </template>
  </article>
</template>
