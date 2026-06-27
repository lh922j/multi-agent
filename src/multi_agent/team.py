import json
import re
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import (
    HandoffMessage,
    TextMessage,
    ToolCallExecutionEvent,
    ToolCallRequestEvent,
)
from autogen_agentchat.teams import Swarm
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from loguru import logger

from .agents.router import make_router
from .agents.data_query import make_data_query_agent
from .agents.prediction import make_prediction_agent
from .agents.rag_agent import make_rag_agent
from .agents.anomaly import make_anomaly_agent
from .config import settings

# 세션별 히스토리
_HISTORY: dict[str, list] = {}


_MAP_RE = re.compile(r"§MAP§(.+?)§END§", re.DOTALL)

# 에이전트 이름 → 한국어 표시
_AGENT_LABELS = {
    "OrchestratorAgent": "🎯 의도 파악 중",
    "DataQueryAgent":    "🔍 데이터 조회 중",
    "PredictionAgent":   "📊 가격 예측 중",
    "RAGAgent":          "🗺️ 지역 정보 검색 중",
    "AnomalyAgent":      "⚠️ 이상거래 탐지 중",
}


@lru_cache(maxsize=1)
def _get_langfuse():
    """Langfuse 클라이언트 (키 없으면 None). v4 API 기준."""
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    try:
        from langfuse import Langfuse
        lf = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        if not hasattr(lf, "start_observation"):
            logger.warning("[langfuse] 호환되지 않는 버전 — 모니터링 비활성화")
            return None
        return lf
    except Exception as e:
        logger.warning(f"[langfuse] 초기화 실패: {e}")
        return None


def _build_swarm() -> Swarm:
    termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(30)
    return Swarm(
        participants=[
            make_router(),
            make_data_query_agent(),
            make_prediction_agent(),
            make_rag_agent(),
            make_anomaly_agent(),
        ],
        termination_condition=termination,
    )


_TEXT_KEY_RE = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')


_JSON_NOISE_RE = re.compile(
    r'^\s*["\{].*?"type"\s*:\s*"(?:trade|rent|commercial|location|station)".*',
    re.DOTALL,
)


def _parse_map_points(content: str) -> tuple[str, list[dict]]:
    m = _MAP_RE.search(content)
    if not m:
        # §MAP§가 잘린 경우: "text" 키를 직접 추출 시도
        tm = _TEXT_KEY_RE.search(content)
        if tm:
            try:
                return json.loads(f'"{tm.group(1)}"'), []
            except Exception:
                pass
        cleaned = content.replace("§END§", "").strip()
        # LLM이 map_points JSON을 그대로 출력한 경우 빈 문자열로 처리
        if _JSON_NOISE_RE.match(cleaned):
            return "", []
        return cleaned, []
    try:
        payload = json.loads(m.group(1))
        map_points = payload.get("map_points", [])
        # §MAP§ 바깥 텍스트 = 전문 에이전트가 작성한 답변
        agent_text = _MAP_RE.sub("", content).strip()
        # agent_text가 비어 있을 때만 raw tool text(payload["text"]) 사용
        text = agent_text or payload.get("text", "")
        return text, map_points
    except Exception:
        return _MAP_RE.sub("", content).strip(), []


