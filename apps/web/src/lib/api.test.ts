import { describe, expect, it, vi } from 'vitest'
import { IMAGE_RECOGNITION_TIMEOUT_MS, analyze, coachChat, engineMove, getHealth, recognizeSetupImage, setApiDebugLogging } from './api'

describe('image recognition request', () => {
  it('allows the backend vision request to finish before the browser aborts it', () => {
    expect(IMAGE_RECOGNITION_TIMEOUT_MS).toBe(610_000)
  })
})

describe('API transport errors', () => {
  it('sends the deterministic play profile payload to the dedicated move endpoint', async () => {
    const payload = { fen: 'fen', moves: ['a3a4'], difficulty: 'custom', game_id: 'game-1', ply: 1, depth: 3, movetime_ms: 500, multipv: 1, threads: 2, hash_mb: 128 }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      text: vi.fn().mockResolvedValue(JSON.stringify({ bestmove: 'a6a5', lines: [], difficulty: 'custom', difficulty_label: '自定义', selected_rank: 1, selection_seed: 'game-1:1' })),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await engineMove(payload)

    expect(fetchMock).toHaveBeenCalledWith('/api/engine/move', expect.objectContaining({
      method: 'POST', body: JSON.stringify(payload),
    }))
    expect(result.selection_seed).toBe('game-1:1')
  })

  it('reports when the backend cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(coachChat({ question: '你好', fen: 'fen', moves: [], messages: [], context: '' }))
      .rejects.toThrow('无法连接后端，请确认 API 服务已启动')
  })

  it('reports an invalid non-JSON backend response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      text: vi.fn().mockResolvedValue('Bad Gateway'),
    }))

    await expect(coachChat({ question: '你好', fen: 'fen', moves: [], messages: [], context: '' }))
      .rejects.toThrow('后端返回了无效响应（HTTP 502）')
  })

  it('reports an unavailable backend when the dev proxy returns an empty 5xx response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: vi.fn().mockResolvedValue(''),
    }))

    await expect(coachChat({ question: '你好', fen: 'fen', moves: [], messages: [], context: '' }))
      .rejects.toThrow('无法连接后端，请确认 API 服务已启动')
  })

  it('preserves structured backend error codes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      headers: new Headers({ 'X-Request-ID': 'rule-request-id' }),
      text: vi.fn().mockResolvedValue(JSON.stringify({ detail: { code: 'rule_violation', message: '长将' } })),
    }))

    await expect(analyze({ fen: 'fen', moves: [], depth: 8, movetime_ms: 0, multipv: 1, threads: 1, hash_mb: 16 }))
      .rejects.toMatchObject({ code: 'rule_violation', message: '长将' })
  })
})

