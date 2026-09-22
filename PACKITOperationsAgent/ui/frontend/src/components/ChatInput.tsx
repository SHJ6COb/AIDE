import { useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'

export default function ChatInput({
  disabled,
  onSend,
}: {
  disabled: boolean
  onSend: (text: string) => void
}) {
  const [value, setValue] = useState('')

  function submit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit(e)
    }
  }

  return (
    <form onSubmit={submit} className="flex items-end gap-2">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled}
        rows={1}
        placeholder="Ask about a packaging specification's replication status..."
        className="max-h-40 min-h-[44px] flex-1 resize-none rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-[15px] text-slate-800 placeholder:text-slate-400 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500 disabled:bg-slate-50"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="h-11 shrink-0 rounded-xl bg-sky-600 px-5 text-sm font-medium text-white transition-colors hover:bg-sky-700 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        Send
      </button>
    </form>
  )
}
