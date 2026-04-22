"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ThreadSummary } from "@/lib/api";
import { ThreadSidebar } from "@/components/ThreadSidebar";
import { ChatWindow } from "@/components/ChatWindow";

export default function Home() {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const loadThreads = useCallback(async () => {
    try {
      const list = await api.listThreads();
      setThreads(list);
    } catch {
      // API may not be running in dev
    }
  }, []);

  useEffect(() => { loadThreads(); }, [loadThreads, refreshKey]);

  const handleNewChat = async () => {
    try {
      const thread = await api.createThread();
      setActiveThreadId(thread.thread_id);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      console.error("Failed to create thread", e);
    }
  };

  const handleDeleteThread = async (threadId: string) => {
    try {
      await api.deleteThread(threadId);
      if (activeThreadId === threadId) setActiveThreadId(null);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      console.error("Failed to delete thread", e);
    }
  };

  return (
    <div className="flex h-full">
      <ThreadSidebar
        threads={threads}
        activeThreadId={activeThreadId}
        onSelectThread={setActiveThreadId}
        onNewChat={handleNewChat}
        onDeleteThread={handleDeleteThread}
      />
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <ChatWindow
          threadId={activeThreadId}
          onMessageSent={() => setRefreshKey((k) => k + 1)}
        />
      </main>
    </div>
  );
}
