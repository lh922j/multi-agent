"""키워드 기반 라우터 — LLM 호출 없이 규칙으로 에이전트를 선택합니다."""
import re
from autogen_agentchat.agents import BaseChatAgent
from autogen_agentchat.base import Response
from autogen_agentchat.messages import HandoffMessage, TextMessage, ChatMessage
from autogen_core import CancellationToken


# ── 라우팅 규칙 ─────────────────────────────────────────────────
# (패턴 목록, 대상 에이전트)  — 위에서부터 첫 번째 매칭 사용
_RULES: list[tuple[list[str], str]] = [
    # 이상거래 탐지
    (["이상거래", "이상 거래", "비정상", "사기", "탐지", "이상한 거래"], "AnomalyAgent"),

    # 가격 예측
    (["예측", "전망", "얼마가 될", "앞으로", "미래 가격", "오를까", "내릴까"], "PredictionAgent"),

    # 지역 특성 (학군·교통·개발호재) — 가격 키워드가 없는 경우
    (["학군", "교통", "지하철", "개발", "호재", "재건축", "재개발",
      "gtx", "GTX", "학교", "교육", "생활권", "입지"], "RAGAgent"),

    # 상권 조회
    (["상권", "카페", "커피", "음식점", "식당", "편의점", "가게",
      "점포", "업종", "영업", "가게 수", "몇 개"], "DataQueryAgent"),

    # 전세·월세
    (["전세", "월세", "임대", "보증금", "렌트", "전·월세", "전월세"], "DataQueryAgent"),

    # 매매·시세 조회 (기본)
    (["매매", "시세", "거래", "실거래", "아파트", "㎡", "평형",
      "근처", "주변", "반경", "역세권"], "DataQueryAgent"),
]

_OFFSCOPE_PATTERNS = re.compile(
    r"날씨|요리|레시피|스포츠|영화|음악|코딩|프로그래밍|주식|암호화폐|코인"
)


def _route(message: str) -> str:
    """메시지를 분석해 적절한 에이전트 이름을 반환합니다."""
    # 범위 외 질문 → ReportAgent가 거부 메시지 처리
    if _OFFSCOPE_PATTERNS.search(message):
        return "ReportAgent"

    msg_lower = message.lower()
    for patterns, target in _RULES:
        if any(p.lower() in msg_lower for p in patterns):
            return target

    # 매칭 없음 → 기본값 DataQueryAgent
    return "DataQueryAgent"


class KeywordRouterAgent(BaseChatAgent):
    """LLM 없이 키워드 규칙으로 handoff를 결정하는 라우터 에이전트."""

    def __init__(self) -> None:
        super().__init__(
            name="OrchestratorAgent",
            description="키워드 기반 라우터. 사용자 질문을 분석해 적절한 에이전트로 handoff합니다.",
        )

    @property
    def produced_message_types(self) -> list[type[ChatMessage]]:
        return [HandoffMessage]

    async def on_messages(
        self,
        messages: list[ChatMessage],
        cancellation_token: CancellationToken,
    ) -> Response:
        # 가장 최근 사용자 메시지 추출
        user_text = ""
        for msg in reversed(messages):
            if isinstance(msg, TextMessage) and msg.source == "user":
                user_text = msg.content
                break

        target = _route(user_text)

        return Response(
            chat_message=HandoffMessage(
                source=self.name,
                target=target,
                content=f"→ {target}",
            )
        )

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        pass


def make_router() -> KeywordRouterAgent:
    return KeywordRouterAgent()
