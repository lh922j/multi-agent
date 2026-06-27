"""하이브리드 라우터 — 키워드 고신뢰 매칭 후 fallback에서만 LLM 분류."""
import re
from autogen_agentchat.agents import BaseChatAgent
from autogen_agentchat.base import Response
from autogen_agentchat.messages import HandoffMessage, TextMessage, ChatMessage
from autogen_core import CancellationToken


# ── 라우팅 규칙 ─────────────────────────────────────────────────
_RULES: list[tuple[list[str], str]] = [
    (["이상거래", "이상 거래", "비정상", "사기", "탐지", "이상한 거래", "직거래", "직거래 비율"], "AnomalyAgent"),
    (["예측", "전망", "얼마가 될", "앞으로", "미래 가격", "오를까", "내릴까"], "PredictionAgent"),
    (["비슷한 가격", "같은 가격대", "유사 가격", "가격대", "구별 평균", "평균 매매가", "평균가"], "DataQueryAgent"),
    (["비슷한", "유사한", "유사 지역",
      "학군", "교통", "지하철", "개발", "호재", "재건축", "재개발",
      "gtx", "GTX", "학교", "교육", "생활권", "입지",
      "상권 특성", "지역 특성", "상권 분석", "특성 알려"], "RAGAgent"),
    (["상권", "카페", "커피", "음식점", "식당", "편의점", "가게",
      "점포", "업종", "영업", "가게 수", "몇 개"], "DataQueryAgent"),
    (["전세", "월세", "임대", "보증금", "렌트", "전·월세", "전월세"], "DataQueryAgent"),
    (["매매", "시세", "거래", "실거래", "아파트", "㎡", "평형",
      "근처", "주변", "반경", "역세권"], "DataQueryAgent"),
]

_OFFSCOPE_PATTERNS = re.compile(
    r"날씨|요리|레시피|스포츠|영화|음악|코딩|프로그래밍|주식|암호화폐|코인|비트코인|맛집|여행|관광"
)

_OFFSCOPE_REPLY = (
    "죄송합니다. 저는 부동산 및 상권 분석 전문 AI입니다. "
    "해당 질문은 제 서비스 범위를 벗어납니다. "
    "아파트 시세, 상권 현황, 이상거래 탐지 등 부동산 관련 질문을 도와드릴 수 있습니다."
)


def _route(message: str) -> str:
    """키워드 매칭으로 에이전트를 결정합니다.

    Returns:
        에이전트 이름 | "OFFSCOPE" | "FALLBACK"
    """
    # 도메인 키워드를 먼저 체크 — "날씨 좋은 남향 아파트 시세"처럼
    # offscope 단어가 섞여도 부동산 의도면 도메인 에이전트로 라우팅
    msg_lower = message.lower()
    for patterns, target in _RULES:
        if any(p.lower() in msg_lower for p in patterns):
            return target

    # 도메인 키워드가 없을 때만 offscope 판정
    if _OFFSCOPE_PATTERNS.search(message):
        return "OFFSCOPE"

    return "FALLBACK"


async def _llm_route(message: str) -> str:
    """키워드 매칭 실패 시 LLM으로 의도 분류 (fallback 전용).

    Returns:
        에이전트 이름 | "OFFSCOPE"
    """
    try:
        from openai import AsyncOpenAI
        from ..config import settings

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 부동산 AI의 라우터입니다. 사용자 질문을 분석해 아래 중 하나만 반환하세요.\n\n"
                        "DataQueryAgent: 아파트 매매·전세·월세 시세 조회, 상권·업종 조회, 지역 평균가 비교\n"
                        "PredictionAgent: 아파트 가격 예측, 향후 시세 전망\n"
                        "AnomalyAgent: 이상거래 탐지, 비정상 거래 분석\n"
                        "RAGAgent: 학군, 교통, 개발 호재, 재건축, 지역 특성, 입지 비교\n"
                        "offscope: 부동산과 무관한 질문\n\n"
                        "반드시 위 5가지 중 하나만 출력하세요."
                    ),
                },
                {"role": "user", "content": message},
            ],
            max_tokens=20,
            temperature=0,
        )
        result = resp.choices[0].message.content.strip()
        valid = {"DataQueryAgent", "PredictionAgent", "AnomalyAgent", "RAGAgent", "offscope"}
        return result if result in valid else "offscope"
    except Exception:
        return "offscope"


class KeywordRouterAgent(BaseChatAgent):
    """하이브리드 라우터: 키워드 고신뢰 → fallback 시 LLM 분류."""

    def __init__(self) -> None:
        super().__init__(
            name="OrchestratorAgent",
            description="하이브리드 라우터. 키워드 매칭 후 fallback 시 LLM으로 의도 분류.",
        )

    @property
    def produced_message_types(self) -> list[type[ChatMessage]]:
        return [HandoffMessage, TextMessage]

    async def on_messages(
        self,
        messages: list[ChatMessage],
        cancellation_token: CancellationToken,
    ) -> Response:
        user_text = ""
        for msg in reversed(messages):
            if isinstance(msg, TextMessage) and msg.source == "user":
                user_text = msg.content
                break

        result = _route(user_text)

        # 명시적 offscope → LLM 없이 즉시 거부
        if result == "OFFSCOPE":
            return Response(
                chat_message=TextMessage(
                    source=self.name,
                    content=f"{_OFFSCOPE_REPLY}\nTERMINATE",
                )
            )

        # 키워드 매칭 성공 → handoff
        if result != "FALLBACK":
            return Response(
                chat_message=HandoffMessage(
                    source=self.name,
                    target=result,
                    content=f"→ {result}",
                )
            )

        # fallback → LLM 분류
        llm_result = await _llm_route(user_text)

        if llm_result == "offscope":
            return Response(
                chat_message=TextMessage(
                    source=self.name,
                    content=f"{_OFFSCOPE_REPLY}\nTERMINATE",
                )
            )

        return Response(
            chat_message=HandoffMessage(
                source=self.name,
                target=llm_result,
                content=f"→ {llm_result} (LLM 분류)",
            )
        )

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        pass


def make_router() -> KeywordRouterAgent:
    return KeywordRouterAgent()
