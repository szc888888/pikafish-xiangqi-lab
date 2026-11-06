export interface Health { api_ready: boolean; engine_configured: boolean; engine_ready: boolean; engine_path: string; eval_file: string | null; error: string | null; llm_configured: boolean; llm_model: string | null }
export interface Score { type: 'cp' | 'mate'; value: number }
export interface EngineLine { rank: number; move: string; label: string; score: Score | null; depth: number | null; pv: string[] }
export interface CandidateRejection { move: string; code: string; reason: string }
export interface CandidateFilterSummary { requested: number; returned: number; rejected: CandidateRejection[] }
export interface Analysis { bestmove: string; score: Score | null; depth: number | null; nodes: number | null; nps: number | null; pv: string[]; raw_info: string[]; lines: EngineLine[]; filter_summary?: CandidateFilterSummary; terminal_status?: 'checkmate' | 'stalemate' | null }
export interface PlanAnalysis { best: { move: string; label: string; score: Score | null; depth: number | null; pv: string[] }; proposed: { move: string; label: string; score: Score | null; depth: number | null; pv: string[] }; score_difference_cp: number | null; explanation: { advantages: string[]; risks: string[]; engine_assessment: string; suggestion: string } | null; ai_available: boolean; ai_message: string | null; perspective?: 'red' | 'black'; comparison_status?: 'cp' | 'mate' | 'unavailable'; best_filter?: CandidateFilterSummary | null; proposed_filter?: CandidateFilterSummary | null }
export interface ReviewItem { ply: number; side: 'red' | 'black'; move: string; label: string; best_move: string | null; best_label: string | null; before_score: Score | null; after_score: Score | null; loss_cp: number | null; grade: 'good' | 'inaccuracy' | 'mistake' | 'blunder' | 'unknown'; pv: string[] }
export interface ReviewStop { ply: number; side: 'red' | 'black'; kind: 'perpetual_check' | 'perpetual_chase'; message: string }
export interface ReviewResponse { items: ReviewItem[]; final_score: Score | null; analyzed_plies: number; status?: 'complete' | 'stopped_rule_violation'; stop?: ReviewStop | null }
export interface OpeningLine { name: string; aliases: string[]; source: string; matched_plies: number; next_moves: { move: string; label: string }[] }
export interface CoachMessage { role: 'user' | 'assistant'; content: string }
export interface SetupImageResult { fen: string; red_to_move: boolean; piece_count: number; warnings: string[] }
export interface PersistedGameMove { ply: number; side: 'red' | 'black'; uci: string; notation_zh: string; before_fen: string; after_fen: string }
export interface PersistedEngineSettings { difficulty: 'companion' | 'beginner' | 'progress' | 'serious' | 'full' | 'custom'; allow_suboptimal: boolean; depth: number; movetime_ms: number; threads: number; hash_mb: number }
export interface PersistedGameEvent { id: string; type: 'undo' | 'hint'; createdAt: string; ply: number; positionMoves: string[]; positionFen: string; undoneMoves?: string[]; candidates?: { move: string; label: string; score: Score | null }[] }
export interface PersistedGame { id: string; name: string | null; initial_fen: string; current_fen: string; red_to_move: boolean; status: string; version: number; created_at: string; updated_at: string; engine_settings: PersistedEngineSettings; moves: PersistedGameMove[]; events: PersistedGameEvent[] }
export interface DataRequest { id: string; type: 'export' | 'delete'; status: string; expires_at: string | null; download_url: string | null }
export interface AuthMethods { email: boolean; oidc: boolean; email_verification_required: boolean }
export interface AuthUser { id: string; display_name: string | null; status: string; privacy_accepted?: boolean; policy_version?: string }
export interface PrivacyConfig { policy_version: string; effective_date: string; operator_name: string; contact_email: string; ready_for_publication: boolean }

export type ApiErrorCategory = 'network_error' | 'http_error' | 'invalid_response' | 'timeout' | 'aborted' | 'unknown'

export class ApiRequestError extends Error {
  readonly requestId: string
  readonly status: number | null
  readonly category: ApiErrorCategory
  readonly code: string | null

  constructor(message: string, metadata: { requestId: string; status?: number | null; category: ApiErrorCategory; code?: string | null }) {
    super(message)
    this.name = 'ApiRequestError'
    this.requestId = metadata.requestId
    this.status = metadata.status ?? null
    this.category = metadata.category
    this.code = metadata.code ?? null
  }
}

const REQUEST_ID_HEADER = 'X-Request-ID'
const SAFE_REQUEST_ID = /^[A-Za-z0-9._-]{1,128}$/
let debugLogging = false

export function setApiDebugLogging(enabled: boolean): void {
  debugLogging = enabled
}

