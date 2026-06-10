"""
시스템 지표 pytest — CI/CD 모든 PR에서 실행 (LLM 호출 없음 또는 최소)

테스트 범주:
  - 라우팅 정확도 (OrchestratorAgent → 올바른 전문 에이전트)
  - 지도 좌표 반환 여부 (map_points expected_map_points=True인 케이스)
  - E2E 응답 지연 (≤ 20s per case, 평균 ≤ 15s)
  - 오류 없이 응답 반환

실행:
    pytest tests/eval/test_system_metrics.py -v
    pytest tests/eval/test_system_metrics.py -v -k "routing"   # 라우팅만
    pytest tests/eval/test_system_metrics.py -v -k "latency"   # 지연만
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

GOLDEN_PATH = Path(__file__).parent / "golden_set.json"
_LATENCY_PER_CASE_SEC = 20.0   # 단일 케이스 최대 허용 지연
_LATENCY_AVG_SEC = 15.0        # 전체 평균 허용 지연


def _load(tags: list[str] | None = None) -> list[dict]:
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if tags:
        cases = [c for c in cases if any(t in c.get("tags", []) for t in tags)]
    return cases


# ── 1. 라우팅 정확도 ──────────────────────────────────────────────
# OrchestratorAgent가 올바른 전문 에이전트로 handoff하는지 확인
# LLM 1 hop만 사용 (저비용)

_ROUTING_CASES = [c for c in _load() if "multiturn" not in c.get("tags", [])]

@pytest.mark.parametrize("case", _ROUTING_CASES, ids=[c["id"] for c in _ROUTING_CASES])
def test_routing_accuracy(case, router_agent):
    """OrchestratorAgent가 expected_agent로 handoff해야 함."""
    expected = case["expected_agent"]
    actual = router_agent(case["input"])
    assert expected in actual, (
        f"[{case['id']}] 라우팅 실패 — expected={expected}, actual={actual!r}"
    )


# ── 2. 응답 완결성 ────────────────────────────────────────────────
# 모든 케이스에서 비어있지 않은 답변을 반환해야 함

_E2E_CASES = _load(tags=["trade", "commercial", "prediction", "anomaly"])

@pytest.mark.parametrize("case", _E2E_CASES, ids=[c["id"] for c in _E2E_CASES])
def test_response_not_empty(case, run_agent):
    """에이전트가 빈 문자열이 아닌 응답을 반환해야 함."""
    result = run_agent(case["input"])
    assert result.answer.strip(), f"[{case['id']}] 빈 응답 반환"
    assert len(result.answer) >= 20, (
        f"[{case['id']}] 응답이 너무 짧음: {result.answer!r}"
    )


# ── 3. 지도 좌표 반환 여부 ────────────────────────────────────────
# expected_map_points=True인 케이스에서 map_points가 비어있으면 안 됨

_MAP_CASES = [c for c in _load() if c.get("expected_map_points")]

@pytest.mark.parametrize("case", _MAP_CASES, ids=[c["id"] for c in _MAP_CASES])
def test_map_points_returned(case, run_agent):
    """지도 마커가 필요한 케이스에서 map_points를 반환해야 함."""
    result = run_agent(case["input"])
    assert result.map_points, (
        f"[{case['id']}] map_points 없음 — 지도 마커 반환 실패\n"
        f"답변: {result.answer[:200]}"
    )
    for pt in result.map_points:
        lat = pt.get("latitude", 0)
        lon = pt.get("longitude", 0)
        assert 33.0 <= lat <= 38.5, f"[{case['id']}] 위도 범위 이상: {lat}"
        assert 125.0 <= lon <= 130.0, f"[{case['id']}] 경도 범위 이상: {lon}"


# ── 4. 응답 지연 ──────────────────────────────────────────────────
# 단일 케이스 ≤ 20s, 전체 평균 ≤ 15s

@pytest.mark.parametrize("case", _E2E_CASES, ids=[c["id"] for c in _E2E_CASES])
def test_latency_per_case(case, run_agent):
    """단일 케이스 지연이 20초 이하여야 함."""
    result = run_agent(case["input"])
    assert result.latency_sec <= _LATENCY_PER_CASE_SEC, (
        f"[{case['id']}] 지연 초과: {result.latency_sec:.1f}s > {_LATENCY_PER_CASE_SEC}s"
    )


def test_latency_average(run_agent):
    """전체 E2E 케이스 평균 지연이 15초 이하여야 함."""
    latencies = [run_agent(c["input"]).latency_sec for c in _E2E_CASES]
    avg = sum(latencies) / len(latencies)
    assert avg <= _LATENCY_AVG_SEC, (
        f"평균 지연 초과: {avg:.1f}s > {_LATENCY_AVG_SEC}s\n"
        + "\n".join(f"  {c['id']}: {l:.1f}s" for c, l in zip(_E2E_CASES, latencies))
    )


# ── 5. 범위 외 거절 ───────────────────────────────────────────────
# offscope 케이스에서 부동산 관련 거절 응답이 반환되어야 함

_OFFSCOPE_CASES = _load(tags=["offscope"])

@pytest.mark.parametrize("case", _OFFSCOPE_CASES, ids=[c["id"] for c in _OFFSCOPE_CASES])
def test_offscope_rejection(case, run_agent):
    """범위 외 질문에 거절 문구가 포함되어야 함."""
    result = run_agent(case["input"])
    keywords = ["부동산", "상권", "답변", "전문", "범위", "죄송", "지원"]
    assert any(kw in result.answer for kw in keywords), (
        f"[{case['id']}] 거절 문구 없음: {result.answer[:200]}"
    )


# ── 6. 멀티턴 맥락 유지 ────────────────────────────────────────────
# 이전 대화에서 언급된 지역명을 다음 턴에서도 기억하는지 확인

_MULTITURN_CASES = _load(tags=["multiturn"])

@pytest.mark.parametrize("case", _MULTITURN_CASES, ids=[c["id"] for c in _MULTITURN_CASES])
def test_multiturn_context_retention(case, run_multiturn_agent):
    """첫 번째 턴의 지역명이 마지막 턴 답변에 반영되어야 함."""
    import re
    result = run_multiturn_agent(case["turns"])
    assert result.answer.strip(), f"[{case['id']}] 빈 응답"

    first_turn = case["turns"][0]
    loc_m = re.search(r"([\w가-힣]{2,4}(?:구|동|시))", first_turn)
    if loc_m:
        loc = loc_m.group(1)
        assert loc in result.answer, (
            f"[{case['id']}] 맥락 유지 실패 — '{loc}'이 답변에 없음\n"
            f"마지막 질문: {case['turns'][-1]}\n"
            f"답변: {result.answer[:300]}"
        )
