"""
GEval criteria 타당성 검증 — 인간 점수 vs GEval 점수 상관관계 분석.

사용법:
    python tests/eval/geval_correlation.py                          # 최신 full 결과 자동 선택
    python tests/eval/geval_correlation.py --result <경로>          # 특정 결과 파일 지정
    python tests/eval/geval_correlation.py --plot                   # 산점도 저장

출력:
    - Pearson r  (선형 상관, criteria의 방향성 일치 여부)
    - Spearman ρ (순위 상관, 이상값에 강건)
    - p-value    (유의성)
    - 케이스별 점수 비교 테이블
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_EVAL_DIR = Path(__file__).parent
_RESULTS_DIR = _EVAL_DIR / "results"
_HUMAN_SCORES_PATH = _EVAL_DIR / "human_scores.json"


def _load_human_scores() -> dict[str, float]:
    data = json.loads(_HUMAN_SCORES_PATH.read_text(encoding="utf-8"))
    return {
        entry["id"]: entry["human_score"]
        for entry in data["scores"]
        if entry["human_score"] is not None
    }


def _load_geval_scores(result_path: Path) -> dict[str, float]:
    data = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        d["id"]: d["geval"]
        for d in data["details"]
        if d.get("geval") is not None
    }


def _latest_full_result() -> Path:
    files = sorted(_RESULTS_DIR.glob("eval_full_*.json"))
    if not files:
        sys.exit("결과 파일이 없습니다. python -m tests.eval.run_eval --mode full 을 먼저 실행하세요.")
    return files[-1]


def _pearson(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    if den == 0:
        return 0.0, 1.0
    r = num / den
    # t-통계량으로 p-value 근사 (양측)
    if abs(r) >= 1.0:
        return r, 0.0
    t = r * math.sqrt(n - 2) / math.sqrt(1 - r ** 2)
    # 간단한 p-value 근사 (scipy 없이)
    p = _t_pvalue(abs(t), n - 2)
    return r, p


def _rank(xs: list[float]) -> list[float]:
    sorted_idx = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j < len(xs) - 1 and xs[sorted_idx[j]] == xs[sorted_idx[j + 1]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[sorted_idx[k]] = avg_rank
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> tuple[float, float]:
    return _pearson(_rank(xs), _rank(ys))


def _t_pvalue(t: float, df: int) -> float:
    """Student t 분포 양측 p-value 근사 (Abramowitz & Stegun)."""
    x = df / (df + t * t)
    # regularized incomplete beta 근사
    a, b = df / 2, 0.5
    p_half = _beta_inc(x, a, b) / 2
    return min(2 * p_half, 1.0)


def _beta_inc(x: float, a: float, b: float, max_iter: int = 200) -> float:
    """정규화 불완전 베타 함수 (연분수 근사)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    # Lentz 연분수
    cf = 1.0
    c, d = 1.0, 1 - (a + b) * x / (a + 1)
    d = 1.0 / d if abs(d) > 1e-30 else 1e30
    cf = d
    for m in range(1, max_iter + 1):
        for sign in (1, -1):
            if sign == 1:
                num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
            else:
                num = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
            d = 1 + num * d
            c = 1 + num / c
            d = 1.0 / d if abs(d) > 1e-30 else 1e30
            c = max(c, 1e-30)
            delta = c * d
            cf *= delta
            if abs(delta - 1) < 1e-10:
                break
    return front * cf


def main():
    parser = argparse.ArgumentParser(description="GEval criteria 상관관계 분석")
    parser.add_argument("--result", type=Path, default=None, help="eval_full_*.json 경로")
    parser.add_argument("--plot", action="store_true", help="산점도를 PNG로 저장")
    args = parser.parse_args()

    result_path = args.result or _latest_full_result()
    print(f"결과 파일: {result_path.name}")

    human = _load_human_scores()
    geval = _load_geval_scores(result_path)

    # 공통 케이스만 사용
    common_ids = sorted(set(human) & set(geval))
    if not common_ids:
        sys.exit(
            f"\nhuman_scores.json에 점수가 입력된 케이스가 없습니다.\n"
            f"{_HUMAN_SCORES_PATH} 파일에서 human_score 값을 입력하세요.\n"
            f"(현재 결과 파일에 geval 점수가 있는 케이스: {', '.join(sorted(geval)[:5])} ...)"
        )

    h_vals = [human[i] for i in common_ids]
    g_vals = [geval[i] for i in common_ids]
    n = len(common_ids)

    r_p, p_p = _pearson(h_vals, g_vals)
    r_s, p_s = _spearman(h_vals, g_vals)

    # ── 출력 ──────────────────────────────────────────────────────
    print(f"\n{'=' * 52}")
    print(f"  GEval criteria 타당성 검증 — n={n}건")
    print(f"{'=' * 52}")
    print(f"  Pearson  r = {r_p:+.4f}   p = {p_p:.4f}  {'✅ 유의' if p_p < 0.05 else '⚠️ 비유의 (p≥0.05)'}")
    print(f"  Spearman ρ = {r_s:+.4f}   p = {p_s:.4f}  {'✅ 유의' if p_s < 0.05 else '⚠️ 비유의 (p≥0.05)'}")
    print(f"{'=' * 52}")
    print()

    # 케이스별 비교
    col_w = max(len(i) for i in common_ids)
    header = f"{'id':<{col_w}}  {'human':>6}  {'geval':>6}  {'diff':>6}"
    print(header)
    print("-" * len(header))
    for cid in common_ids:
        h, g = human[cid], geval[cid]
        diff = g - h
        flag = " ←" if abs(diff) >= 0.3 else ""
        print(f"{cid:<{col_w}}  {h:>6.3f}  {g:>6.3f}  {diff:>+6.3f}{flag}")

    # 해석
    print()
    if abs(r_p) >= 0.7 and p_p < 0.05:
        print("해석: criteria 설계가 인간 판단과 강하게 일치합니다. (r ≥ 0.7, p < 0.05)")
    elif abs(r_p) >= 0.4 and p_p < 0.05:
        print("해석: criteria가 어느 정도 인간 판단을 반영하나 개선 여지가 있습니다. (0.4 ≤ r < 0.7)")
    else:
        print("해석: criteria와 인간 판단의 상관관계가 낮습니다. criteria 문구 재검토가 필요합니다.")

    # 산점도
    if args.plot:
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(6, 6))
            ax.scatter(h_vals, g_vals, alpha=0.7)
            for cid, h, g in zip(common_ids, h_vals, g_vals):
                ax.annotate(cid, (h, g), fontsize=7, ha="left", va="bottom")
            ax.set_xlabel("Human Score")
            ax.set_ylabel("GEval Score")
            ax.set_title(f"GEval vs Human  (Pearson r={r_p:.3f}, n={n})")
            ax.plot([0, 1], [0, 1], "k--", alpha=0.3)
            out = _RESULTS_DIR / "geval_correlation.png"
            fig.savefig(out, dpi=150, bbox_inches="tight")
            print(f"\n산점도 저장 → {out}")
        except ImportError:
            print("\n[산점도 생략] matplotlib 미설치: pip install matplotlib")


if __name__ == "__main__":
    main()
