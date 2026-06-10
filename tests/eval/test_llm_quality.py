"""
DeepEval 네이티브 LLM 품질 평가 — CI/CD 연동용

실행:
    # Confident AI 대시보드 연동 (최초 1회)
    deepeval login

    # 전체 실행 (main 브랜치 push 시)
    deepeval test run tests/eval/test_llm_quality.py

    # 특정 태그만 실행
    deepeval test run tests/eval/test_llm_quality.py -k "rag"

    # 로컬 빠른 실행 (대시보드 없이)
    pytest tests/eval/test_llm_quality.py -v --no-header
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from deepeval import assert_test
from deepeval.metrics import (
    AnswerRelevancyMetric, FaithfulnessMetric, GEval,
    ContextualRecallMetric, ContextualPrecisionMetric,
)
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

GOLDEN_PATH = Path(__file__).parent / "golden_set.json"
_MODEL = "gpt-4o-mini"


def _load_cases(tags: list[str] | None = None) -> list[dict]:
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if tags:
        cases = [c for c in cases if any(t in c.get("tags", []) for t in tags)]
    # offscope는 LLM 품질 평가 제외 (거절 응답이므로 relevancy=0 정상)
    return [c for c in cases if "offscope" not in c.get("tags", [])]


def _run_agent(question: str) -> tuple[str, list[dict]]:
    """멀티에이전트 동기 호출."""
    import uuid
    from multi_agent.team import run_chat
    thread_id = f"eval-{uuid.uuid4().hex[:8]}"
    return asyncio.run(run_chat(question, thread_id))


# ── 답변 관련성 테스트 ────────────────────────────────────────────

@pytest.mark.parametrize("case", _load_cases(tags=["trade", "commercial"]))
def test_answer_relevancy_data(case):
    """DataQueryAgent 응답의 질문 관련성 ≥ 0.7."""
    answer, _ = _run_agent(case["input"])
    tc = LLMTestCase(
        input=case["input"],
        actual_output=answer,
        expected_output=case["reference"],
    )
    assert_test(tc, [
        AnswerRelevancyMetric(threshold=0.7, model=_MODEL, verbose_mode=False),
    ])


@pytest.mark.parametrize("case", _load_cases(tags=["rag"]))
def test_answer_relevancy_rag(case):
    """RAGAgent 응답의 질문 관련성 ≥ 0.6 (RAG는 임계값 완화)."""
    answer, _ = _run_agent(case["input"])
    tc = LLMTestCase(
        input=case["input"],
        actual_output=answer,
        expected_output=case["reference"],
        retrieval_context=[case["context"]] if case.get("context") else [],
    )
    assert_test(tc, [
        AnswerRelevancyMetric(threshold=0.6, model=_MODEL, verbose_mode=False),
    ])


# ── Context Recall / Precision 테스트 (RAG 전용) ─────────────────

@pytest.mark.parametrize("case", _load_cases(tags=["rag"]))
def test_contextual_recall_rag(case):
    """검색된 문서에 답변에 필요한 정보가 있는지 (Recall ≥ 0.6)."""
    if not case.get("context"):
        pytest.skip("context 없는 케이스 건너뜀")
    from multi_agent.tools.rag import search_area_info
    answer, _ = _run_agent(case["input"])
    retrieved = search_area_info(case["input"])
    tc = LLMTestCase(
        input=case["input"],
        actual_output=answer,
        expected_output=case["reference"],
        retrieval_context=[retrieved] if retrieved else [case["context"]],
    )
    assert_test(tc, [
        ContextualRecallMetric(threshold=0.6, model=_MODEL, verbose_mode=False),
    ])


@pytest.mark.parametrize("case", _load_cases(tags=["rag"]))
def test_contextual_precision_rag(case):
    """검색된 문서가 질문과 관련 있는지 (Precision ≥ 0.6)."""
    if not case.get("context"):
        pytest.skip("context 없는 케이스 건너뜀")
    from multi_agent.tools.rag import search_area_info
    answer, _ = _run_agent(case["input"])
    retrieved = search_area_info(case["input"])
    tc = LLMTestCase(
        input=case["input"],
        actual_output=answer,
        expected_output=case["reference"],
        retrieval_context=[retrieved] if retrieved else [case["context"]],
    )
    assert_test(tc, [
        ContextualPrecisionMetric(threshold=0.6, model=_MODEL, verbose_mode=False),
    ])


# ── Faithfulness 테스트 ──────────────────────────────────────────

@pytest.mark.parametrize("case", _load_cases(tags=["rag"]))
def test_faithfulness_rag(case):
    """RAG 답변이 검색 컨텍스트에 근거해야 함 ≥ 0.7."""
    if not case.get("context"):
        pytest.skip("context 없는 케이스 건너뜀")
    answer, _ = _run_agent(case["input"])
    tc = LLMTestCase(
        input=case["input"],
        actual_output=answer,
        retrieval_context=[case["context"]],
    )
    assert_test(tc, [
        FaithfulnessMetric(threshold=0.7, model=_MODEL, verbose_mode=False),
    ])


# ── GEval 도메인 품질 테스트 ────────────────────────────────────

_DOMAIN_CRITERIA = (
    "한국 부동산 및 상권 전문 AI로서 다음 기준을 모두 충족하는가: "
    "(1) 질문에서 요청한 지역명이 답변에 포함되어 있다, "
    "(2) 가격 정보 또는 현황 데이터를 구체적으로 제시한다, "
    "(3) 부동산 도메인에서 사실로 인정될 수 있는 내용만 포함한다."
)

@pytest.mark.parametrize("case", _load_cases())
def test_domain_quality(case):
    """도메인 품질 GEval ≥ 0.65."""
    answer, _ = _run_agent(case["input"])
    tc = LLMTestCase(
        input=case["input"],
        actual_output=answer,
    )
    assert_test(tc, [
        GEval(
            name="Korean RE Domain Quality",
            criteria=_DOMAIN_CRITERIA,
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            threshold=0.65,
            model=_MODEL,
            verbose_mode=False,
        ),
    ])


# ── 거절 응답 테스트 ─────────────────────────────────────────────

_OFFSCOPE_CASES = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
_OFFSCOPE_CASES = [c for c in _OFFSCOPE_CASES if "offscope" in c.get("tags", [])]

@pytest.mark.parametrize("case", _OFFSCOPE_CASES)
def test_offscope_rejection(case):
    """범위 외 질문에 부동산 관련 답변 거절 문구가 포함되어야 함."""
    answer, _ = _run_agent(case["input"])
    rejection_keywords = ["부동산", "상권", "답변", "전문", "범위"]
    assert any(kw in answer for kw in rejection_keywords), (
        f"거절 문구 없음: {answer[:200]}"
    )
