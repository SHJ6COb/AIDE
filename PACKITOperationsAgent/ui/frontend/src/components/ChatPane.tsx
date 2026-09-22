import { useEffect, useRef } from 'react'
import type { Message } from '../types'
import MessageBubble from './MessageBubble'
import StepIndicator from './StepIndicator'
import ErrorBanner from './ErrorBanner'
import ChatInput from './ChatInput'

export default function ChatPane({
  hasConversation,
  messages,
  currentStep,
  streamError,
  onDismissStreamError,
  sending,
  onSend,
  onReportIssue,
  issueError,
}: {
  hasConversation: boolean
  messages: Message[]
  currentStep: string | null
  streamError: string | null
  onDismissStreamError: () => void
  sending: boolean
  onSend: (text: string) => void
  onReportIssue: () => void
  issueError: string | null
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, currentStep, streamError])

  return (
    <main className="flex h-full flex-1 flex-col bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 px-6 py-3">
        <h1 className="text-sm font-semibold text-slate-700">PackIT Operations Agent</h1>
        <button
          type="button"
          onClick={onReportIssue}
          disabled={!hasConversation}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Report Issue
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {!hasConversation ? (
          <div className="flex h-full items-center justify-center text-center text-slate-400">
            <p>Select a conversation or start a new one to ask about a packaging specification.</p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {messages.length === 0 && !currentStep && (
              <div className="flex h-full items-center justify-center py-16 text-center text-slate-400">
                <p>Ask about the replication status of a packaging specification to get started.</p>
              </div>
            )}
            {messages.map((m, i) => (
              <MessageBubble key={i} message={m} />
            ))}
            {currentStep && <StepIndicator message={currentStep} />}
            {streamError && <ErrorBanner message={streamError} onDismiss={onDismissStreamError} />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {hasConversation && (
        <div className="border-t border-slate-200 px-6 py-4">
          <div className="mx-auto max-w-3xl">
            {issueError && (
              <div className="mb-2">
                <ErrorBanner message={issueError} />
              </div>
            )}
            <ChatInput disabled={sending} onSend={onSend} />
          </div>
        </div>
      )}
    </main>
  )
}
