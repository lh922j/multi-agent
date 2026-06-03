"""
Swarm 통합 테스트 — 실제 LLM 호출, OpenAI API 키 필요.
실행: pytest tests/test_team.py -v -s
"""
import asyncio
import pytest

from multi_agent.team import run_chat, clear_history


@pytest.fixture(autouse=True)
def cleanup():
    yield
    clear_history("test-session")


class TestRunChat:
    def test_data_query_trade(self):
        answer, map_points = asyncio.run(
            run_chat("역삼동 84㎡ 아파트 최근 매매 시세 알려줘", "test-session")
        )
        assert isinstance(answer, str)
        assert len(answer) > 10

    def test_returns_map_points_for_trade(self):
        answer, map_points = asyncio.run(
            run_chat("강남구 아파트 매매 실거래 조회해줘", "test-session")
        )
        assert isinstance(map_points, list)

    def test_off_topic_response(self):
        answer, _ = asyncio.run(
            run_chat("오늘 날씨 어때?", "test-session")
        )
        assert isinstance(answer, str)
        assert len(answer) > 0

    def test_multiturn_context(self):
        asyncio.run(run_chat("역삼동 매매 시세 알려줘", "test-session"))
        answer, _ = asyncio.run(run_chat("방금 그 지역 전세도 알려줘", "test-session"))
        assert isinstance(answer, str)
        assert len(answer) > 10
