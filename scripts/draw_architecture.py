"""멀티에이전트 아키텍처 시각화."""
import matplotlib
matplotlib.rcParams["font.family"] = ["Apple SD Gothic Neo", "AppleGothic", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import matplotlib.patheffects as pe

fig, ax = plt.subplots(figsize=(20, 14))
ax.set_xlim(0, 20)
ax.set_ylim(0, 14)
ax.axis("off")
fig.patch.set_facecolor("#F8F9FA")
ax.set_facecolor("#F8F9FA")

# ── 색상 정의 ──
C_USER     = "#4A90D9"
C_STREAM   = "#7B68EE"
C_ORCH     = "#E67E22"
C_DATA     = "#27AE60"
C_PRED     = "#8E44AD"
C_RAG      = "#2980B9"
C_ANOM     = "#C0392B"
C_REPORT   = "#16A085"
C_DB       = "#95A5A6"
C_UI       = "#F39C12"
C_TOOLS    = "#BDC3C7"
C_BORDER   = "#2C3E50"
ALPHA_BOX  = 0.92


def rounded_box(ax, x, y, w, h, color, label, sublabel="", fontsize=11, subsize=8):
    box = FancyBboxPatch((x - w/2, y - h/2), w, h,
                         boxstyle="round,pad=0.08",
                         facecolor=color, edgecolor=C_BORDER,
                         linewidth=1.5, alpha=ALPHA_BOX, zorder=3)
    ax.add_patch(box)
    ax.text(x, y + (0.15 if sublabel else 0), label,
            ha="center", va="center", fontsize=fontsize,
            fontweight="bold", color="white", zorder=4)
    if sublabel:
        ax.text(x, y - 0.28, sublabel,
                ha="center", va="center", fontsize=subsize,
                color="white", alpha=0.85, zorder=4)


def tool_box(ax, x, y, label, color=C_TOOLS):
    box = FancyBboxPatch((x - 1.1, y - 0.22), 2.2, 0.44,
                         boxstyle="round,pad=0.05",
                         facecolor=color, edgecolor="#95A5A6",
                         linewidth=1.0, alpha=0.85, zorder=3)
    ax.add_patch(box)
    ax.text(x, y, label, ha="center", va="center",
            fontsize=7.5, color="#2C3E50", zorder=4)


def arrow(ax, x1, y1, x2, y2, color="#555", label="", style="->", lw=1.8):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color,
                                lw=lw, connectionstyle="arc3,rad=0.0"),
                zorder=2)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx+0.1, my+0.12, label, fontsize=7.5,
                color=color, ha="center", zorder=5,
                bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))


def section_bg(ax, x, y, w, h, color, title):
    rect = FancyBboxPatch((x, y), w, h,
                          boxstyle="round,pad=0.1",
                          facecolor=color, edgecolor=C_BORDER,
                          linewidth=1.0, alpha=0.12, zorder=1)
    ax.add_patch(rect)
    ax.text(x + 0.25, y + h - 0.3, title,
            fontsize=8, color=C_BORDER, alpha=0.6, zorder=2,
            style="italic")


# ════════════════════════════════════════════════
# 제목
ax.text(10, 13.5, "부동산·상권 AI 멀티에이전트 아키텍처",
        ha="center", va="center", fontsize=17,
        fontweight="bold", color=C_BORDER)
ax.text(10, 13.1, "AutoGen 0.4 Swarm  ·  PostgreSQL  ·  LightGBM  ·  GraphRAG",
        ha="center", va="center", fontsize=10, color="#7F8C8D")

# ════════════════════════════════════════════════
# [1] Streamlit UI (최상단 왼쪽)
section_bg(ax, 0.3, 11.3, 5.5, 1.5, C_UI, "Frontend")
rounded_box(ax, 3.0, 12.2, 4.8, 0.9, C_UI,
            "🖥  Streamlit UI",
            "chat_input / pydeck 지도 / 실시간 상태", fontsize=11, subsize=8)

