export type ClientPlatform = 'pc' | 'mini_program' | 'mobile_web' | 'unknown'

export function detectClientPlatform(): ClientPlatform {
  const agent = typeof navigator === 'undefined' ? '' : navigator.userAgent.toLowerCase()
  const environment = typeof window === 'undefined' ? undefined
    : (window as Window & { __wxjs_environment?: string }).__wxjs_environment
  if (environment === 'miniprogram' || /\bminiprogram\b/.test(agent)) return 'mini_program'
  if (/android|iphone|ipad|ipod|mobile/.test(agent)) return 'mobile_web'
  if (/windows nt|macintosh|x11|cros|linux x86_64/.test(agent)) return 'pc'
  return 'unknown'
}

export const clientPlatformLabels: Record<ClientPlatform, string> = {
  pc: 'PC 端', mini_program: '小程序端', mobile_web: '手机网页', unknown: '暂无记录',
}
