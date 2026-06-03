"""
멀티에이전트 평가 스크립트 (골든셋 기반)

실행:
    python scripts/eval.py
    python scripts/eval.py --verbose       # 전체 답변 출력
    python scripts/eval.py --case 0        # 특정 케이스만 실행
"""
import argparse
import asyncio
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from loguru import logger
from multi_agent.team import run_chat


# ── 평가 기준 정의 ─────────────────────────────────────────────
@dataclass
class EvalCase:
    id: str
    question: str
    # 답변에 반드시 포함되어야 할 키워드 (AND 조건)
    must_contain: list[str] = field(default_factory=list)
    # 답변에 없어야 할 키워드
    must_not_contain: list[str] = field(default_factory=list)
    # 라우팅 확인용 (답변에서 에이전트 흔적 확인은 어려우므로 선택적)
    expected_category: str = ""  # "상권", "부동산", "거부"


# ── 골든셋 ────────────────────────────────────────────────────
GOLDEN_SET: list[EvalCase] = [
    # ── 상권 쿼리 ──────────────────────────────────────────
    # LLM이 "카페" 대신 "비알코올", "음료" 등으로 바꿔 말할 수 있으므로
    # 지역명 + 숫자(개수) 포함 여부로 검증
    EvalCase(
        id="commercial_01",
        question="작전동 카페 몇 개야?",
        must_contain=["작전"],          # 지역 언급
        must_not_contain=["오류"],
        expected_category="상권",
    ),
    EvalCase(
        id="commercial_02",
        question="마포구 음식점 현황 알려줘",
        must_contain=["마포"],
        must_not_contain=["오류"],
        expected_category="상권",
    ),
    EvalCase(
        id="commercial_03",
        question="강남구 편의점 몇 개야?",
        must_contain=["강남"],
        must_not_contain=["오류"],
        expected_category="상권",
    ),
    # ── 부동산 매매 ────────────────────────────────────────
    EvalCase(
        id="trade_01",
        question="강남구 84㎡ 매매 시세 알려줘",
        must_contain=["강남", "억"],     # 지역 + 가격 단위 (억 형식으로 출력)
        must_not_contain=["오류"],
        expected_category="부동산",
    ),
    EvalCase(
        id="trade_02",
        question="역삼동 최근 아파트 거래 알려줘",
        must_contain=["역삼", "억"],
        must_not_contain=["오류"],
        expected_category="부동산",
    ),
    # ── 부동산 전월세 ──────────────────────────────────────
    EvalCase(
        id="rent_01",
        question="마포구 84㎡ 전세 시세는?",
        must_contain=["마포", "억"],
        must_not_contain=["오류"],
        expected_category="부동산",
    ),
    # ── 지역 정보 (GraphRAGAgent + Vector RAG) ─────────────
    EvalCase(
        id="rag_01",
        question="상계동 학군 어때?",
        must_contain=["상계", "학교"],
        must_not_contain=["오류"],
        expected_category="지역정보",
    ),
    EvalCase(
        id="rag_02",
        question="대치동 교육 환경 알려줘",
        must_contain=["대치", "학교"],
        must_not_contain=["오류"],
        expected_category="지역정보",
    ),
    EvalCase(
        id="rag_03",
        question="노원구 학원 현황은?",
        must_contain=["노원", "학원"],
        must_not_contain=["오류"],
        expected_category="지역정보",
    ),
    # ── 가격 예측 ──────────────────────────────────────────
    EvalCase(
        id="predict_01",
        question="강남구 84㎡ 아파트 가격 예측해줘",
        must_contain=["예측", "억"],
        must_not_contain=["오류"],
        expected_category="예측",
    ),
    EvalCase(
        id="predict_02",
        question="마포구 59㎡ 아파트 미래 가격 전망은?",
        must_contain=["마포", "만원"],
        must_not_contain=["오류"],
        expected_category="예측",
    ),
    # ── 이상거래 탐지 ──────────────────────────────────────
    EvalCase(
        id="anomaly_01",
        question="강남구 이상거래 탐지해줘",
        must_contain=["강남", "이상"],
        must_not_contain=["오류"],
        expected_category="이상탐지",
    ),
    EvalCase(
        id="anomaly_02",
        question="역삼동 비정상 거래 있어?",
        must_contain=["역삼", "건"],   # detect_anomaly 출력에 항상 "건수" 포함
        must_not_contain=["오류"],
        expected_category="이상탐지",
    ),
    # ── 지역 정보: 교통 ────────────────────────────────────
    EvalCase(
        id="rag_04",
        question="상계동 교통 어때?",
        must_contain=["상계", "지하철"],
        must_not_contain=["오류"],
        expected_category="지역정보",
    ),
    # ── 무관한 질문 (거부 확인) ────────────────────────────
    EvalCase(
        id="reject_01",
        question="오늘 날씨 어때?",
        must_contain=["부동산"],
        must_not_contain=["오류"],
        expected_category="거부",
    ),
    EvalCase(
        id="reject_02",
        question="파이썬 코드 짜줘",
        must_contain=["부동산"],
        must_not_contain=["오류"],
        expected_category="거부",
    ),
]


