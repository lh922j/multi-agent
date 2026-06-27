"use client";
import { useState, useCallback, useRef } from "react";
import { Message, Session, SSEEvent, MapPoint } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

export function useChat() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;

  const newSession = useCallback(() => {
    const id = makeId();
    const session: Session = {
      id,
      title: "새 대화",
      updatedAt: new Date(),
      messages: [],
    };
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(id);
    return id;
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      let sessionId = activeSessionId;
      if (!sessionId) sessionId = newSession();

      const userMsg: Message = {
        id: makeId(),
        role: "user",
        content: text,
      };

      const assistantMsg: Message = {
        id: makeId(),
        role: "assistant",
        content: "",
        streaming: true,
      };

      setSessions((prev) =>
        prev.map((s) =>
          s.id === sessionId
            ? {
                ...s,
                title: s.messages.length === 0 ? text.slice(0, 24) : s.title,
                updatedAt: new Date(),
                messages: [...s.messages, userMsg, assistantMsg],
              }
            : s
        )
      );

      setStreaming(true);
      abortRef.current = new AbortController();

      try {
        const resp = await fetch(`${API_BASE}/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, thread_id: sessionId }),
          signal: abortRef.current.signal,
        });

        const reader = resp.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let fullText = "";
        let mapPoints: MapPoint[] = [];
        let agentName = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;
            try {
              const ev: SSEEvent = JSON.parse(raw);
              if (ev.type === "token" && ev.token) {
                fullText += ev.token;
                setSessions((prev) =>
                  prev.map((s) =>
                    s.id === sessionId
                      ? {
                          ...s,
                          messages: s.messages.map((m) =>
                            m.id === assistantMsg.id
                              ? { ...m, content: fullText }
                              : m
                          ),
                        }
                      : s
                  )
                );
              } else if (ev.type === "agent" && ev.agent) {
                agentName = ev.agent;
              } else if (ev.type === "done") {
                if (ev.answer) fullText = ev.answer;
                if (ev.map_points) mapPoints = ev.map_points;
              }
            } catch {}
          }
        }

        setSessions((prev) =>
          prev.map((s) =>
            s.id === sessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === assistantMsg.id
                      ? {
                          ...m,
                          content: fullText,
                          mapPoints,
                          agentName,
                          streaming: false,
                        }
                      : m
                  ),
                }
              : s
          )
        );
      } catch (err: unknown) {
        if ((err as Error).name === "AbortError") return;
        setSessions((prev) =>
          prev.map((s) =>
            s.id === sessionId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === assistantMsg.id
                      ? { ...m, content: "오류가 발생했습니다. 다시 시도해주세요.", streaming: false }
                      : m
                  ),
                }
              : s
          )
        );
      } finally {
        setStreaming(false);
      }
    },
    [activeSessionId, newSession]
  );

  return { sessions, activeSession, activeSessionId, setActiveSessionId, newSession, sendMessage, streaming };
}
