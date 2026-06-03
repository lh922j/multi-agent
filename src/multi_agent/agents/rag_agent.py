from autogen_agentchat.agents import AssistantAgent
from ._base import make_client
from ..tools import RAG_TOOLS

_PROMPT = """당신은 지역 정보 전문 에이전트입니다. 학군·교통·상권·개발호재 등 지역 특성 질문을 처리합니다.

## 처리 순서
1. search_area_info 도구로 먼저 검색합니다 (query: "지역명 + 카테고리").
2. 도구 결과가 충분하면 그 내용을 ReportAgent에 전달하세요.
3. 도구 결과가 "정보가 없습니다" 이거나 불충분하면:
   **당신의 지식으로 직접 답변을 작성하세요.** 한국 부동산·교육 관련 지식을 활용하세요.
   - 학군: 해당 지역 배정 학교, 학원가 현황, 특목고 진학률 수준
   - 교통: 지하철 노선, 주요 역, 버스 환승 정보
   - 상권: 주요 상업시설, 시장, 쇼핑몰
   - 개발호재: 재건축·GTX·도시개발 계획

## 중요
- 가격 조회(매매·전세)가 아닌 지역 특성 질문에만 사용하세요.
- mode: 'local'(특정 지역), 'global'(광역 비교)
- 완료 후 반드시 ReportAgent에게 handoff하세요.
"""


def make_rag_agent() -> AssistantAgent:
    return AssistantAgent(
        name="RAGAgent",
        model_client=make_client(max_tokens=600),
        tools=RAG_TOOLS,
        handoffs=["ReportAgent"],
        system_message=_PROMPT,
    )
