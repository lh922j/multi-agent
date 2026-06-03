import asyncio
import queue as _queue
import threading
import uuid

import httpx
import pydeck as pdk
import streamlit as st


def iter_stream_events(user_input: str, thread_id: str):
    """
    stream_chat()을 백그라운드 스레드에서 실행하고
    Queue를 통해 이벤트를 실시간으로 yield.
    Streamlit 메인 스레드에서 호출하면 UI가 실시간 업데이트됨.
    """
    q: _queue.Queue = _queue.Queue()

    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _run():
                async for event in stream_chat(user_input, thread_id):
                    q.put(event)
            loop.run_until_complete(_run())
        except Exception as e:
            q.put({"type": "done", "answer": f"오류가 발생했습니다: {e}", "map_points": []})
        finally:
            q.put(None)
            loop.close()

    threading.Thread(target=target, daemon=True).start()

    while True:
        event = q.get(timeout=120)
        if event is None:
            break
        yield event


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from multi_agent.team import stream_chat, clear_history

st.set_page_config(
    page_title="부동산 AI 멀티에이전트",
    page_icon="🏢",
    layout="wide",
)

# ── 세션 초기화 ──────────────────────────────────────────────
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "map_entries" not in st.session_state:
    st.session_state.map_entries = []


# ── 카카오 Places API: 주변 POI 조회 ─────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_nearby_pois(lat: float, lon: float, radius: int = 600) -> list[dict]:
    """카카오 장소 검색으로 주변 지하철역·관광명소·문화시설을 가져옵니다."""
    try:
        from multi_agent.config import settings
        if not settings.kakao_api_key:
            return []

        # 지하철역(SW8), 관광명소(AT4), 문화시설(CT1) 순서로 수집
        categories = [("SW8", "🚉"), ("AT4", "📌"), ("CT1", "🏛")]
        pois: list[dict] = []
        seen: set[str] = set()

        for cat_code, icon in categories:
            url = "https://dapi.kakao.com/v2/local/search/category.json"
            resp = httpx.get(
                url,
                params={"category_group_code": cat_code, "x": lon, "y": lat,
                        "radius": radius, "size": 5},
                headers={"Authorization": f"KakaoAK {settings.kakao_api_key}"},
                timeout=3.0,
            )
            if resp.status_code != 200:
                continue
            for doc in resp.json().get("documents", []):
                name = doc["place_name"]
                if name in seen:
                    continue
                seen.add(name)
                pois.append({
                    "name": f"{icon} {name}",
                    "longitude": float(doc["x"]),
                    "latitude": float(doc["y"]),
                })
            if len(pois) >= 12:
                break

        return pois
    except Exception:
        return []


# ── 지도 렌더링 ───────────────────────────────────────────────
def _color_by_amount(amount: float, min_val: float, max_val: float) -> list[int]:
    ratio = (amount - min_val) / (max_val - min_val + 1)
    r = int(255 * ratio)
    b = int(255 * (1 - ratio))
    return [r, 0, b, 180]


def _render_map(points: list[dict]):
    if not points:
        return

    trade_pts   = [p for p in points if p.get("type") in ("trade", "rent")]
    comm_pts    = [p for p in points if p.get("type") == "commercial"]
    loc_pts     = [p for p in points if p.get("type") == "location"]
    station_pts = [p for p in points if p.get("type") == "station"]

    layers = []

    if station_pts:
        for p in station_pts:
            p["tooltip"] = f"🚉 {p['apt_name']}"
            p["label"] = f"🚉 {p['apt_name']}"
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=station_pts,
                get_position="[longitude, latitude]",
                get_fill_color=[255, 80, 0, 220],
                get_radius=60,
                pickable=True,
            )
        )
        layers.append(
            pdk.Layer(
                "TextLayer",
                data=station_pts,
                get_position="[longitude, latitude]",
                get_text="label",
                get_size=14,
                get_color=[180, 40, 0],
                get_pixel_offset=[0, -18],
                get_alignment_baseline="'bottom'",
            )
        )

    if loc_pts:
        for p in loc_pts:
            p["tooltip"] = f"📍 {p['apt_name']}"
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=loc_pts,
                get_position="[longitude, latitude]",
                get_fill_color=[30, 120, 255, 40],
                get_line_color=[30, 120, 255, 200],
                get_line_width=8,
                stroked=True,
                filled=True,
                get_radius=400,
                pickable=True,
            )
        )
        layers.append(
            pdk.Layer(
                "TextLayer",
                data=loc_pts,
                get_position="[longitude, latitude]",
                get_text="apt_name",
                get_size=16,
                get_color=[30, 80, 200],
                get_alignment_baseline="'bottom'",
            )
        )

    if trade_pts:
        amounts = [p["deal_amount"] for p in trade_pts if p.get("deal_amount")]
        min_a = min(amounts) if amounts else 0
        max_a = max(amounts) if amounts else 1
        for p in trade_pts:
            p["color"] = _color_by_amount(p.get("deal_amount", 0), min_a, max_a)
            p["tooltip"] = f"{p['apt_name']} | {p['dong_name']} | {int(p['deal_amount']):,}만원"
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=trade_pts,
                get_position="[longitude, latitude]",
                get_fill_color="color",
                get_radius=150,
                pickable=True,
            )
        )

    if comm_pts:
        for p in comm_pts:
            p["tooltip"] = f"{p['apt_name']} | {p.get('category', '')} | {p['dong_name']}"
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=comm_pts,
                get_position="[longitude, latitude]",
                get_fill_color=[0, 200, 100, 160],
                get_radius=80,
                pickable=True,
            )
        )

    if not layers:
        return

    center_lat = sum(p["latitude"] for p in points) / len(points)
    center_lon = sum(p["longitude"] for p in points) / len(points)

    # 포인트 수에 따라 줌 레벨 조정
    zoom = 14 if len(points) <= 2 else 13

    # ── 카카오 주변 POI 레이어 (지하철역·관광명소·문화시설) ──
    poi_data = _fetch_nearby_pois(center_lat, center_lon, radius=600)
    if poi_data:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=poi_data,
                get_position="[longitude, latitude]",
                get_fill_color=[100, 100, 100, 60],
                get_line_color=[80, 80, 80, 160],
                get_line_width=3,
                stroked=True,
                filled=True,
                get_radius=30,
                pickable=False,
            )
        )
        layers.append(
            pdk.Layer(
                "TextLayer",
                data=poi_data,
                get_position="[longitude, latitude]",
                get_text="name",
                get_size=12,
                get_color=[60, 60, 60, 200],
                get_pixel_offset=[0, -12],
                get_alignment_baseline="'bottom'",
                background=True,
                get_background_color=[255, 255, 255, 180],
                get_border_color=[200, 200, 200, 200],
                get_border_width=1,
            )
        )

    st.pydeck_chart(
        pdk.Deck(
            map_style="https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
            initial_view_state=pdk.ViewState(
                latitude=center_lat,
                longitude=center_lon,
                zoom=zoom,
                pitch=0,
            ),
            layers=layers,
            tooltip={
                "html": "<b>{tooltip}</b>",
                "style": {
                    "backgroundColor": "white",
                    "color": "#333",
                    "fontSize": "13px",
                    "padding": "6px 10px",
                    "borderRadius": "4px",
                },
            },
        )
    )


