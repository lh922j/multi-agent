from autogen_agentchat.agents import AssistantAgent
from ._base import make_client
from ..tools import ANOMALY_TOOLS

_PROMPT = """당신은 아파트 이상거래 탐지 전문 에이전트입니다.

## 규칙
- detect_anomaly 도구로 Isolation Forest 기반 이상거래를 탐지합니다.
- contamination 기본값 0.02 (2%)를 사용하세요. 사용자가 별도 요청 시 조정하세요.
- 평(坪) 단위 입력 시 × 3.3으로 ㎡ 변환 후 ±5㎡ 범위로 area_min/max 설정
  예: 25평 → area_min=78, area_max=88
- "N평대" 입력 시 해당 10구간 전체를 포괄하도록 변환
  예: 20평대(20~29평) → area_min=66, area_max=96 / 30평대 → area_min=99, area_max=129
- 탐지 완료 후 결과를 바탕으로 직접 한국어 답변을 작성하세요.
- 이상거래로 판정된 건수와 주요 특징(가격 편차, 거래 패턴)을 간결하게 설명하세요.
- 답변 맨 끝에 반드시 [[TERMINATE]]를 단독 줄로 추가하세요.
"""


def make_anomaly_agent() -> AssistantAgent:
    return AssistantAgent(
        name="AnomalyAgent",
        model_client=make_client(max_tokens=500),
        tools=ANOMALY_TOOLS,
        system_message=_PROMPT,
    )
