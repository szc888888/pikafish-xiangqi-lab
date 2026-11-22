import { createApp, nextTick, type Component } from 'vue'

export function renderComponent(component: Component, props: Record<string, any>) {
  const root = document.createElement('div')
  document.body.append(root)
  const app = createApp(component, props)
  app.mount(root)
  function all(tag: string) { return Array.from(root.querySelectorAll(tag)) }
  function button(label: string): HTMLButtonElement {
    const found = Array.from(root.querySelectorAll('button')).find(item => item.textContent?.trim() === label)
    if (!found) throw new Error(`Button missing: ${label}`)
    return found
  }
  return { root, all, button, text: () => root.textContent ?? '', unmount: () => { app.unmount(); root.remove() }, async click(label: string) { button(label).click(); await nextTick() } }
}