# [2] stream_chat() / Queue
section_bg(ax, 0.3, 9.4, 5.5, 1.6, C_STREAM, "Streaming Layer")
rounded_box(ax, 3.0, 10.4, 4.8, 0.9, C_STREAM,
            "⚡  team.py  ·  stream_chat()",
            "Queue · background thread · Langfuse trace", fontsize=10, subsize=8)

arrow(ax, 3.0, 11.75, 3.0, 10.85, C_UI, "질문 + thread_id")
arrow(ax, 3.5, 10.85, 3.5, 11.75, C_STREAM, "이벤트 yield\n(status/tool/done)", lw=1.4)

# ════════════════════════════════════════════════
# [3] AutoGen Swarm 영역
section_bg(ax, 0.3, 2.5, 19.4, 6.6, "#E8F4FD", "AutoGen 0.4 Swarm  — Handoff 기반 라우팅")

# OrchestratorAgent (중앙 상단)
rounded_box(ax, 10.0, 8.4, 4.2, 0.9, C_ORCH,
            "🎯  OrchestratorAgent",
            "GPT-4o-mini  |  max_tokens=150", fontsize=10, subsize=8)

# stream_chat → Orchestrator
arrow(ax, 4.75, 10.0, 7.9, 8.65, C_STREAM, "task_messages\n(history + user)")

# 5개 전문 에이전트
agents = [
    (2.2,  6.8, C_DATA,  "🔍  DataQueryAgent",   "GPT-4o-mini | 1500 tok"),
    (5.8,  6.8, C_PRED,  "📊  PredictionAgent",  "GPT-4o-mini | 800 tok"),
    (10.0, 6.8, C_RAG,   "🗺  RAGAgent",    "GPT-4o-mini | 600 tok"),
    (14.2, 6.8, C_ANOM,  "⚠  AnomalyAgent",     "GPT-4o-mini | 800 tok"),
    (17.8, 6.8, C_REPORT,"✍  ReportAgent",       "GPT-4o-mini | 800 tok"),
]
handoff_targets = ["DataQueryAgent", "PredictionAgent", "RAGAgent", "AnomalyAgent", "ReportAgent"]

for ax_x, ax_y, col, label, sub in agents:
    rounded_box(ax, ax_x, ax_y, 3.4, 0.85, col, label, sub, fontsize=9, subsize=7.5)

# Orchestrator → 각 에이전트 (handoff 화살표)
orch_x = 10.0
for (ax_x, ax_y, col, *_) in agents:
    arrow(ax, orch_x, 7.95, ax_x, 7.23, col, lw=1.4)

# ── 도구 목록 ──
# DataQueryAgent 도구
tool_data = [
    (2.2, 5.85, "query_trade_data"),
    (2.2, 5.38, "query_rent_data"),
    (2.2, 4.91, "query_trade_nearby"),
    (2.2, 4.44, "query_rent_nearby"),
    (2.2, 3.97, "query_commercial_data"),
]
for tx, ty, tl in tool_data:
    tool_box(ax, tx, ty, tl, "#D5F5E3")
    arrow(ax, 2.2, 6.38, 2.2, ty + 0.22, "#27AE60", lw=1.0)

# PredictionAgent 도구
tool_pred = [
    (5.8, 5.85, "predict_price"),
    (5.8, 5.38, "get_station_coords"),
]
for tx, ty, tl in tool_pred:
    tool_box(ax, tx, ty, tl, "#E8DAEF")
    arrow(ax, 5.8, 6.38, 5.8, ty + 0.22, "#8E44AD", lw=1.0)

# RAGAgent 도구
tool_box(ax, 10.0, 5.85, "search_area_info", "#D6EAF8")
arrow(ax, 10.0, 6.38, 10.0, 6.07, "#2980B9", lw=1.0)

# AnomalyAgent 도구
tool_box(ax, 14.2, 5.85, "detect_anomaly", "#FADBD8")
arrow(ax, 14.2, 6.38, 14.2, 6.07, "#C0392B", lw=1.0)

