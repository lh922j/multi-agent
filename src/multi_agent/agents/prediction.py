from autogen_agentchat.agents import AssistantAgent
from ._base import make_client
from ..tools import PREDICTION_TOOLS

_PROMPT = """당신은 아파트 매매 가격 예측 전문 에이전트입니다.

## 예측 절차
1. 위도·경도가 없으면 get_station_coordinates로 좌표를 먼저 조회하세요.
2. district_code는 5자리 sgg_code (예: 강남구='11680', 서초구='11650').
3. predict_price 호출 후 결과를 바탕으로 직접 한국어 답변을 작성하세요.

## 중요 규칙
- 도구 없이 가격을 추측하거나 답변하지 마세요.
- 좌표는 반드시 get_station_coordinates로 조회하세요. 직접 추측 금지.
- 예측 면적·지역명을 첫 문장에 명시하세요.
- 핵심 예측 결과를 간결하게 답변하세요.
- 답변 맨 끝에 반드시 TERMINATE를 단독 줄로 추가하세요.
"""


def make_prediction_agent() -> AssistantAgent:
    return AssistantAgent(
        name="PredictionAgent",
        model_client=make_client(max_tokens=500),
        tools=PREDICTION_TOOLS,
        system_message=_PROMPT,
    )
