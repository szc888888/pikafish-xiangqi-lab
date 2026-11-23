import { afterEach, describe, expect, it, vi } from 'vitest'
import { detectClientPlatform } from './clientPlatform'

afterEach(() => { vi.unstubAllGlobals() })

describe('client platform', () => {
  it.each([
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'pc'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 'pc'],
    ['Mozilla/5.0 (X11; Linux x86_64)', 'pc'],
    ['iPhone MicroMessenger miniProgram', 'mini_program'],
    ['iPhone MicroMessenger', 'mobile_web'],
    ['Android', 'mobile_web'],
    ['', 'unknown'],
  ])('classifies %s as %s', (userAgent, expected) => {
    vi.stubGlobal('navigator', { userAgent })
    expect(detectClientPlatform()).toBe(expected)
  })

  it('recognizes the mini program environment before the generic mobile user agent', () => {
    vi.stubGlobal('navigator', { userAgent: 'iPhone MicroMessenger' })
    vi.stubGlobal('window', { __wxjs_environment: 'miniprogram' })
    expect(detectClientPlatform()).toBe('mini_program')
    vi.stubGlobal('window', {})
    expect(detectClientPlatform()).toBe('mobile_web')
  })
})