# ReportAgent → TERMINATE (완료)
ax.text(17.8, 5.6, "TERMINATE", ha="center", va="center",
        fontsize=8.5, color=C_REPORT, fontweight="bold",
        bbox=dict(fc="white", ec=C_REPORT, linewidth=1.2, pad=3, boxstyle="round"))
ax.annotate("", xy=(17.8, 5.75), xytext=(17.8, 6.38),
            arrowprops=dict(arrowstyle="->", color=C_REPORT, lw=1.3), zorder=2)

# ReportAgent → stream_chat (최종 답변 반환)
arrow(ax, 17.8, 7.24, 17.8, 9.0, C_REPORT, lw=1.4)
ax.annotate("", xy=(4.75, 9.95), xytext=(17.8, 9.0),
            arrowprops=dict(arrowstyle="->", color=C_REPORT, lw=1.4,
                            connectionstyle="arc3,rad=-0.25"), zorder=2)
ax.text(11.5, 9.7, "final_text + map_points", fontsize=8,
        color=C_REPORT, ha="center",
        bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))

# ════════════════════════════════════════════════
# [4] 데이터 소스 영역
section_bg(ax, 0.3, 0.3, 19.4, 1.9, "#ECF0F1", "Data Sources")

db_items = [
    (2.5,  1.2, C_DB,    "🐘  PostgreSQL",  "apt_trade / apt_rent\ncommercial_store / apt_geocode"),
    (7.0,  1.2, "#636e72","📁  SQLite",      "realestate.db\n(기존 데이터 마이그레이션)"),
    (11.0, 1.2, "#6c5ce7","🤖  LightGBM",   "price_model_trade_lgbm\n_complex.pkl"),
    (15.0, 1.2, "#00b894","📄  area_info.json","학군·교통·상권\n정적 지식베이스"),
    (18.5, 1.2, "#fdcb6e","🗺  Kakao API",   "지오코딩 / Places\n(POI 검색)"),
]
for dx, dy, dc, dl, ds in db_items:
    rounded_box(ax, dx, dy, 3.4, 1.2, dc, dl, ds, fontsize=9, subsize=7.5)

# 에이전트 → DB 연결선
arrow(ax, 2.2, 3.5, 2.2, 1.8, "#7F8C8D", lw=1.2)   # DataQuery → PostgreSQL
arrow(ax, 3.5, 3.5, 7.0, 1.8, "#7F8C8D", lw=1.0)   # DataQuery → SQLite
arrow(ax, 5.8, 3.5, 11.0, 1.8, "#7F8C8D", lw=1.0)  # Prediction → LightGBM
arrow(ax, 10.0, 5.38, 15.0, 1.8, "#7F8C8D", lw=1.0) # GraphRAG → area_info
arrow(ax, 14.2, 5.38, 18.5, 1.8, "#7F8C8D", lw=1.0) # Anomaly/Nearby → Kakao

# ════════════════════════════════════════════════
# 범례
legend_items = [
    (C_UI,     "Streamlit UI"),
    (C_STREAM, "Streaming Layer"),
    (C_ORCH,   "Orchestrator"),
    (C_DATA,   "DataQuery"),
    (C_PRED,   "Prediction"),
    (C_RAG,    "GraphRAG"),
    (C_ANOM,   "Anomaly"),
    (C_REPORT, "Report"),
]
for i, (color, label) in enumerate(legend_items):
    lx = 6.5 + i * 1.7
    patch = mpatches.Patch(facecolor=color, edgecolor=C_BORDER, linewidth=0.8, label=label)
    ax.add_patch(FancyBboxPatch((lx - 0.3, 13.5), 0.6, 0.35,
                                boxstyle="round,pad=0.04",
                                facecolor=color, edgecolor=C_BORDER, linewidth=0.8, zorder=3))
    ax.text(lx + 0.5, 13.67, label, fontsize=7.5, va="center", color=C_BORDER, zorder=4)

plt.tight_layout(pad=0.5)
out_path = "docs/architecture.png"
import os; os.makedirs("docs", exist_ok=True)
plt.savefig(out_path, dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
print(f"저장 완료: {out_path}")
plt.show()
