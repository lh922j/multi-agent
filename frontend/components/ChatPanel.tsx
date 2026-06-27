"use client";
import { useEffect, useRef, useState } from "react";
import { Message } from "@/types";

interface Props {
  messages: Message[];
  streaming: boolean;
  onSend: (text: string) => void;
}

const QUICK_QUERIES = [
  "강남구 84㎡ 매매 시세",
  "홍대 근처 카페 상권",
  "잠실동 재건축 현황",
  "마포구 전세 시세 비교",
];

export default function ChatPanel({ messages, streaming, onSend }: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleSend() {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    onSend(text);
  }

  return (
    <div className="flex flex-col h-full min-w-0" style={{ flex: 3, background: "#F8FAFC" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-6 h-[60px] bg-white border-b border-slate-200 shrink-0">
        <h1 className="text-[15px] font-semibold text-slate-800">
          {messages.length > 0
            ? messages.find((m) => m.role === "user")?.content.slice(0, 30) ?? "대화"
            : "부동산 AI 어시스턴트"}
        </h1>
        {messages.some((m) => m.agentName) && (
          <span
            className="text-xs font-medium px-3 py-1 rounded-full"
            style={{ background: "rgba(34,197,94,0.12)", color: "#15803D" }}
          >
            ● {messages.find((m) => m.agentName)?.agentName}
          </span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
            <div className="w-14 h-14 rounded-2xl flex items-center justify-center text-2xl" style={{ background: "#EEF2FF" }}>
              🏢
            </div>
            <div>
              <p className="text-slate-700 font-medium text-base mb-1">무엇이든 물어보세요</p>
              <p className="text-sm text-slate-400">부동산 시세, 상권 분석, 가격 예측까지</p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center">
              {QUICK_QUERIES.map((q) => (
                <button
                  key={q}
                  onClick={() => onSend(q)}
                  className="text-sm px-4 py-2 rounded-full border border-blue-200 text-blue-600 hover:bg-blue-50 transition-colors"
                  style={{ background: "#EEF2FF" }}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {streaming && messages[messages.length - 1]?.role !== "assistant" && (
          <TypingIndicator />
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 px-4 py-3 bg-white border-t border-slate-200">
        <div className="flex items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            placeholder="부동산에 대해 무엇이든 질문하세요..."
            disabled={streaming}
            className="flex-1 px-5 py-3 rounded-full text-sm outline-none text-slate-700 disabled:opacity-50"
            style={{ background: "#F1F5F9", border: "1px solid #E2E8F0" }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || streaming}
            className="w-11 h-11 rounded-full flex items-center justify-center text-white transition-opacity disabled:opacity-40"
            style={{ background: "#2563EB" }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[72%] px-4 py-2.5 rounded-2xl rounded-tr-sm text-white text-sm leading-relaxed" style={{ background: "#2563EB" }}>
          {message.content}
        </div>
      </div>
    );
  }

  const rendered = renderContent(message.content);

  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[85%] px-4 py-3 rounded-2xl rounded-tl-sm text-sm leading-relaxed bg-white shadow-sm text-slate-700 ${message.streaming ? "streaming" : ""}`}
      >
        {rendered}
      </div>
    </div>
  );
}

function renderContent(text: string) {
  if (!text) return <span className="text-slate-400">분석 중...</span>;

  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let tableLines: string[] = [];
  let key = 0;

  const flushTable = () => {
    if (tableLines.length < 2) {
      tableLines.forEach((l) => elements.push(<p key={key++} className="mb-1">{l}</p>));
      tableLines = [];
      return;
    }
    const headers = tableLines[0].split("|").map((h) => h.trim()).filter(Boolean);
    const rows = tableLines.slice(2).map((r) => r.split("|").map((c) => c.trim()).filter(Boolean));
    elements.push(
      <div key={key++} className="overflow-x-auto my-2 rounded-lg border border-slate-200">
        <table className="data-table">
          <thead><tr>{headers.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
          <tbody>{rows.map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
        </table>
      </div>
    );
    tableLines = [];
  };

  for (const line of lines) {
    if (line.includes("|")) {
      tableLines.push(line);
    } else {
      if (tableLines.length) flushTable();
      if (!line.trim()) {
        elements.push(<br key={key++} />);
      } else if (line.startsWith("**") && line.endsWith("**")) {
        elements.push(<p key={key++} className="font-semibold mb-1">{line.replace(/\*\*/g, "")}</p>);
      } else {
        elements.push(<p key={key++} className="mb-1">{line}</p>);
      }
    }
  }
  if (tableLines.length) flushTable();

  return <>{elements}</>;
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="bg-white shadow-sm rounded-2xl rounded-tl-sm px-4 py-3 flex gap-1.5 items-center">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="w-2 h-2 rounded-full"
            style={{
              background: "#2563EB",
              animation: `blink 1.2s ${i * 0.2}s ease-in-out infinite`,
              opacity: 0.4,
            }}
          />
        ))}
      </div>
    </div>
  );
}
