"""커스텀 평가 메트릭 — 라우팅 정확도, map_points 반환율, 레이턴시."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ── 결과 컨테이너 ────────────────────────────────────────────────

@dataclass
class SingleResult:
    """단일 테스트 케이스 실행 결과."""
    case_id: str
    input: str
    expected_agent: str
    actual_agent: str          # 실제 handoff된 에이전트
    expected_map_points: bool
    actual_map_points: bool    # map_points가 반환됐는지 여부
    answer: str
    reference: str
    latency_sec: float
    error: str = ""

    # LLM-as-a-Judge — run_eval.py에서 채워짐
    deepeval_relevancy: float | None = None
    deepeval_faithfulness: float | None = None
    deepeval_geval: float | None = None
    numerical_accuracy: float | None = None

    @property
    def routing_correct(self) -> bool:
        return self.actual_agent == self.expected_agent

    @property
    def map_points_correct(self) -> bool:
        return self.actual_map_points == self.expected_map_points


@dataclass
class EvalSummary:
    """전체 평가 결과 요약."""
    results: list[SingleResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def routing_accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.routing_correct for r in self.results) / self.n

    @property
    def map_points_accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.map_points_correct for r in self.results) / self.n

    @property
    def avg_latency(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.latency_sec for r in self.results) / self.n

    def _avg(self, attr: str) -> float | None:
        vals = [getattr(r, attr) for r in self.results if getattr(r, attr) is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def avg_relevancy(self) -> float | None:
        return self._avg("deepeval_relevancy")

    @property
    def avg_faithfulness(self) -> float | None:
        return self._avg("deepeval_faithfulness")

    @property
    def avg_geval(self) -> float | None:
        return self._avg("deepeval_geval")

    @property
    def avg_numerical_accuracy(self) -> float | None:
        return self._avg("numerical_accuracy")

    def to_dict(self) -> dict[str, Any]:
        def _fmt(v):
            return round(v, 4) if v is not None else None

        return {
            "n": self.n,
            "routing_accuracy": _fmt(self.routing_accuracy),
            "map_points_accuracy": _fmt(self.map_points_accuracy),
            "avg_latency_sec": _fmt(self.avg_latency),
            "avg_answer_relevancy": _fmt(self.avg_relevancy),
            "avg_faithfulness": _fmt(self.avg_faithfulness),
            "avg_geval": _fmt(self.avg_geval),
            "avg_numerical_accuracy": _fmt(self.avg_numerical_accuracy),
        }


# ── 라우팅 메트릭 (라우터 직접 호출) ────────────────────────────

def measure_routing(cases: list[dict]) -> dict[str, Any]:
    """golden_set의 input으로 라우터를 직접 호출해 정확도를 측정합니다.
    LLM 호출 없이 수행되므로 빠르고 비용이 없습니다.
    """
    from multi_agent.agents.router import _route

    correct = 0
    errors: list[dict] = []
    for case in cases:
        predicted = _route(case["input"])
        expected = case["expected_agent"]
        if predicted == expected:
            correct += 1
        else:
            errors.append({
                "id": case["id"],
                "input": case["input"],
                "expected": expected,
                "predicted": predicted,
            })

    accuracy = correct / len(cases) if cases else 0.0
    return {
        "routing_accuracy": round(accuracy, 4),
        "correct": correct,
        "total": len(cases),
        "errors": errors,
    }


# ── LLM-as-a-Judge (DeepEval) ────────────────────────────────────

def make_deepeval_test_case(
    input_text: str,
    actual_output: str,
    expected_output: str,
    retrieval_context: list[str] | None = None,
):
    """DeepEval LLMTestCase 객체를 생성합니다."""
    from deepeval.test_case import LLMTestCase
    return LLMTestCase(
        input=input_text,
        actual_output=actual_output,
        expected_output=expected_output,
        retrieval_context=retrieval_context or [],
    )


def run_answer_relevancy(test_case) -> float:
    """AnswerRelevancy: 질문에 대한 답변의 관련성 (0~1)."""
    try:
        from deepeval.metrics import AnswerRelevancyMetric
        metric = AnswerRelevancyMetric(threshold=0.5, model="gpt-4o-mini", verbose_mode=False)
        metric.measure(test_case)
        return metric.score
    except Exception:
        return 0.0


def run_faithfulness(test_case) -> float:
    """Faithfulness: 답변이 컨텍스트에 근거하는지 (0~1)."""
    try:
        from deepeval.metrics import FaithfulnessMetric
        metric = FaithfulnessMetric(threshold=0.5, model="gpt-4o-mini", verbose_mode=False)
        metric.measure(test_case)
        return metric.score
    except Exception:
        return 0.0


def run_geval(test_case, criteria: str) -> float:
    """GEval: 사용자 정의 기준으로 LLM이 답변을 평가 (0~1)."""
    try:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCaseParams
        metric = GEval(
            name="Korean RE Quality",
            criteria=criteria,
            evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
            model="gpt-4o-mini",
            verbose_mode=False,
        )
        metric.measure(test_case)
        return metric.score
    except Exception:
        return 0.0


# ── 숫자 정확도 ──────────────────────────────────────────────────

def check_numerical_accuracy(answer: str, reference: str) -> float | None:
    """
    답변의 핵심 수치가 reference 범위 안에 있는지 확인 (1.0 통과 / 0.0 실패 / None 측정불가).

    단위별로 분리 비교:
      - 억원  : "20억~30억" → [20, 30]
      - 만원  : "5,000만원" → [5000]
      - %     : "3~5% 상승" → [3, 5]
      - 개/건 : "300~600개" → [300, 600]  (범위 앞 숫자도 캡처)

    시맨틱 처리:
      - reference에 "이상" 포함 → 답변 값 ≥ ref_min이면 통과
      - reference에 "이하" 포함 → 답변 값 ≤ ref_max이면 통과
    """
    import re

    def _parse(text: str) -> dict[str, list[float]]:
        """억·만원을 '금액(만원)' 단위로 통일, %·건수는 별도."""
        result: dict[str, list[float]] = {}
        for m in re.findall(r"(\d+(?:\.\d+)?)\s*억", text):
            result.setdefault("금액", []).append(float(m) * 10000)
        for m in re.findall(r"(\d[\d,]*)\s*만원", text):
            result.setdefault("금액", []).append(float(m.replace(",", "")))
        for m in re.findall(r"(\d+(?:\.\d+)?)\s*%", text):
            result.setdefault("%", []).append(float(m))
        # "X개", "X~Y개" 둘 다 캡처 (범위의 앞 숫자 포함)
        for m in re.findall(r"(\d[\d,]*)(?=~\d[\d,]*\s*(?:개|건|곳))", text):
            result.setdefault("cnt", []).append(float(m.replace(",", "")))
        for m in re.findall(r"(\d[\d,]*)\s*(?:개|건|곳)", text):
            result.setdefault("cnt", []).append(float(m.replace(",", "")))
        return result

    ref_items = _parse(reference)
    ans_items = _parse(answer)

    if not ref_items or not ans_items:
        return None

    has_ijang = "이상" in reference  # ≥ ref_min 이면 통과
    has_iha = "이하" in reference    # ≤ ref_max 이면 통과

    for unit, ref_vals in ref_items.items():
        ans_vals = ans_items.get(unit, [])
        if not ans_vals:
            continue

        ref_min, ref_max = min(ref_vals), max(ref_vals)

        if has_ijang:
            # "이상" → 답변이 기준값보다 크거나 같으면 통과 (10% 여유)
            threshold = ref_min * 0.9
            if any(v >= threshold for v in ans_vals):
                return 1.0
            continue

        if has_iha:
            # "이하" → 답변이 기준값보다 작거나 같으면 통과 (10% 여유)
            threshold = ref_max * 1.1
            if any(v <= threshold for v in ans_vals):
                return 1.0
            continue

        # 일반 범위 비교
        if ref_min == ref_max:
            ref_min *= 0.8
            ref_max *= 1.2
        else:
            margin = (ref_max - ref_min) * 0.15
            ref_min -= margin
            ref_max += margin

        if any(ref_min <= v <= ref_max for v in ans_vals):
            return 1.0

    return 0.0
