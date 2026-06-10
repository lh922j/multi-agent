import json
import os
import re
import uuid

import httpx
import pydeck as pdk
import streamlit as st

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")


def iter_sse_events(user_input: str, thread_id: str):
    """FastAPI /chat/stream SSE 엔드포인트에서 스트리밍 이벤트를 수신."""
    try:
        with httpx.Client(timeout=120.0) as client:
            with client.stream(
                "POST", f"{API_BASE}/chat/stream",
                json={"message": user_input, "thread_id": thread_id},
            ) as resp:
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:].strip()
                        if data:
                            yield json.loads(data)
    except Exception as e:
        yield {"type": "done", "answer": f"API 서버에 연결할 수 없습니다 (FastAPI 실행 확인): {e}", "map_points": []}

st.set_page_config(
    page_title="부동산 AI 멀티에이전트",
    page_icon="🏢",
    layout="wide",
)

# ── 멀티세션 관리 ────────────────────────────────────────────

def _make_session() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "thread_id": str(uuid.uuid4()),
        "title": "새 대화",
        "messages": [],
        "map_entries": [],
    }


if "sessions" not in st.session_state:
    _first = _make_session()
    st.session_state.sessions = [_first]
    st.session_state.active_id = _first["id"]


def _active() -> dict:
    for s in st.session_state.sessions:
        if s["id"] == st.session_state.active_id:
            return s
    return st.session_state.sessions[0]


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


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_school_pois(lat: float, lon: float, radius: int = 2000) -> list[dict]:
    """카카오 키워드 검색으로 주변 초·중·고 학교를 가져옵니다."""
    try:
        from multi_agent.config import settings
        if not settings.kakao_api_key:
            return []

        school_configs = [
            ("초등학교", [50, 180, 80, 220],  "🟢"),
            ("중학교",   [255, 165, 0, 220],  "🟠"),
            ("고등학교", [220, 50, 50, 220],  "🔴"),
        ]
        schools: list[dict] = []
        seen: set[str] = set()

        for school_type, color, icon in school_configs:
            url = "https://dapi.kakao.com/v2/local/search/keyword.json"
            resp = httpx.get(
                url,
                params={"query": school_type, "x": lon, "y": lat,
                        "radius": radius, "size": 8, "sort": "distance"},
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
                schools.append({
                    "name": name,
                    "school_type": school_type,
                    "icon": icon,
                    "longitude": float(doc["x"]),
                    "latitude": float(doc["y"]),
                    "label": f"{icon} {name}",
                    "color": color,
                    "tooltip": f"{school_type} | {name}",
                    "type": "school",
                })

        return schools
    except Exception:
        return []


# ── 지도 렌더링 ───────────────────────────────────────────────
def _color_by_amount(amount: float, min_val: float, max_val: float) -> list[int]:
    ratio = (amount - min_val) / (max_val - min_val + 1)
    r = int(255 * ratio)
    b = int(255 * (1 - ratio))
    return [r, 0, b, 80]


@st.cache_data(ttl=3600, show_spinner=False)
def _get_district_hull(district_name: str) -> list | None:
    """구/동 이름으로 ConvexHull 폴리곤 좌표를 반환 (DB 좌표 기반)."""
    try:
        import numpy as np
        from scipy.spatial import ConvexHull
        from sqlalchemy import text
        from multi_agent.db.database import get_engine
        from multi_agent.tools._district import _load as _load_codes

        engine = get_engine()
        with engine.connect() as conn:
            if district_name.endswith("구"):
                codes_map = _load_codes()
                codes = codes_map.get(district_name, [])
                if not codes:
                    return None
                placeholders = ", ".join(f"'{c}'" for c in codes)
                rows = conn.execute(text(f"""
                    SELECT latitude, longitude FROM commercial_store
                    WHERE sgg_code::text IN ({placeholders})
                      AND latitude IS NOT NULL AND longitude IS NOT NULL
                    LIMIT 3000
                """)).fetchall()
            else:
                rows = conn.execute(text("""
                    SELECT latitude, longitude FROM apt_geocode
                    WHERE dong_name = :dong
                      AND latitude IS NOT NULL AND longitude IS NOT NULL
                """), {"dong": district_name}).fetchall()

        if len(rows) < 3:
            return None

        pts = np.array([[r.longitude, r.latitude] for r in rows])
        hull = ConvexHull(pts)
        polygon = pts[hull.vertices].tolist()
        polygon.append(polygon[0])
        return polygon
    except Exception:
        return None


def _extract_district(question: str) -> str | None:
    """질문에서 구/동 이름 추출."""
    m = re.search(r"([\w가-힣]{1,6}(?:구|동))", question)
    return m.group(1) if m else None


def _render_map(points: list[dict], question: str = ""):
    if not points:
        return

    trade_pts   = [p for p in points if p.get("type") in ("trade", "rent")]
    comm_pts    = [p for p in points if p.get("type") == "commercial"]
    loc_pts     = [p for p in points if p.get("type") == "location"]
    station_pts = [p for p in points if p.get("type") == "station"]
    school_pts  = [p for p in points if p.get("type") == "school"]

    # 학교 마커가 있으면 location 원형은 표시하지 않음 (중복/혼란 방지)
    if school_pts:
        loc_pts = []

    layers = []
    _has_district_polygon = False

    # ── 구/동 영역 폴리곤 ─────────────────────────────────────
    if question:
        _district = _extract_district(question)
        if _district:
            _hull = _get_district_hull(_district)
            if _hull:
                _has_district_polygon = True
                layers.append(
                    pdk.Layer(
                        "PolygonLayer",
                        data=[{"polygon": _hull, "name": _district}],
                        get_polygon="polygon",
                        get_fill_color=[100, 150, 255, 35],
                        get_line_color=[80, 120, 220, 180],
                        get_line_width=40,
                        pickable=False,
                    )
                )

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

    if school_pts:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=school_pts,
                get_position="[longitude, latitude]",
                get_fill_color="color",
                get_radius=55,
                pickable=True,
            )
        )
        # 타입별로 가장 가까운 3개만 라벨 표시 (전체 표시 시 겹침 과다)
        _type_cnt: dict[str, int] = {}
        _label_pts = []
        for _p in school_pts:
            _t = _p["school_type"]
            if _type_cnt.get(_t, 0) < 3:
                _label_pts.append(_p)
                _type_cnt[_t] = _type_cnt.get(_t, 0) + 1
        layers.append(
            pdk.Layer(
                "TextLayer",
                data=_label_pts,
                get_position="[longitude, latitude]",
                get_text="label",
                get_size=11,
                get_color=[20, 20, 20],
                get_pixel_offset=[0, -14],
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
                get_line_color="color",
                get_line_width=8,
                stroked=True,
                filled=True,
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

    # 포인트 수에 따라 줌 레벨 조정 (학교 마커가 많으면 더 넓게)
    if school_pts:
        zoom = 14
    elif len(points) <= 2:
        zoom = 14
    else:
        zoom = 13

    # ── 카카오 주변 POI 레이어 (지하철역·관광명소·문화시설)
    # 학교 마커 또는 구/동 폴리곤이 있을 때는 표시하지 않음 (혼잡 방지)
    if not school_pts and not _has_district_polygon:
        poi_data = _fetch_nearby_pois(center_lat, center_lon, radius=600)
        if poi_data:
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=poi_data,
                    get_position="[longitude, latitude]",
                    get_fill_color=[80, 130, 200, 160],
                    get_line_color=[50, 100, 180, 200],
                    get_line_width=2,
                    stroked=True,
                    filled=True,
                    get_radius=28,
                    pickable=True,
                )
            )
            layers.append(
                pdk.Layer(
                    "TextLayer",
                    data=poi_data,
                    get_position="[longitude, latitude]",
                    get_text="name",
                    get_size=10,
                    get_color=[40, 40, 80],
                    get_pixel_offset=[0, -10],
                    get_alignment_baseline="'bottom'",
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
st.caption("아파트 실거래 + 상권 분석 | made by donghoon")

col_chat, col_map = st.columns([3, 2])

# ── 대화 히스토리 (스크롤 컨테이너) ─────────────────────────────
with col_chat:
    with st.container(height=620, border=False):
        for msg in _active()["messages"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

# ── 지도 패널 ────────────────────────────────────────────────
_SCHOOL_KEYWORDS = ("학군", "학교", "교육", "학원")


def _enrich_with_schools(question: str, points: list[dict]) -> list[dict]:
    """학군 관련 질문이면 학교 POI를 points에 추가."""
    if not any(kw in question for kw in _SCHOOL_KEYWORDS):
        return points
    if not points:
        return points
    clat = sum(p["latitude"] for p in points) / len(points)
    clon = sum(p["longitude"] for p in points) / len(points)
    school_pois = _fetch_school_pois(clat, clon, radius=2000)
    return list(points) + school_pois


with col_map:
    st.subheader("📍 거래 위치")
    _map_entries = _active()["map_entries"]
    if _map_entries:
        latest = _map_entries[-1]
        st.caption(f"질문: {latest['question']}")
        enriched = _enrich_with_schools(latest["question"], latest["points"])

        # 현재 질문에 지역명 없으면 이전 질문 중 지역명 있는 것을 폴백으로 사용
        _district_q = next(
            (e["question"] for e in reversed(_map_entries) if _extract_district(e["question"])),
            latest["question"],
        )
        _render_map(enriched, question=_district_q)

        if len(_map_entries) > 1:
            with st.expander("이전 지도 조회 히스토리"):
                for entry in reversed(_map_entries[:-1]):
                    st.caption(entry["question"])
                    _render_map(_enrich_with_schools(entry["question"], entry["points"]), question=entry["question"])
    else:
        st.info("거래 조회 시 지도에 위치가 표시됩니다.")

# ── 사이드바 ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🏢 부동산·상권 AI")

    # ── 새 대화 버튼 ──────────────────────────────────────────
    if st.button("✏️  새 대화", use_container_width=True, type="primary"):
        _new_s = _make_session()
        st.session_state.sessions.insert(0, _new_s)
        st.session_state.active_id = _new_s["id"]
        st.rerun()

    st.divider()

    # ── 대화 세션 목록 (메시지 없는 새 대화 숨김, 최신→위 정렬) ──
    for _sess in st.session_state.sessions:
        if not _sess["messages"]:
            continue
        _is_active = _sess["id"] == st.session_state.active_id
        _title = _sess["title"]
        _label = (_title[:24] + "…") if len(_title) > 24 else _title

        if st.button(
            f"▶  {_label}" if _is_active else _label,
            key=f"sess_{_sess['id']}",
            use_container_width=True,
            type="primary" if _is_active else "secondary",
        ):
            st.session_state.active_id = _sess["id"]
            st.rerun()

    st.divider()

    # ── 예시 질문 ─────────────────────────────────────────────
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

    # ── 전체 초기화 (맨 아래) ─────────────────────────────────
    st.markdown("<div style='flex:1'></div>", unsafe_allow_html=True)
    if st.button("🗑️  전체 초기화", use_container_width=True):
        for _s in st.session_state.sessions:
            httpx.delete(f"{API_BASE}/chat/{_s['thread_id']}", timeout=5.0)
        _first = _make_session()
        st.session_state.sessions = [_first]
        st.session_state.active_id = _first["id"]
        st.rerun()

# ── 입력창 (페이지 하단 고정) ─────────────────────────────────
if user_input := st.chat_input("질문을 입력하세요 (예: 강남구 84㎡ 매매 시세 알려줘)"):
    _sess = _active()
    _sess["messages"].append({"role": "user", "content": user_input})

    # 첫 번째 메시지로 세션 제목 설정
    if _sess["title"] == "새 대화":
        _sess["title"] = user_input

    thread_id = _sess["thread_id"]
    answer = "응답을 생성하지 못했습니다."
    map_points: list[dict] = []

    with col_chat:
        with st.chat_message("assistant"):
            status = st.empty()
            try:
                for event in iter_sse_events(user_input, thread_id):
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

    _sess["messages"].append({"role": "assistant", "content": answer})

    if map_points:
        _sess["map_entries"].append({
            "question": user_input,
            "points": map_points,
        })
    st.rerun()
