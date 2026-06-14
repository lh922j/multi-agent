"""
멀티에이전트 평가 실행 스크립트.

실행 방법:
    # 라우팅만 (빠름, LLM 비용 없음)
    python -m tests.eval.run_eval --mode routing

    # 전체 평가 (LLM-as-a-Judge)  — API 비용 발생
    python -m tests.eval.run_eval --mode full

    # 특정 케이스만
    python -m tests.eval.run_eval --mode full --ids trade-01,rag-01

출력:
    tests/eval/results/eval_<timestamp>.json  — 상세 결과
    tests/eval/results/eval_<timestamp>.png   — 지표 막대 차트
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_ROOT / "src"))

GOLDEN_PATH = Path(__file__).parent / "golden_set.json"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ── 골든셋 로드 ──────────────────────────────────────────────────

def load_golden_set(ids: list[str] | None = None) -> list[dict]:
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if ids:
        cases = [c for c in cases if c["id"] in ids]
    return cases


# ── 시스템 실행 (실제 멀티에이전트 호출) ────────────────────────

async def _run_case(case: dict) -> tuple[str, list[dict], str, float]:
    """단일 케이스를 멀티에이전트 시스템에 실행합니다.
    멀티턴 케이스(turns 필드 존재)는 모든 turns를 순서대로 실행합니다.
    Returns: (answer, map_points, actual_agent_hint, latency_sec)
    """
    from multi_agent.team import run_chat

    thread_id = f"eval-{case['id']}-{int(time.time())}"
    t0 = time.perf_counter()
    try:
        turns = case.get("turns")
        if turns and len(turns) > 1:
            # 멀티턴: 모든 턴 순서대로 실행, 마지막 답변만 사용
            answer, map_points = "", []
            for turn in turns:
                answer, map_points = await run_chat(turn, thread_id)
        else:
            answer, map_points = await run_chat(case["input"], thread_id)
    except Exception as e:
        return f"ERROR: {e}", [], "ERROR", time.perf_counter() - t0
    latency = time.perf_counter() - t0

    return answer, map_points, "", latency


# ── 단일 케이스 평가 ─────────────────────────────────────────────

async def evaluate_case(case: dict, mode: str) -> "SingleResult":
    from tests.eval.metrics import (
        SingleResult,
        check_numerical_accuracy,
        make_deepeval_test_case,
        run_answer_relevancy, run_faithfulness, run_geval,
    )
    from multi_agent.agents.router import _route

    # 라우팅 (LLM 없이 즉시)
    actual_agent = _route(case["input"])

    if mode == "routing":
        # 라우팅 정확도만 측정
        return SingleResult(
            case_id=case["id"],
            input=case["input"],
            expected_agent=case["expected_agent"],
            actual_agent=actual_agent,
            expected_map_points=case["expected_map_points"],
            actual_map_points=False,
            answer="(skipped)",
            reference=case["reference"],
            latency_sec=0.0,
        )

    # 실제 멀티에이전트 호출
    answer, map_points, _, latency = await _run_case(case)

    result = SingleResult(
        case_id=case["id"],
        input=case["input"],
        expected_agent=case["expected_agent"],
        actual_agent=actual_agent,
        expected_map_points=case["expected_map_points"],
        actual_map_points=len(map_points) > 0,
        answer=answer,
        reference=case["reference"],
        latency_sec=latency,
    )

    if "ERROR" in answer:
        result.error = answer
        return result

    # TERMINATE 태그 제거 후 DeepEval에 전달
    clean_answer = answer.replace("TERMINATE", "").strip()

    # offscope 케이스: 의도적 거부 답변 → relevancy 측정 제외
    is_offscope = case.get("expected_agent") == "OFFSCOPE"

    # 숫자 정확도 (reference에 수치가 있는 케이스)
    _NUM_TAGS = {"trade", "rent", "commercial", "prediction", "anomaly"}
    if case["reference"] and any(t in _NUM_TAGS for t in case.get("tags", [])):
        result.numerical_accuracy = check_numerical_accuracy(clean_answer, case["reference"])

    # LLM-as-a-Judge (DeepEval) — offscope는 건너뜀
    if is_offscope:
        return result

    context = [case["context"]] if case.get("context") else []
    turns = case.get("turns")
    if turns and len(turns) > 1:
        eval_input = "[대화 맥락]\n" + "\n".join(f"사용자: {t}" for t in turns)
    else:
        eval_input = case["input"]
    tc = make_deepeval_test_case(
        input_text=eval_input,
        actual_output=clean_answer,
        expected_output=case["reference"],
        retrieval_context=context,
    )
    result.deepeval_relevancy = run_answer_relevancy(tc)
    if context:
        result.deepeval_faithfulness = run_faithfulness(tc)
    if case.get("criteria"):
        result.deepeval_geval = run_geval(tc, case["criteria"])

    return result


# ── 전체 평가 실행 ───────────────────────────────────────────────

async def run_all(mode: str, ids: list[str] | None) -> "EvalSummary":
    from tests.eval.metrics import EvalSummary

    cases = load_golden_set(ids)
    print(f"\n[Eval] 케이스 수: {len(cases)} | 모드: {mode}\n")

    summary = EvalSummary()
    for i, case in enumerate(cases, 1):
        print(f"  [{i:02d}/{len(cases)}] {case['id']} ...", end=" ", flush=True)
        result = await evaluate_case(case, mode)
        summary.results.append(result)
        status = "✓" if result.routing_correct else "✗"
        print(f"{status}  라우팅={'O' if result.routing_correct else 'X'}  "
              f"레이턴시={result.latency_sec:.1f}s  "
              f"relevancy={result.deepeval_relevancy or '-'}")

    return summary


# ── 결과 저장 + 리포트 ───────────────────────────────────────────

def save_results(summary: "EvalSummary", mode: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"eval_{mode}_{ts}.json"
    out_png  = RESULTS_DIR / f"eval_{mode}_{ts}.png"

    # JSON 저장
    payload = {
        "timestamp": ts,
        "mode": mode,
        "summary": summary.to_dict(),
        "details": [
            {
                "id": r.case_id,
                "input": r.input,
                "expected_agent": r.expected_agent,
                "actual_agent": r.actual_agent,
                "routing_correct": r.routing_correct,
                "map_points_correct": r.map_points_correct,
                "latency_sec": round(r.latency_sec, 2),
                "answer": r.answer,
                "answer_relevancy": r.deepeval_relevancy,
                "faithfulness": r.deepeval_faithfulness,
                "geval": r.deepeval_geval,
                "numerical_accuracy": r.numerical_accuracy,
                "error": r.error,
            }
            for r in summary.results
        ],
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[Eval] 결과 저장 → {out_json}")

    # 콘솔 테이블 출력
    try:
        from tabulate import tabulate
        rows = [
            [r.case_id, "✓" if r.routing_correct else "✗",
             round(r.deepeval_relevancy or 0, 3),
             round(r.deepeval_faithfulness or 0, 3) if r.deepeval_faithfulness else "-",
             round(r.deepeval_geval or 0, 3),
             f"{r.latency_sec:.1f}s"]
            for r in summary.results
        ]
        print("\n" + tabulate(
            rows,
            headers=["ID", "Route", "Relevancy", "Faithfulness", "GEval", "Latency"],
            tablefmt="rounded_outline",
        ))
    except ImportError:
        pass

    # 요약 출력
    s = summary.to_dict()
    print("\n── 요약 ──────────────────────────────────")
    for k, v in s.items():
        print(f"  {k:30s}: {v}")

    # 막대 차트 저장
    if mode == "full":
        _save_chart(summary, out_png)


def _save_chart(summary: "EvalSummary", out_path: Path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        s = summary.to_dict()
        labels = ["Routing\nAccuracy", "Map Points\nAccuracy",
                  "Answer\nRelevancy", "Faithfulness\n(RAG only)", "GEval",
                  "Numerical\nAccuracy"]
        values = [
            s["routing_accuracy"] or 0,
            s["map_points_accuracy"] or 0,
            s["avg_answer_relevancy"] or 0,
            s["avg_faithfulness"] or 0,
            s["avg_geval"] or 0,
            s["avg_numerical_accuracy"] or 0,
        ]
        colors = ["#4472C4", "#4472C4", "#ED7D31", "#ED7D31", "#ED7D31", "#A9D18E"]

        fig, ax = plt.subplots(figsize=(11, 5))
        bars = ax.bar(labels, values, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_ylim(0, 1.1)
        ax.axhline(0.7, color="red", linestyle="--", linewidth=0.8, label="목표 기준 0.7")
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                    f"{val:.2f}", ha="center", va="bottom", fontsize=9)
        ax.set_title("멀티에이전트 평가 지표", fontsize=14, fontweight="bold")
        ax.set_ylabel("Score (0 ~ 1)")
        from matplotlib.patches import Patch
        ax.legend(handles=[
            Patch(color="#4472C4", label="시스템 정확도"),
            Patch(color="#ED7D31", label="LLM-as-a-Judge"),
            Patch(color="#A9D18E", label="숫자 정확도"),
            plt.Line2D([0], [0], color="red", linestyle="--", label="목표 기준 0.7"),
        ], fontsize=9, loc="upper right")
        plt.tight_layout()
        fig.savefig(out_path, dpi=150)
        plt.close()
        print(f"[Eval] 차트 저장 → {out_path}")
    except Exception as e:
        print(f"[Eval] 차트 저장 실패: {e}")


# ── CLI 진입점 ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="멀티에이전트 평가 실행")
    parser.add_argument(
        "--mode", choices=["routing", "full"], default="routing",
        help="routing: 라우팅 정확도만 (빠름) / full: LLM-as-a-Judge 포함",
    )
    parser.add_argument(
        "--ids", type=str, default=None,
        help="실행할 케이스 ID (쉼표 구분). 예: trade-01,rag-01",
    )
    args = parser.parse_args()

    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None

    summary = asyncio.run(run_all(args.mode, ids))
    save_results(summary, args.mode)


if __name__ == "__main__":
    main()