# ── UI 레이아웃 ───────────────────────────────────────────────
st.title("🏢 부동산 · 상권 AI 멀티에이전트")
st.caption("AutoGen 0.4 Swarm + GraphRAG + Pinecone | 아파트 실거래 + 상권 분석")

col_chat, col_map = st.columns([3, 2])

# ── 대화 히스토리 (위 → 아래로 쌓임) ──────────────────────────
with col_chat:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# ── 지도 패널 ────────────────────────────────────────────────
with col_map:
    st.subheader("📍 거래 위치")
    if st.session_state.map_entries:
        latest = st.session_state.map_entries[-1]
        st.caption(f"질문: {latest['question']}")
        _render_map(latest["points"])

        if len(st.session_state.map_entries) > 1:
            with st.expander("이전 지도 조회 히스토리"):
                for entry in reversed(st.session_state.map_entries[:-1]):
                    st.caption(entry["question"])
                    _render_map(entry["points"])
    else:
        st.info("거래 조회 시 지도에 위치가 표시됩니다.")

# ── 사이드바 ──────────────────────────────────────────────────
with st.sidebar:
    st.header("🏢 부동산 AI")

    # ── 대화 히스토리 ─────────────────────────────────────────
    if st.session_state.messages:
        st.subheader("대화 히스토리")
        pairs = []
        i = 0
        msgs = st.session_state.messages
        while i < len(msgs):
            if msgs[i]["role"] == "user":
                q = msgs[i]["content"]
                a = msgs[i + 1]["content"] if i + 1 < len(msgs) and msgs[i + 1]["role"] == "assistant" else ""
                pairs.append((q, a))
                i += 2
            else:
                i += 1
        for idx, (q, a) in enumerate(reversed(pairs), 1):
            q_short = q[:30] + "..." if len(q) > 30 else q
            with st.expander(f"{len(pairs) - idx + 1}. {q_short}"):
                st.markdown(a[:300] + "..." if len(a) > 300 else a)
        st.divider()

    if st.button("대화 초기화", use_container_width=True):
        clear_history(st.session_state.thread_id)
        st.session_state.messages = []
        st.session_state.map_entries = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.rerun()

    st.divider()
    with st.expander("예시 질문"):
        st.markdown("""
**부동산**
- 역삼동 84㎡ 매매 최근 시세
- 강남역 근처 전세 1km 이내
- 강남구 이상거래 탐지

**상권**
- 홍대 상권 업종 현황
- 마포구 카페 몇 개야

**지역 정보**
- 마포구 학군 어때
- GTX 수혜 지역 알려줘
""")

# ── 입력창 (페이지 하단 고정) ─────────────────────────────────
if user_input := st.chat_input("질문을 입력하세요 (예: 강남구 84㎡ 매매 시세 알려줘)"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    thread_id = st.session_state.thread_id

    answer = "응답을 생성하지 못했습니다."
    map_points: list[dict] = []

    # 처리 중 상태 표시 (col_chat 하단에 추가, 실시간 업데이트)
    with col_chat:
        with st.chat_message("assistant"):
            status = st.empty()
            try:
                for event in iter_stream_events(user_input, thread_id):
                    if event["type"] == "status":
                        status.info(event["label"])
                    elif event["type"] == "tool":
                        status.info(f"⚙️ 처리 중 → `{event['tool']}`")
                    elif event["type"] == "done":
                        answer = event["answer"]
                        map_points = event["map_points"]
            except Exception as e:
                answer = f"오류가 발생했습니다: {e}"
            status.empty()
            st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})

    if map_points:
        st.session_state.map_entries.append({
            "question": user_input,
            "points": map_points,
        })
    st.rerun()
