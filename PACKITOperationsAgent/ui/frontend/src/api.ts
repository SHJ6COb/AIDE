import type { Conversation, Message, QueryEvent } from './types'

const BASE = '/api'

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

export function listConversations(): Promise<Conversation[]> {
  return fetch(`${BASE}/conversations`).then((res) => asJson<Conversation[]>(res))
}

export function createConversation(): Promise<{ id: string }> {
  return fetch(`${BASE}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  }).then((res) => asJson<{ id: string }>(res))
}

export function getMessages(conversationId: string): Promise<Message[]> {
  return fetch(`${BASE}/conversations/${conversationId}/messages`).then((res) => asJson<Message[]>(res))
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const res = await fetch(`${BASE}/conversations/${conversationId}`, { method: 'DELETE' })
  if (!res.ok && res.status !== 204) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `Request failed (${res.status})`)
  }
}

export function reportIssue(conversationId: string, description?: string): Promise<{ mailto_url: string }> {
  return fetch(`${BASE}/issues`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, description }),
  }).then((res) => asJson<{ mailto_url: string }>(res))
}

// Native EventSource can't send a POST body, so the SSE response is parsed by hand
// from a fetch() ReadableStream instead (contract's /query endpoint is POST).
export async function* streamQuery(conversationId: string, query: string): AsyncGenerator<QueryEvent> {
  const res = await fetch(`${BASE}/conversations/${conversationId}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  })

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `Request failed (${res.status})`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

    let boundary: number
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const rawEvent = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)

      const dataLines = rawEvent
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())

      if (dataLines.length === 0) continue
      yield JSON.parse(dataLines.join('\n')) as QueryEvent
    }
  }
}
