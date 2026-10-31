<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { applyMove, BLACK_FILE_LABELS, legalTargets, PIECE_LABELS, RED_FILE_LABELS, toUci, type Position } from '../lib/xiangqi'
import type { BoardTheme } from '../lib/boardTheme'

const props = defineProps<{ position: Position; interactive: boolean; theme?: BoardTheme; setupMode?: boolean; setupSelectedSquare?: [number, number] | null; lastMove?: string | null; highlightMove?: string | null }>()
const emit = defineEmits<{ square: [row: number, col: number] }>()
const injectedSetupMode = inject('xiangqi-setup-mode', ref(false))
const selected = ref<[number, number] | null>(null)
watch(() => props.position, () => { selected.value = null })
const legal = computed(() => selected.value ? legalTargets(props.position, selected.value) : [])
function click(row: number, col: number) {
  if (!props.interactive) return
  if (props.setupMode || injectedSetupMode.value) {
    emit('square', row, col)
    selected.value = null
    return
  }
  const piece = props.position.board[row][col]
  if (selected.value && legal.value.some(([r, c]) => r === row && c === col)) {
    emit('square', row, col)
    selected.value = null
  } else if (piece !== '.' && (piece === piece.toUpperCase()) === props.position.redToMove) {
    selected.value = [row, col]
    emit('square', row, col)
  } else {
    selected.value = null
    emit('square', row, col)
  }
}
</script>

<template>
  <div class="board-wrap">
    <div class="files top"><span v-for="file in BLACK_FILE_LABELS" :key="`top-${file}`">{{ file }}</span></div>
    <div class="board" :class="`board-theme-${theme ?? 'classic'}`">
      <div class="palace-diagonals palace-black" aria-hidden="true" />
      <div class="palace-diagonals palace-red" aria-hidden="true" />
      <template v-for="(row, rowIndex) in position.board" :key="rowIndex">
        <div v-for="(piece, colIndex) in row" :key="`${rowIndex}-${colIndex}`" class="square"
          :style="{ left: `${(colIndex + 0.5) * (100 / 9)}%`, top: `${(rowIndex + 0.5) * 10}%` }"
          :class="{ selected: selected?.[0] === rowIndex && selected?.[1] === colIndex, 'setup-source': setupSelectedSquare?.[0] === rowIndex && setupSelectedSquare?.[1] === colIndex, target: legal.some(([r,c]) => r === rowIndex && c === colIndex), last: lastMove?.includes(toUci(rowIndex,colIndex)), 'hint-from': highlightMove?.slice(0,2) === toUci(rowIndex,colIndex), 'hint-to': highlightMove?.slice(2,4) === toUci(rowIndex,colIndex) }"
          @click="click(rowIndex, colIndex)">
          <span v-if="piece !== '.'" class="piece" :class="piece === piece.toUpperCase() ? 'red-piece' : 'black-piece'">{{ PIECE_LABELS[piece] }}</span>
          <span v-if="legal.some(([r,c]) => r === rowIndex && c === colIndex)" class="hint" />
        </div>
      </template>
      <div class="river">楚河 <span>汉界</span></div>
    </div>
    <div class="files bottom"><span v-for="file in RED_FILE_LABELS" :key="`bottom-${file}`">{{ file }}</span></div>
  </div>
</template>
