export function handleCoachInputKeydown(event: KeyboardEvent, submit: () => void) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  submit()
}