async def stream_chat(
    message: str,
    thread_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    실시간 스트리밍 버전.
    각 에이전트 메시지를 dict로 yield:
      {"type": "status",  "agent": "DataQueryAgent", "label": "🔍 데이터 조회 중"}
      {"type": "tool",    "agent": "DataQueryAgent", "tool": "query_trade_data"}
      {"type": "done",    "answer": "...", "map_points": [...]}
    """
    langfuse = _get_langfuse()
    trace_span = None

    if langfuse:
        try:
            trace_id = langfuse.create_trace_id()
            trace_span = langfuse.start_observation(
                name="run_chat",
                as_type="span",
                trace_context={"trace_id": trace_id},
                input={"message": message},
            )
        except Exception as e:
            logger.warning(f"[langfuse] trace 생성 실패: {e}")
            trace_span = None

    swarm = _build_swarm()
    history = _HISTORY.get(thread_id, [])
    task_messages = [*history, TextMessage(content=message, source="user")]

    final_text = ""
    map_points: list[dict] = []
    all_messages = []
    primary_agent = ""   # OrchestratorAgent 제외한 전문 에이전트
    saw_tool_map = False  # 도구 결과에서 §MAP§를 실제로 본 경우

    # AnomalyAgent: 도구가 §MAP§를 반환하지 않지만 위치 마커가 필요 → fallback 항상 적용
    # DataQueryAgent: 도구가 §MAP§를 반환한 경우(개별 거래)만 fallback 적용
    #                 집계/카운트 쿼리는 §MAP§ 없음 → fallback 미적용
    _LOC_FALLBACK_ALWAYS = {"AnomalyAgent", "RAGAgent"}
    _LOC_FALLBACK_IF_SAW_MAP = {"DataQueryAgent"}
    _SKIP_AGENTS = {"OrchestratorAgent"}

    try:
        async for msg in swarm.run_stream(task=task_messages):
            # TaskResult는 스트림 마지막에 오는 최종 결과
            if isinstance(msg, TaskResult):
                all_messages = list(msg.messages)
                break

            all_messages.append(msg)
            source = getattr(msg, "source", "")

            # 전문 에이전트 추적 (마지막으로 활성화된 에이전트 기준)
            if source and source not in _SKIP_AGENTS and source in _AGENT_LABELS:
                primary_agent = source

            # 도구 실행 결과에서 §MAP§ 존재 여부 추적
            if isinstance(msg, ToolCallExecutionEvent):
                for item in getattr(msg, "content", []):
                    item_str = getattr(item, "content", "")
                    if isinstance(item_str, str) and "§MAP§" in item_str:
                        saw_tool_map = True
                        break

            # Langfuse span 기록 (v4)
            if langfuse and trace_span and source:
                try:
                    content_preview = str(getattr(msg, "content", ""))[:200]
                    child = trace_span.start_observation(
                        name=f"{source}:{type(msg).__name__}",
                        as_type="span",
                        input={"content": content_preview},
                    )
                    child.end()
                except Exception:
                    pass

            # 에이전트 전환 → status yield
            if source and source in _AGENT_LABELS:
                label = _AGENT_LABELS[source]
                logger.debug(f"[stream] {source} → {label}")
                yield {"type": "status", "agent": source, "label": label}

            # 툴 호출 → tool yield
            if isinstance(msg, ToolCallRequestEvent):
                for call in msg.content:
                    tool_name = call.name if hasattr(call, "name") else str(call)
                    logger.debug(f"[stream] tool_call: {tool_name}")
                    yield {"type": "tool", "agent": source, "tool": tool_name}

        # 최종 답변 추출 — handoff 메시지 제외
        _SKIP = ("transferred to", "adopting the role", "handoff to")

        def _is_valid(msg) -> str | None:
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                return None
            clean = content.replace("TERMINATE", "").strip()
            if not clean:
                return None
            if any(p in clean.lower() for p in _SKIP):
                return None
            return clean

        # 1차: 전문 에이전트(OrchestratorAgent 제외) 메시지 탐색
        _SPECIALIST = {"DataQueryAgent", "PredictionAgent", "RAGAgent", "AnomalyAgent"}
        for msg in reversed(all_messages):
            if getattr(msg, "source", "") in _SPECIALIST:
                clean = _is_valid(msg)
                if clean:
                    text_candidate, pts = _parse_map_points(clean)
                    if text_candidate:
                        final_text = text_candidate
                        map_points = pts
                        break
        # 2차: 전체 메시지에서 탐색
        if not final_text:
            for msg in reversed(all_messages):
                clean = _is_valid(msg)
                if clean:
                    text_candidate, pts = _parse_map_points(clean)
                    if text_candidate:
                        final_text = text_candidate
                        map_points = pts
                        break

        # 3차: map_points가 비어 있으면 모든 메시지에서 §MAP§ 직접 추출
        # (LLM이 §MAP§ 블록을 생략했을 때 fallback)
        if not map_points:
            for msg in all_messages:
                content = getattr(msg, "content", "")
                # list content (ToolCallExecutionResultMessage)
                if isinstance(content, list):
                    for item in content:
                        item_str = getattr(item, "content", "")
                        if isinstance(item_str, str) and "§MAP§" in item_str:
                            _, pts = _parse_map_points(item_str)
                            if pts:
                                map_points = pts
                                break
                elif isinstance(content, str) and "§MAP§" in content:
                    _, pts = _parse_map_points(content)
                    if pts:
                        map_points = pts
                        break
                if map_points:
                    break

    except Exception as e:
        logger.error(f"[stream_chat] 오류: {e}")
        final_text = f"오류가 발생했습니다: {e}"

    finally:
        # Langfuse trace 완료 (v4)
        if langfuse and trace_span:
            try:
                trace_span.update(output={"answer": final_text[:500]})
                trace_span.end()
                langfuse.flush()
            except Exception as e:
                logger.warning(f"[langfuse] flush 실패: {e}")

    # 지도 fallback 적용 조건:
    #   - AnomalyAgent: 항상 (도구가 §MAP§ 없어도 위치 핀 필요)
    #   - DataQueryAgent: 도구 결과에서 §MAP§를 실제로 본 경우만
    #     (집계·카운트 쿼리는 §MAP§ 없음 → fallback 미적용)
    _apply_fallback = (
        primary_agent in _LOC_FALLBACK_ALWAYS
        or (primary_agent in _LOC_FALLBACK_IF_SAW_MAP and saw_tool_map)
    )
    if _apply_fallback:
        # 역(驛) 이름이 질문에 있으면 station 마커 추가 (기존 map_points 유무 무관)
        _STATION_RE = re.compile(r"[\w가-힣]{1,6}역")
        station_match = _STATION_RE.search(message)
        if station_match:
            station_name = station_match.group(0)
            if not any(p.get("apt_name") == station_name for p in map_points):
                try:
                    from .tools.query_nearby import _geocode
                    coords = _geocode(station_name)
                    if coords:
                        map_points = list(map_points) + [{
                            "apt_name": station_name,
                            "dong_name": "",
                            "area_exclusive": 0,
                            "deal_amount": 0,
                            "latitude": coords[0],
                            "longitude": coords[1],
                            "type": "station",
                        }]
                        logger.debug(f"[stream] 역 마커 추가: {station_name} {coords}")
                except Exception as e:
                    logger.debug(f"[stream] 역 좌표 조회 실패: {e}")

        # map_points가 없으면 질문에서 지역명(구·동) 추출 후 좌표 조회
        if not map_points:
            _LOC_RE = re.compile(r"[\w가-힣]{1,6}(?:동|구|시)")
            loc_match = _LOC_RE.search(message)
            if loc_match:
                loc_name = loc_match.group(0)
                try:
                    from .tools.query_nearby import _geocode
                    coords = _geocode(loc_name)
                    if coords:
                        map_points = [{
                            "apt_name": loc_name,
                            "dong_name": "",
                            "area_exclusive": 0,
                            "deal_amount": 0,
                            "latitude": coords[0],
                            "longitude": coords[1],
                            "type": "location",
                        }]
                        logger.debug(f"[stream] 위치 마커 추가: {loc_name} {coords}")
                except Exception as e:
                    logger.debug(f"[stream] 위치 조회 실패: {e}")

    # 히스토리 갱신 — user 질문 + 최종 답변만 저장
    # (HandoffMessage·중간 에이전트 메시지는 다음 Swarm 라우팅을 혼란시키므로 제외)
    prev_history = _HISTORY.get(thread_id, [])
    clean_answer = final_text.replace("TERMINATE", "").strip() if final_text else ""
    new_entry: list = [
        TextMessage(content=message, source="user"),
    ]
    if clean_answer:
        new_entry.append(TextMessage(content=clean_answer, source="assistant"))
    _HISTORY[thread_id] = (prev_history + new_entry)[-6:]   # 최대 3턴(6개) 유지

    yield {"type": "done", "answer": final_text or "응답을 생성하지 못했습니다.", "map_points": map_points}


async def run_chat(message: str, thread_id: str) -> tuple[str, list[dict]]:
    """동기 호환용 래퍼 — stream_chat()을 소비해서 최종 결과만 반환."""
    result = {"answer": "", "map_points": []}
    async for event in stream_chat(message, thread_id):
        if event["type"] == "done":
            result = event
    return result["answer"], result["map_points"]


def clear_history(thread_id: str) -> None:
    _HISTORY.pop(thread_id, None)
