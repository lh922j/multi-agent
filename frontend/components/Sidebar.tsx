"use client";
import { Session } from "@/types";

interface Props {
  sessions: Session[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onCollapse: () => void;
}

export default function Sidebar({ sessions, activeSessionId, onSelectSession, onNewSession, onCollapse }: Props) {
  return (
    <aside className="group relative flex flex-col h-full w-[260px] shrink-0" style={{ background: "#111827" }}>

      {/* 닫기 버튼 — hover 시 표시 */}
      <button
        onClick={onCollapse}
        title="사이드바 닫기"
        className="absolute top-4 right-3 w-7 h-7 rounded-md flex items-center justify-center transition-all duration-150 opacity-0 group-hover:opacity-100"
        style={{ color: "#6B7280", background: "rgba(255,255,255,0.06)" }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <polyline points="15 18 9 12 15 6" />
        </svg>
      </button>

      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center text-base shrink-0" style={{ background: "#2563EB" }}>
          🏢
        </div>
        <span className="text-white font-bold text-[15px]">부동산·상권 Agent</span>
      </div>

      {/* New chat */}
      <div className="px-4 mb-4">
        <button
          onClick={onNewSession}
          className="w-full py-2 rounded-lg text-white text-sm font-medium transition-opacity hover:opacity-90"
          style={{ background: "#2563EB" }}
        >
          + 새 대화 시작
        </button>
      </div>

      {/* History label */}
      <div className="px-4 mb-2">
        <span className="text-xs font-medium" style={{ color: "#6B7280" }}>최근 대화</span>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-3 space-y-1">
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelectSession(s.id)}
            className="w-full text-left px-3 py-3 rounded-lg transition-colors hover:bg-white/5"
            style={{ background: s.id === activeSessionId ? "rgba(37,99,235,0.18)" : "transparent" }}
          >
            <p className="text-sm truncate" style={{ color: s.id === activeSessionId ? "#E0EAFF" : "#9CA3AF" }}>
              {s.title}
            </p>
            <p className="text-xs mt-0.5" style={{ color: "#6B7280" }}>
              {formatTime(s.updatedAt)}
            </p>
          </button>
        ))}
        {sessions.length === 0 && (
          <p className="text-xs px-3 py-2" style={{ color: "#4B5563" }}>아직 대화가 없습니다</p>
        )}
      </div>

      {/* User */}
      <div className="m-3 px-3 py-2.5 rounded-lg flex items-center gap-3" style={{ background: "rgba(255,255,255,0.06)" }}>
        <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0" style={{ background: "#2563EB" }}>
          U
        </div>
        <div>
          <p className="text-sm font-medium text-white">사용자</p>
          <p className="text-xs" style={{ color: "#6B7280" }}>GPT-4o mini</p>
        </div>
      </div>
    </aside>
  );
}

function formatTime(d: Date) {
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "방금 전";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}분 전`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}시간 전`;
  return `${Math.floor(diff / 86_400_000)}일 전`;
}