function isSafeRequestId(value: string | null | undefined): value is string {
  return Boolean(value && SAFE_REQUEST_ID.test(value))
}

function createRequestId(): string {
  try {
    const randomUUID = globalThis.crypto?.randomUUID
    if (typeof randomUUID === 'function') {
      const value = randomUUID.call(globalThis.crypto)
      if (isSafeRequestId(value)) return value
    }
  } catch {
    // Fall through to the bounded local fallback.
  }
  try {
    const getRandomValues = globalThis.crypto?.getRandomValues
    if (typeof getRandomValues === 'function') {
      const values = new Uint32Array(2)
      getRandomValues.call(globalThis.crypto, values)
      const value = `web-${values[0].toString(36)}-${values[1].toString(36)}`
      if (isSafeRequestId(value)) return value
    }
  } catch {
    // Fall through to the bounded local fallback.
  }
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function responseRequestId(response: Response, fallback: string): string {
  const value = response.headers?.get(REQUEST_ID_HEADER)
  return isSafeRequestId(value) ? value : fallback
}

function operationPath(url: string): string {
  const match = url.match(/^\/api\/[A-Za-z0-9/_-]+/)
  return match?.[0] ?? '/api/request'
}

function durationMs(startedAt: number): number {
  return Math.max(0, Date.now() - startedAt)
}

function logRequestStart(operation: string, requestId: string): void {
  if (operation === '/api/health' && !debugLogging) return
  console.info({ event: 'api.request.start', operation, requestId, status: null, duration_ms: 0, category: 'started' })
}

function logRequestCompletion(operation: string, requestId: string, status: number, startedAt: number): void {
  if (operation === '/api/health' && !debugLogging) return
  console.info({ event: 'api.request.complete', operation, requestId, status, duration_ms: durationMs(startedAt), category: 'success' })
}

function logRequestFailure(operation: string, requestId: string, status: number | null, startedAt: number, category: ApiErrorCategory): void {
  console.error({ event: 'api.request.failure', operation, requestId, status, duration_ms: durationMs(startedAt), category })
}

function headersForRequest(options: RequestInit | undefined, requestId: string): Record<string, string> {
  const headers = new Headers(options?.headers)
  if (!headers.has('Content-Type') && !(typeof FormData !== 'undefined' && options?.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  headers.set(REQUEST_ID_HEADER, requestId)
  const result = Object.fromEntries(headers.entries())
  const contentType = result['content-type']
  delete result['content-type']
  if (contentType) result['Content-Type'] = contentType
  delete result['x-request-id']
  result[REQUEST_ID_HEADER] = requestId
  return result
}

function humanTransportError(error: unknown): string {
  if (error instanceof TypeError) return '无法连接后端，请确认 API 服务已启动（127.0.0.1:8000）'
  return error instanceof Error && error.message ? error.message : '请求失败'
}

function isAbortError(error: unknown): boolean {
  return typeof DOMException !== 'undefined' && error instanceof DOMException && error.name === 'AbortError'
}

function backendError(body: unknown, status: number): { message: string; code: string | null } {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail?: unknown }).detail
    if (detail && typeof detail === 'object' && 'message' in detail) {
      const structured = detail as { message?: unknown; code?: unknown }
      if (typeof structured.message === 'string') return { message: structured.message, code: typeof structured.code === 'string' ? structured.code : null }
    }
    if (typeof detail === 'string') return { message: detail, code: null }
  }
  return { message: `请求失败（HTTP ${status}）`, code: null }
}

