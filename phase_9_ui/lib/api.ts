const BASE = "/api";

export interface Message {
  role: "user" | "assistant";
  content: string;
  ts: string;
  citation_url?: string;
  last_updated?: string;
  used_chunk_ids?: string[];
}

export interface Thread {
  thread_id: string;
  created_at: string;
  messages: Message[];
  metadata: { last_scheme?: string };
}

export interface ThreadSummary {
  thread_id: string;
  created_at: string;
  message_count: number;
  preview?: string;
}

export interface ChatResponse {
  thread_id: string;
  answer: string;
  citation_url: string;
  last_updated: string;
  confidence: number;
  used_chunk_ids: string[];
  sentinel?: string;
  refusal?: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  createThread: () =>
    request<Thread>("/threads", { method: "POST" }),

  listThreads: () =>
    request<ThreadSummary[]>("/threads"),

  getThread: (threadId: string) =>
    request<Thread>(`/threads/${threadId}`),

  deleteThread: (threadId: string) =>
    request<void>(`/threads/${threadId}`, { method: "DELETE" }),

  chat: (threadId: string, query: string) =>
    request<ChatResponse>(`/threads/${threadId}/chat`, {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
};
