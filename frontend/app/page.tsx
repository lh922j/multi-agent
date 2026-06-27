"use client";
import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar";
import ChatPanel from "@/components/ChatPanel";
import MapPanel from "@/components/MapPanel";
import { useChat } from "@/hooks/useChat";

export default function Home() {
  const { sessions, activeSession, activeSessionId, setActiveSessionId, newSession, sendMessage, streaming } = useChat();
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    if (sessions.length === 0) newSession();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex h-screen overflow-hidden">
      {sidebarOpen && (
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={setActiveSessionId}
          onNewSession={newSession}
          onCollapse={() => setSidebarOpen(false)}
        />
      )}

      {!sidebarOpen && (
        <button
          onClick={() => setSidebarOpen(true)}
          title="사이드바 열기"
          className="shrink-0 w-8 flex items-start pt-4 justify-center"
          style={{ color: "#9CA3AF", background: "#111827" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      )}

      <ChatPanel
        messages={activeSession?.messages ?? []}
        streaming={streaming}
        onSend={sendMessage}
      />

      <MapPanel messages={activeSession?.messages ?? []} />
    </div>
  );
}
