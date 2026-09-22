import type { Conversation } from '../types'
import { relativeTime } from '../lib/time'

export default function Sidebar({
  conversations,
  activeId,
  disabled,
  onSelect,
  onNew,
  onDelete,
}: {
  conversations: Conversation[]
  activeId: string | null
  disabled: boolean
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}) {
  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-slate-200 bg-slate-50">
      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          disabled={disabled}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="text-lg leading-none">+</span>
          New conversation
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 && (
          <p className="px-2 py-4 text-center text-sm text-slate-400">No conversations yet</p>
        )}
        <ul className="space-y-0.5">
          {conversations.map((c) => (
            <li key={c.id} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                disabled={disabled}
                className={`w-full rounded-lg px-3 py-2.5 pr-8 text-left transition-colors disabled:cursor-not-allowed ${
                  c.id === activeId ? 'bg-sky-100 text-sky-900' : 'text-slate-700 hover:bg-slate-100'
                }`}
              >
                <p className="truncate text-sm font-medium">{c.title || 'New conversation'}</p>
                <p className="text-xs text-slate-400">{relativeTime(c.updated_at)}</p>
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onDelete(c.id)
                }}
                disabled={disabled}
                aria-label="Delete conversation"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-slate-400 opacity-0 transition-opacity hover:bg-slate-200 hover:text-red-600 group-hover:opacity-100 disabled:cursor-not-allowed"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  )
}
