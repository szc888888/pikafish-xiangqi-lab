<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getAdminOverview, getAdminUsers, resetAdminEngine, type AdminOverview, type AdminUser } from '../lib/api'

const overview = ref<AdminOverview | null>(null)
const users = ref<AdminUser[]>([])
const busy = ref(false)
const error = ref('')
const refreshedAt = ref('')
const expandedUserId = ref<string | null>(null)

async function refresh() {
  busy.value = true
  error.value = ''
  try {
    const [nextOverview, nextUsers] = await Promise.all([getAdminOverview(), getAdminUsers()])
    overview.value = nextOverview
    users.value = nextUsers.users
    refreshedAt.value = new Date().toLocaleString()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '管理员数据加载失败'
  } finally {
    busy.value = false
  }
}

async function resetEngine() {
  busy.value = true
  error.value = ''
  try {
    const result = await resetAdminEngine()
    if (overview.value) overview.value.engine = { ...overview.value.engine, ...result.engine }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '引擎重置失败'
  } finally {
    busy.value = false
  }
}

function date(value: string) { return new Date(value).toLocaleString() }
function strengthSummary(item: AdminUser) {
  return item.opponent_strengths.length ? item.opponent_strengths.map(entry => `${entry.label} ${entry.games}`).join(' · ') : '暂无 AI 对局'
}
function strengthGames(item: AdminUser, key: string) {
  return item.opponent_strengths.find(entry => entry.key === key)?.games ?? 0
}
onMounted(() => void refresh())
</script>

<template>
  <section class="admin-page" aria-labelledby="admin-title">
    <div class="admin-heading">
      <div><p class="eyebrow">SYSTEM CONTROL</p><h1 id="admin-title">管理中心</h1><p class="subtitle">查看账号规模、引擎容量和当前棋力配置。</p></div>
      <div class="button-row admin-actions"><button :disabled="busy" @click="refresh">{{ busy ? '处理中…' : '刷新数据' }}</button><button class="secondary" :disabled="busy || !overview" @click="resetEngine">重置引擎池</button></div>
    </div>
    <p v-if="error" class="validation" role="alert">{{ error }}</p>
    <p v-if="refreshedAt" class="help">最近刷新：{{ refreshedAt }}</p>
    <template v-if="overview">
      <div class="admin-metrics">
        <article class="card"><span>注册用户</span><strong>{{ overview.users.total }}</strong><small>{{ overview.users.active }} 个活跃 · {{ overview.users.deletion_pending }} 个待删除</small></article>
        <article class="card"><span>云端棋局</span><strong>{{ overview.games.total }}</strong><small>包含未完成和已完成记录</small></article>
        <article class="card"><span>引擎并发</span><strong>{{ overview.engine.inflight }} / {{ overview.engine.max_inflight }}</strong><small>{{ overview.engine.ready_engines }} / {{ overview.engine.pool_size }} 个进程就绪</small></article>
      </div>
      <div class="admin-columns">
        <article class="card">
          <div class="card-title"><div><h2>引擎池</h2><p class="help">每个进程独占一条 UCI 会话，池内搜索可并行。</p></div><span class="pill" :class="overview.engine.ready ? '' : 'admin-pill-warn'">{{ overview.engine.ready ? 'READY' : 'OFFLINE' }}</span></div>
          <dl class="admin-detail-list"><div><dt>进程池</dt><dd>{{ overview.engine.pool_size }} 个</dd></div><div><dt>在途上限</dt><dd>{{ overview.engine.max_inflight }} 个</dd></div><div><dt>Pikafish</dt><dd>{{ overview.engine.engine_version || '未读取' }}</dd></div><div><dt>NNUE</dt><dd>{{ overview.engine.nnue_version || '未读取' }}</dd></div><div><dt>路径</dt><dd>{{ overview.engine.path }}</dd></div></dl>
          <div class="admin-engine-list"><div v-for="item in overview.engine.engines" :key="item.index"><span>引擎 {{ item.index }}</span><b :class="item.ready ? 'admin-ok' : 'admin-muted'">{{ item.ready ? `运行中 · PID ${item.pid}` : item.configured ? '未就绪' : '未配置' }}</b></div></div>
          <p v-if="overview.engine.error" class="help admin-error">{{ overview.engine.error }}</p>
        </article>
        <article class="card"><div class="card-title"><div><h2>棋力档位</h2><p class="help">大厅棋友只引用这些服务端档位。</p></div></div><div class="admin-profile-list"><div v-for="profile in overview.profiles" :key="profile.key"><strong>{{ profile.label }}</strong><span>{{ profile.key }} · 深度 {{ profile.depth }} · {{ profile.movetime_ms }} ms · {{ profile.threads }} 线程 · {{ profile.hash_mb }} MB</span></div></div></article>
      </div>
      <article class="card admin-users"><div class="card-title"><div><h2>用户数据</h2><p class="help">活跃时间、对局行为与 AI 对手强度。提示和悔棋按已保存操作记录统计。</p></div><span class="count">{{ users.length }}</span></div><div class="admin-table-wrap"><table><thead><tr><th>账号</th><th>状态</th><th>最近活跃</th><th>活跃天数</th><th>对局数</th><th>提示</th><th>悔棋</th><th>对手强度（局数）</th><th>创建时间</th></tr></thead><tbody><template v-for="item in users" :key="item.id"><tr><td><strong>{{ item.display_name || '未设置昵称' }}</strong><small class="admin-cell-sub">{{ item.email || '开发身份' }} · {{ item.role === 'admin' ? '管理员' : '用户' }}</small></td><td><span class="admin-status" :class="`admin-status-${item.status}`">{{ item.status }}</span></td><td>{{ item.last_active_at ? date(item.last_active_at) : '暂无记录' }}</td><td>{{ item.active_days }} 天</td><td><button class="admin-game-count" :aria-expanded="expandedUserId === item.id" :aria-controls="`strengths-${item.id}`" :aria-label="`${item.display_name || '用户'}对局数 ${item.games_total}，查看强度分布`" @click="expandedUserId = expandedUserId === item.id ? null : item.id">{{ item.games_total }}</button><small class="admin-cell-sub">正式 {{ item.formal_games }} · AI {{ item.opponent_games }}</small></td><td>{{ item.hints_used }}</td><td>{{ item.undos_used }}</td><td><span class="admin-strength-summary">{{ strengthSummary(item) }}</span></td><td>{{ date(item.created_at) }}</td></tr><tr v-if="expandedUserId === item.id" :id="`strengths-${item.id}`" class="admin-strength-detail-row"><td colspan="9"><div class="admin-strength-detail"><strong>AI 对局强度分布</strong><span v-for="profile in overview.profiles" :key="profile.key">{{ profile.label }} <b>{{ strengthGames(item, profile.key) }}</b> 局</span></div></td></tr></template><tr v-if="!users.length"><td colspan="9" class="admin-empty">暂无用户</td></tr></tbody></table></div></article>
    </template>
    <p v-else-if="!busy" class="card admin-empty">没有读取到管理员数据。</p>
  </section>
</template>