// The vision API can be configured to wait up to 600 seconds. Keep a small
// transport buffer so the browser does not abort a request that the API can finish.
export const IMAGE_RECOGNITION_TIMEOUT_MS = 610_000

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const operation = operationPath(url)
  const clientRequestId = createRequestId()
  const startedAt = Date.now()
  logRequestStart(operation, clientRequestId)
  let response: Response
  try {
    // The API uses an HttpOnly session cookie. Be explicit so login works
    // consistently through the local dev proxy and same-origin deployments.
    response = await fetch(url, { ...options, cache: 'no-store', credentials: 'include', headers: headersForRequest(options, clientRequestId) })
  } catch (error) {
    logRequestFailure(operation, clientRequestId, null, startedAt, 'network_error')
    throw new ApiRequestError(humanTransportError(error), { requestId: clientRequestId, category: 'network_error' })
  }

  const requestId = responseRequestId(response, clientRequestId)
  let text: string
  try {
    text = await response.text()
  } catch {
    logRequestFailure(operation, requestId, response.status, startedAt, 'invalid_response')
    throw new ApiRequestError(`后端返回了无效响应（HTTP ${response.status}）`, { requestId, status: response.status, category: 'invalid_response' })
  }
  let body: unknown = null
  if (text.trim()) {
    try {
      body = JSON.parse(text)
    } catch {
      logRequestFailure(operation, requestId, response.status, startedAt, 'invalid_response')
      throw new ApiRequestError(`后端返回了无效响应（HTTP ${response.status}）`, { requestId, status: response.status, category: 'invalid_response' })
    }
  }
  if (!response.ok) {
    logRequestFailure(operation, requestId, response.status, startedAt, 'http_error')
    if (!text.trim() && response.status >= 500) {
      throw new ApiRequestError('无法连接后端，请确认 API 服务已启动（127.0.0.1:8000）', { requestId, status: response.status, category: 'http_error' })
    }
    const detail = backendError(body, response.status)
    throw new ApiRequestError(detail.message, { requestId, status: response.status, category: 'http_error', code: detail.code })
  }
  logRequestCompletion(operation, requestId, response.status, startedAt)
  return body as T
}
const post = (url: string, payload: unknown) => request<any>(url, { method: 'POST', body: JSON.stringify(payload) })
export const getHealth = () => request<Health>('/api/health')
export const resetEngine = () => request<Health>('/api/engine/reset', { method: 'POST' })
export const analyze = (payload: { fen: string; moves: string[]; depth: number; movetime_ms: number; multipv: number; threads: number; hash_mb: number }) => request<Analysis>('/api/engine/analyze', { method: 'POST', body: JSON.stringify(payload) })
export interface EngineMove extends Analysis { difficulty: string; difficulty_label: string; selected_rank: number; selection_seed: string }
export const engineMove = (payload: { fen: string; moves: string[]; difficulty: string; allow_suboptimal: boolean; game_id: string; ply: number; depth: number; movetime_ms: number; multipv: number; threads: number; hash_mb: number }) => request<EngineMove>('/api/engine/move', { method: 'POST', body: JSON.stringify(payload) })
export const validate = (payload: { fen: string; moves: string[] }) => post('/api/engine/validate', payload)
export const analyzePlan = (payload: { fen: string; moves: string[]; idea: string; move: string; depth: number; movetime_ms: number; threads: number; hash_mb: number }) => request<PlanAnalysis>('/api/engine/plan-analysis', { method: 'POST', body: JSON.stringify(payload) })
export const review = (payload: { fen: string; moves: string[]; depth?: number; movetime_ms?: number; threads?: number; hash_mb?: number }) => request<ReviewResponse>('/api/engine/review', { method: 'POST', body: JSON.stringify(payload) })
export const persistReview = (gameId: string, payload: { fen: string; moves: string[]; depth?: number; movetime_ms?: number; threads?: number; hash_mb?: number }) => request<ReviewResponse & { review_id: string; game_id: string; snapshot_hash: string }>(`/api/games/${encodeURIComponent(gameId)}/reviews`, { method: 'POST', body: JSON.stringify(payload) })
export const getOpenings = (payload: { fen: string; moves: string[] }) => request<{ matches: OpeningLine[] }>('/api/openings', { method: 'POST', body: JSON.stringify(payload) })
export const coachChat = (payload: { question: string; fen: string; moves: string[]; messages: CoachMessage[]; context: string }) => request<{ answer: string; ai_available: boolean; ai_message: string | null }>('/api/coach/chat', { method: 'POST', body: JSON.stringify(payload) })
export const getMe = () => request<AuthUser>('/api/me')
export const getPrivacyConfig = () => request<PrivacyConfig>('/api/privacy/config')
export const acceptPrivacy = (policy_version: string) => request<{ accepted: boolean }>('/api/me/privacy-consent', { method: 'POST', body: JSON.stringify({ accepted: true, policy_version }) })
export const getAuthMethods = () => request<AuthMethods>('/api/auth/methods')
export const registerEmail = (payload: { email: string; password: string; display_name?: string; accept_privacy: true; policy_version: string }) => request<{ user: AuthUser; email_verified: boolean; verification_required: boolean }>('/auth/email/register', { method: 'POST', body: JSON.stringify(payload) })
export const loginEmail = (payload: { email: string; password: string }) => request<{ user: AuthUser }>('/auth/email/login', { method: 'POST', body: JSON.stringify(payload) })
export const requestEmailVerification = (email: string) => request<{ ok: boolean }>('/auth/email/verification/request', { method: 'POST', body: JSON.stringify({ email }) })
export const verifyEmail = (token: string) => request<{ ok: boolean }>('/auth/email/verify', { method: 'POST', body: JSON.stringify({ token }) })
export const forgotPassword = (email: string) => request<{ ok: boolean }>('/auth/email/password/forgot', { method: 'POST', body: JSON.stringify({ email }) })
export const resetPassword = (token: string, password: string) => request<{ ok: boolean }>('/auth/email/password/reset', { method: 'POST', body: JSON.stringify({ token, password }) })
export const beginOidcLogin = () => { window.location.href = '/auth/oidc/start' }
export const logout = () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' })
export const getGames = () => request<PersistedGame[]>('/api/games')
export const createGame = (payload: { name?: string; initial_fen: string; engine_settings?: PersistedEngineSettings; events?: PersistedGameEvent[] }) => request<PersistedGame>('/api/games', { method: 'POST', body: JSON.stringify(payload) })
export const importGame = (payload: { legacy_id: string; name?: string; initial_fen: string; moves: string[]; engine_settings?: PersistedEngineSettings; events?: PersistedGameEvent[] }) => request<PersistedGame>('/api/games/import', { method: 'POST', body: JSON.stringify(payload) })
export const appendGameMove = (id: string, payload: { expected_version: number; uci: string; engine_settings?: PersistedEngineSettings }) => request<PersistedGame>(`/api/games/${encodeURIComponent(id)}/moves`, { method: 'POST', body: JSON.stringify(payload) })
export const deleteGame = (id: string) => request<void>(`/api/games/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const updateGameEvents = (id: string, payload: { expected_version: number; events: PersistedGameEvent[] }) => request<PersistedGame>(`/api/games/${encodeURIComponent(id)}/events`, { method: 'PATCH', body: JSON.stringify(payload) })
export const requestExport = () => request<DataRequest>('/api/me/exports', { method: 'POST' })
export const requestDeletion = () => request<DataRequest>('/api/me/deletion', { method: 'POST' })
export const cancelDeletion = () => request<DataRequest>('/api/me/deletion/cancel', { method: 'POST' })
export async function recognizeSetupImage(file: File, signal?: AbortSignal): Promise<SetupImageResult> {
  const form = new FormData()
  form.append('file', file)
  const controller = new AbortController()
  const operation = '/api/setup/image'
  const clientRequestId = createRequestId()
  const startedAt = Date.now()
  logRequestStart(operation, clientRequestId)
  let timedOut = false
  let requestId = clientRequestId
  let requestStatus: number | null = null
  const timer = globalThis.setTimeout(() => { timedOut = true; controller.abort() }, IMAGE_RECOGNITION_TIMEOUT_MS)
  const abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) controller.abort()
  try {
    if (signal?.aborted) {
      logRequestFailure(operation, requestId, null, startedAt, 'aborted')
      throw new ApiRequestError('已取消图片识别', { requestId, status: null, category: 'aborted' })
    }
    const response = await fetch('/api/setup/image', {
      method: 'POST',
      body: form,
      signal: controller.signal,
      headers: { [REQUEST_ID_HEADER]: clientRequestId },
    })
    requestId = responseRequestId(response, clientRequestId)
    requestStatus = response.status
    let body: unknown
    try {
      body = await response.json()
    } catch (error) {
      if (isAbortError(error)) throw error
      logRequestFailure(operation, requestId, response.status, startedAt, 'invalid_response')
      throw new ApiRequestError(`后端返回了无效响应（HTTP ${response.status}）`, { requestId, status: response.status, category: 'invalid_response' })
    }
    if (!response.ok) {
      logRequestFailure(operation, requestId, response.status, startedAt, 'http_error')
      const detail = backendError(body, response.status)
      throw new ApiRequestError(detail.message === `请求失败（HTTP ${response.status}）` ? '棋盘图片识别失败' : detail.message, { requestId, status: response.status, category: 'http_error', code: detail.code })
    }
    logRequestCompletion(operation, requestId, response.status, startedAt)
    return body as SetupImageResult
  } catch (error) {
    if (isAbortError(error)) {
      const category = timedOut ? 'timeout' : 'aborted'
      logRequestFailure(operation, requestId, requestStatus, startedAt, category)
      throw new ApiRequestError(timedOut ? '图片识别超时，请换一张清晰的棋盘图片后重试' : '已取消图片识别', { requestId, status: requestStatus, category })
    }
    if (error instanceof ApiRequestError) throw error
    logRequestFailure(operation, requestId, requestStatus, startedAt, error instanceof TypeError ? 'network_error' : 'unknown')
    if (error instanceof TypeError) {
      throw new ApiRequestError('无法连接后端，请确认 API 服务已启动（127.0.0.1:8000）', { requestId, status: requestStatus, category: 'network_error' })
    }
    throw error
  } finally {
    globalThis.clearTimeout(timer)
    signal?.removeEventListener('abort', abort)
  }
}