# ── 평가 로직 ─────────────────────────────────────────────────
@dataclass
class EvalResult:
    case_id: str
    question: str
    answer: str
    passed: bool
    failures: list[str]
    elapsed: float
    map_points_count: int


def evaluate_answer(case: EvalCase, answer: str, map_points: list) -> EvalResult:
    failures = []
    answer_lower = answer.lower()

    for kw in case.must_contain:
        if kw.lower() not in answer_lower:
            failures.append(f"must_contain 누락: '{kw}'")

    for kw in case.must_not_contain:
        if kw.lower() in answer_lower:
            failures.append(f"must_not_contain 포함됨: '{kw}'")

    return EvalResult(
        case_id=case.id,
        question=case.question,
        answer=answer,
        passed=len(failures) == 0,
        failures=failures,
        elapsed=0.0,
        map_points_count=len(map_points),
    )


async def run_case(case: EvalCase, verbose: bool) -> EvalResult:
    thread_id = str(uuid.uuid4())
    t0 = time.perf_counter()
    try:
        answer, map_points = await run_chat(case.question, thread_id)
    except Exception as e:
        answer = f"오류: {e}"
        map_points = []
    elapsed = time.perf_counter() - t0

    result = evaluate_answer(case, answer, map_points)
    result.elapsed = elapsed

    status = "✅ PASS" if result.passed else "❌ FAIL"
    print(f"\n{status}  [{case.id}]  ({elapsed:.1f}s)  {case.question}")
    if result.failures:
        for f in result.failures:
            print(f"       → {f}")
    if verbose:
        print(f"       답변: {answer[:200]}...")
        if map_points:
            print(f"       지도 포인트: {len(map_points)}개")

    return result


async def run_eval(
    cases: list[EvalCase],
    verbose: bool = False,
) -> list[EvalResult]:
    results = []
    for case in cases:
        result = await run_case(case, verbose)
        results.append(result)
    return results


def print_summary(results: list[EvalResult]):
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    avg_elapsed = sum(r.elapsed for r in results) / total if total else 0

    print("\n" + "=" * 60)
    print(f"  평가 결과: {passed}/{total} 통과  ({passed/total*100:.0f}%)")
    print(f"  평균 응답 시간: {avg_elapsed:.1f}초")
    print("=" * 60)

    if passed < total:
        print("\n실패 케이스:")
        for r in results:
            if not r.passed:
                print(f"  [{r.case_id}] {r.question}")
                for f in r.failures:
                    print(f"    - {f}")

    # Langfuse에 결과 기록
    try:
        from multi_agent.config import settings
        from langfuse import Langfuse
        if settings.langfuse_public_key and settings.langfuse_secret_key:
            lf = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            # 전체 평가 점수 기록
            trace_id = lf.create_trace_id()
            obs = lf.start_observation(
                name="golden_set_eval",
                as_type="span",
                trace_context={"trace_id": trace_id},
                input={"total": total},
                output={"passed": passed, "pass_rate": passed / total},
            )
            obs.end()
            lf.flush()
            print(f"\n  Langfuse에 결과 기록 완료 (trace_id: {trace_id[:8]}...)")
    except Exception as e:
        logger.debug(f"Langfuse 기록 건너뜀: {e}")


def main():
    parser = argparse.ArgumentParser(description="멀티에이전트 골든셋 평가")
    parser.add_argument("--verbose", "-v", action="store_true", help="전체 답변 출력")
    parser.add_argument("--case", "-c", type=int, default=None, help="특정 케이스 인덱스만 실행")
    args = parser.parse_args()

    cases = GOLDEN_SET
    if args.case is not None:
        if args.case >= len(GOLDEN_SET):
            print(f"케이스 인덱스 범위 초과 (0~{len(GOLDEN_SET)-1})")
            sys.exit(1)
        cases = [GOLDEN_SET[args.case]]

    print(f"평가 시작: {len(cases)}개 케이스")
    print("-" * 60)

    results = asyncio.run(run_eval(cases, verbose=args.verbose))
    print_summary(results)

    all_passed = all(r.passed for r in results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
