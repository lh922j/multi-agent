from autogen_agentchat.agents import AssistantAgent
from ._base import make_client
from ..tools import ANOMALY_TOOLS

_PROMPT = """당신은 아파트 이상거래 탐지 전문 에이전트입니다.

## 규칙
- detect_anomaly 도구로 Isolation Forest 기반 이상거래를 탐지합니다.
- contamination 기본값 0.02 (2%)를 사용하세요. 사용자가 별도 요청 시 조정하세요.
- 탐지 완료 후 반드시 ReportAgent에게 handoff하세요.
- 결과 해석은 ReportAgent에게 위임하세요.
"""


def make_anomaly_agent() -> AssistantAgent:
    return AssistantAgent(
        name="AnomalyAgent",
        model_client=make_client(max_tokens=400),
        tools=ANOMALY_TOOLS,
        handoffs=["ReportAgent"],
        system_message=_PROMPT,
    )
