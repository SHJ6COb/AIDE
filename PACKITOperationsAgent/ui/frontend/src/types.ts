export interface Conversation {
  id: string
  title: string
  updated_at: string
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export type QueryEvent =
  | { type: 'step'; message: string }
  | { type: 'answer'; content: string }
  | { type: 'error'; message: string }
