"""
pytest 공통 픽스처 — eval + unit 테스트 공유

사용:
    pytest tests/                          # 전체
    pytest tests/eval/test_system_metrics.py -v   # 시스템 지표만
    deepeval test run tests/eval/test_llm_quality.py  # LLM 품질만
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

GOLDEN_PATH = Path(__file__).parent / "eval" / "golden_set.json"


# ── 골든셋 픽스처 ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def golden_cases() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def golden_cases_by_tag(golden_cases) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for case in golden_cases:
        for tag in case.get("tags", []):
            idx.setdefault(tag, []).append(case)
    return idx


# ── 에이전트 호출 픽스처 ──────────────────────────────────────────

class AgentResult:
    """단일 에이전트 호출 결과."""
    def __init__(self, answer: str, map_points: list[dict], latency_sec: float):
        self.answer = answer
        self.map_points = map_points
        self.latency_sec = latency_sec


@pytest.fixture(scope="session")
def run_agent():
    """에이전트 동기 호출 함수를 픽스처로 제공."""
    from multi_agent.team import run_chat

    def _call(question: str) -> AgentResult:
        thread_id = f"eval-{uuid.uuid4().hex[:8]}"
        t0 = time.perf_counter()
        answer, map_points = asyncio.run(run_chat(question, thread_id))
        latency = time.perf_counter() - t0
        return AgentResult(answer=answer, map_points=map_points, latency_sec=latency)

    return _call


@pytest.fixture(scope="session")
def run_multiturn_agent():
    """멀티턴 에이전트 호출 — 같은 thread_id로 turns를 순서대로 실행."""
    from multi_agent.team import run_chat

    def _call(turns: list[str]) -> AgentResult:
        thread_id = f"eval-mt-{uuid.uuid4().hex[:8]}"
        t0 = time.perf_counter()
        answer, map_points = "", []
        for turn in turns:
            answer, map_points = asyncio.run(run_chat(turn, thread_id))
        latency = time.perf_counter() - t0
        return AgentResult(answer=answer, map_points=map_points, latency_sec=latency)

    return _call


@pytest.fixture(scope="session")
def router_agent():
    """라우팅만 테스트할 때 사용 — OrchestratorAgent 직접 호출."""
    from multi_agent.agents.router import make_router
    from autogen_agentchat.messages import TextMessage

    agent = make_router()

    async def _route(question: str) -> str:
        """라우팅 결과(agent 이름) 반환."""
        resp = await agent.on_messages(
            [TextMessage(content=question, source="user")],
            cancellation_token=None,
        )
        content = resp.chat_message.content if resp.chat_message else ""
        # HandoffMessage → 대상 에이전트 이름 추출
        target = getattr(resp.chat_message, "target", None)
        return target or content

    def _route_sync(question: str) -> str:
        return asyncio.run(_route(question))

    return _route_sync