describe('API request diagnostics', () => {
  it('sends a generated request ID and prefers the server correlation ID', async () => {
    const randomUUID = vi.fn(() => 'client-request-id')
    vi.stubGlobal('crypto', { randomUUID })
    const consoleInfo = vi.spyOn(console, 'info').mockImplementation(() => undefined)
    setApiDebugLogging(true)
    const responseHeaders = new Headers({ 'X-Request-ID': 'server-request-id' })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: responseHeaders,
      text: vi.fn().mockResolvedValue(JSON.stringify({ api_ready: true })),
    })
    vi.stubGlobal('fetch', fetchMock)

    await getHealth()

    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.objectContaining({
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'X-Request-ID': 'client-request-id',
      }),
    }))
    expect(randomUUID).toHaveBeenCalledOnce()
    expect(consoleInfo.mock.calls.some(([event]) => typeof event === 'object' && event !== null && 'requestId' in event && event.requestId === 'server-request-id')).toBe(true)
    expect(consoleInfo.mock.calls[0][0]).toMatchObject({ operation: '/api/health', requestId: 'client-request-id', status: null, duration_ms: 0, category: 'started' })
    setApiDebugLogging(false)
  })

  it('logs failure metadata without serializing request or response content', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal('crypto', { randomUUID: () => 'client-request-id' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      headers: new Headers({ 'X-Request-ID': 'server-request-id' }),
      text: vi.fn().mockResolvedValue(JSON.stringify({ detail: 'safe user-facing detail' })),
    }))
    const payload = { question: 'PROMPT_SENTINEL', fen: 'FEN_SENTINEL', moves: ['MOVE_SENTINEL'], messages: [], context: '' }

    await expect(coachChat(payload)).rejects.toMatchObject({
      requestId: 'server-request-id',
      status: 422,
      category: 'http_error',
      message: 'safe user-facing detail',
    })

    expect(consoleError).toHaveBeenCalledOnce()
    const logged = JSON.stringify(consoleError.mock.calls[0])
    expect(logged).toContain('/api/coach/chat')
    expect(logged).toContain('server-request-id')
    expect(logged).toContain('http_error')
    expect(logged).not.toContain('PROMPT_SENTINEL')
    expect(logged).not.toContain('FEN_SENTINEL')
    expect(logged).not.toContain('MOVE_SENTINEL')
    expect(logged).not.toContain('safe user-facing detail')
  })

  it('keeps successful health polling quiet', async () => {
    const consoleLog = vi.spyOn(console, 'log').mockImplementation(() => undefined)
    const consoleInfo = vi.spyOn(console, 'info').mockImplementation(() => undefined)
    const consoleDebug = vi.spyOn(console, 'debug').mockImplementation(() => undefined)
    vi.stubGlobal('crypto', { randomUUID: () => 'health-request-id' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'X-Request-ID': 'health-server-id' }),
      text: vi.fn().mockResolvedValue('{}'),
    }))

    await getHealth()

    expect(consoleLog).not.toHaveBeenCalled()
    expect(consoleInfo).not.toHaveBeenCalled()
    expect(consoleDebug).not.toHaveBeenCalled()
  })

  it('sends a request ID for multipart image recognition', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'image-request-id' })
    vi.stubGlobal('window', { setTimeout, clearTimeout })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'X-Request-ID': 'image-server-id' }),
      json: vi.fn().mockResolvedValue({ fen: 'safe', red_to_move: true, piece_count: 0, warnings: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await recognizeSetupImage(new File(['image'], 'board.png', { type: 'image/png' }))

    expect(fetchMock).toHaveBeenCalledWith('/api/setup/image', expect.objectContaining({
      headers: expect.objectContaining({ 'X-Request-ID': 'image-request-id' }),
    }))
  })

  it('classifies an already-aborted image request as caller cancellation', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal('crypto', { randomUUID: () => 'already-aborted-id' })
    const caller = new AbortController()
    caller.abort()
    const fetchMock = vi.fn().mockImplementation((_url, options: RequestInit) => {
      if (options.signal?.aborted) return Promise.reject(new DOMException('aborted', 'AbortError'))
      return new Promise(() => undefined)
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(recognizeSetupImage(new File(['image'], 'board.png', { type: 'image/png' }), caller.signal))
      .rejects.toMatchObject({ category: 'aborted', requestId: 'already-aborted-id' })
    expect(fetchMock).not.toHaveBeenCalled()
    expect(consoleError).toHaveBeenCalledOnce()
    expect(consoleError.mock.calls[0][0]).toMatchObject({ operation: '/api/setup/image', requestId: 'already-aborted-id', category: 'aborted' })
  })

  it('classifies timeout while parsing an image response and retains the server ID', async () => {
    vi.useFakeTimers()
    try {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
      vi.stubGlobal('crypto', { randomUUID: () => 'timeout-client-id' })
      let requestSignal: AbortSignal | null | undefined
      const fetchMock = vi.fn().mockImplementation((_url, options: RequestInit) => {
        requestSignal = options.signal
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ 'X-Request-ID': 'timeout-server-id' }),
          json: vi.fn().mockImplementation(() => new Promise((_resolve, reject) => {
            requestSignal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
          })),
        })
      })
      vi.stubGlobal('fetch', fetchMock)

      const pending = recognizeSetupImage(new File(['image'], 'board.png', { type: 'image/png' }))
      const rejection = expect(pending).rejects.toMatchObject({ category: 'timeout', requestId: 'timeout-server-id' })
      await vi.advanceTimersByTimeAsync(IMAGE_RECOGNITION_TIMEOUT_MS)
      await rejection
      expect(consoleError).toHaveBeenCalledOnce()
      expect(consoleError.mock.calls[0][0]).toMatchObject({ operation: '/api/setup/image', requestId: 'timeout-server-id', status: 200, category: 'timeout' })
      expect(typeof consoleError.mock.calls[0][0].duration_ms).toBe('number')
    } finally {
      vi.useRealTimers()
    }
  })

  it('classifies caller cancellation while parsing an image response without duplicate failures', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal('crypto', { randomUUID: () => 'caller-client-id' })
    const caller = new AbortController()
    let requestSignal: AbortSignal | null | undefined
    const fetchMock = vi.fn().mockImplementation((_url, options: RequestInit) => {
      requestSignal = options.signal
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers({ 'X-Request-ID': 'caller-server-id' }),
        json: vi.fn().mockImplementation(() => new Promise((_resolve, reject) => {
          if (requestSignal?.aborted) {
            reject(new DOMException('aborted', 'AbortError'))
            return
          }
          requestSignal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true })
        })),
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const pending = recognizeSetupImage(new File(['image'], 'board.png', { type: 'image/png' }), caller.signal)
    await Promise.resolve()
    caller.abort()
    await expect(pending).rejects.toMatchObject({ category: 'aborted', requestId: 'caller-server-id' })
    expect(consoleError).toHaveBeenCalledOnce()
    expect(consoleError.mock.calls[0][0]).toMatchObject({ operation: '/api/setup/image', requestId: 'caller-server-id', status: 200, category: 'aborted' })
  })

  it('keeps malformed image JSON classified as an invalid response', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.stubGlobal('crypto', { randomUUID: () => 'invalid-json-client-id' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'X-Request-ID': 'invalid-json-server-id' }),
      json: vi.fn().mockRejectedValue(new SyntaxError('invalid json')),
    }))

    await expect(recognizeSetupImage(new File(['image'], 'board.png', { type: 'image/png' })))
      .rejects.toMatchObject({ category: 'invalid_response', requestId: 'invalid-json-server-id' })
    expect(consoleError).toHaveBeenCalledOnce()
    expect(consoleError.mock.calls[0][0]).toMatchObject({ operation: '/api/setup/image', requestId: 'invalid-json-server-id', status: 200, category: 'invalid_response' })
  })
})
