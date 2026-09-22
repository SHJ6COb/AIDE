import { useCallback, useEffect, useState } from 'react'
import type { Conversation, Message } from './types'
import * as api from './api'
import Sidebar from './components/Sidebar'
import ChatPane from './components/ChatPane'
import ErrorBanner from './components/ErrorBanner'

// Caught live via QA testing: a real page reload lost the active conversation
// entirely -- the sidebar still listed it (server-side persistence was fine),
// but nothing was auto-selected, resetting to the empty "select a
// conversation" state every time. Persisting the id client-side and
// restoring it on mount (if it still exists) closes that gap.
const ACTIVE_ID_STORAGE_KEY = 'packit-agent-active-conversation-id'

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])

  const [currentStep, setCurrentStep] = useState<string | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)

  const [issueError, setIssueError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const refreshConversations = useCallback(async () => {
    try {
      const list = await api.listConversations()
      setConversations(list)
      setLoadError(null)
      return list
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load conversations')
      return []
    }
  }, [])

  useEffect(() => {
    refreshConversations().then((list) => {
      const savedId = localStorage.getItem(ACTIVE_ID_STORAGE_KEY)
      if (savedId && list.some((c) => c.id === savedId)) {
        selectConversation(savedId)
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshConversations])

  async function selectConversation(id: string) {
    setActiveId(id)
    localStorage.setItem(ACTIVE_ID_STORAGE_KEY, id)
    setCurrentStep(null)
    setStreamError(null)
    setIssueError(null)
    try {
      const msgs = await api.getMessages(id)
      setMessages(msgs)
    } catch (err) {
      setStreamError(err instanceof Error ? err.message : 'Failed to load messages')
    }
  }

  async function newConversation() {
    try {
      const { id } = await api.createConversation()
      await refreshConversations()
      setActiveId(id)
      localStorage.setItem(ACTIVE_ID_STORAGE_KEY, id)
      setMessages([])
      setCurrentStep(null)
      setStreamError(null)
      setIssueError(null)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to create conversation')
    }
  }

  async function deleteConv(id: string) {
    const target = conversations.find((c) => c.id === id)
    const label = target?.title || 'this conversation'
    if (!window.confirm(`Delete "${label}"? This can't be undone.`)) {
      return
    }
    try {
      await api.deleteConversation(id)
      await refreshConversations()
      if (id === activeId) {
        setActiveId(null)
        localStorage.removeItem(ACTIVE_ID_STORAGE_KEY)
        setMessages([])
      }
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to delete conversation')
    }
  }

  async function sendQuery(text: string) {
    if (!activeId) return

    setMessages((prev) => [...prev, { role: 'user', content: text, created_at: new Date().toISOString() }])
    setSending(true)
    setStreamError(null)
    setCurrentStep('Thinking...')

    let terminal = false
    try {
      for await (const event of api.streamQuery(activeId, text)) {
        if (event.type === 'step') {
          setCurrentStep(event.message)
        } else if (event.type === 'answer') {
          terminal = true
          setCurrentStep(null)
        } else if (event.type === 'error') {
          terminal = true
          setCurrentStep(null)
          setStreamError(event.message)
        }
      }
      if (!terminal) {
        setStreamError('The connection ended unexpectedly before a response arrived.')
      }
    } catch (err) {
      setCurrentStep(null)
      setStreamError(err instanceof Error ? err.message : 'Something went wrong while contacting the agent.')
    } finally {
      setSending(false)
      // Contract: trust the persisted message list, not accumulated SSE state.
      try {
        const msgs = await api.getMessages(activeId)
        setMessages(msgs)
      } catch {
        // keep the optimistic/local messages if the refetch itself fails
      }
      refreshConversations()
    }
  }

  async function handleReportIssue() {
    if (!activeId) return
    setIssueError(null)
    try {
      const { mailto_url } = await api.reportIssue(activeId)
      window.location.href = mailto_url
    } catch (err) {
      setIssueError(err instanceof Error ? err.message : 'Failed to report issue')
    }
  }

  return (
    <div className="flex h-screen flex-col">
      {loadError && (
        <div className="px-4 pt-3">
          <ErrorBanner message={loadError} onDismiss={() => setLoadError(null)} />
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          disabled={sending}
          onSelect={selectConversation}
          onNew={newConversation}
          onDelete={deleteConv}
        />
        <ChatPane
          hasConversation={activeId !== null}
          messages={messages}
          currentStep={currentStep}
          streamError={streamError}
          onDismissStreamError={() => setStreamError(null)}
          sending={sending}
          onSend={sendQuery}
          onReportIssue={handleReportIssue}
          issueError={issueError}
        />
      </div>
    </div>
  )
}
