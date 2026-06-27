"""
PostgreSQL commercial_area / commercial_store → *_상권.txt 생성

실행:
    python scripts/build_commercial_docs.py
"""
import sys
from pathlib import Path
from collections import defaultdict

from loguru import logger

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

OUTPUT_DIR = Path(__file__).parents[1] / "rag" / "docs"


def extract_gu(address: str) -> str | None:
    """주소에서 구/시 이름 추출. '서울특별시 마포구 ...' → '마포구'"""
    if not address:
        return None
    parts = address.split()
    for part in parts:
        if part.endswith("구") or part.endswith("시") or part.endswith("군"):
            if len(part) >= 3:
                return part
    return None


def build_commercial_docs() -> None:
    from multi_agent.db.database import get_engine
    from sqlalchemy import text

    engine = get_engine()

    with engine.connect() as conn:
        # sgg_code → gu_name 매핑 (주소에서 추출)
        r = conn.execute(text("""
            SELECT DISTINCT sgg_code, address
            FROM commercial_store
            WHERE address IS NOT NULL AND address != ''
            ORDER BY sgg_code
        """))
        sgg_to_gu: dict[str, str] = {}
        for sgg_code, address in r:
            if sgg_code not in sgg_to_gu:
                gu = extract_gu(address)
                if gu:
                    sgg_to_gu[sgg_code] = gu

        logger.info(f"구 매핑 완료: {len(sgg_to_gu)}개 sgg_code")

        # gu별 commercial_area 집계
        r = conn.execute(text("""
            SELECT sgg_code, dong_name, large_category,
                   SUM(active_count) as active,
                   SUM(store_count) as total
            FROM commercial_area
            GROUP BY sgg_code, dong_name, large_category
            ORDER BY sgg_code, active DESC
        """))
        rows = r.fetchall()

    # gu → dong → category → count 구조
    gu_data: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for sgg_code, dong_name, large_cat, active, total in rows:
        gu = sgg_to_gu.get(sgg_code)
        if not gu:
            continue
        gu_data[gu][dong_name][large_cat] += active or 0

    generated = 0
    for gu_name, dong_map in gu_data.items():
        txt = _format_doc(gu_name, dong_map)
        out_path = OUTPUT_DIR / f"{gu_name}_상권.txt"
        out_path.write_text(txt, encoding="utf-8")
        generated += 1

    logger.info(f"상권 txt 생성 완료: {generated}개 → {OUTPUT_DIR}")


def _format_doc(gu_name: str, dong_map: dict) -> str:
    """구 단위 상권 현황을 섹션 청킹용 마크다운으로 포맷."""
    # 전체 업종 집계
    category_total: dict[str, int] = defaultdict(int)
    for dong, cats in dong_map.items():
        for cat, cnt in cats.items():
            category_total[cat] += cnt

    total_active = sum(category_total.values())

    lines = [f"# {gu_name} 상권 현황", ""]

    # 업종별 현황 섹션
    lines += ["## 업종별 현황", f"총 영업 중 점포 수: {total_active:,}개", ""]
    for cat, cnt in sorted(category_total.items(), key=lambda x: -x[1]):
        lines.append(f"- {cat}: {cnt:,}개")
    lines.append("")

    # 주요 동별 상권 섹션
    lines.append("## 주요 동별 상권")
    # 활성 점포 합계 기준 상위 10개 동
    dong_totals = {d: sum(cats.values()) for d, cats in dong_map.items()}
    top_dongs = sorted(dong_totals.items(), key=lambda x: -x[1])[:10]

    for dong, dong_total in top_dongs:
        lines += ["", f"### {dong} ({dong_total:,}개 점포)"]
        cats = dong_map[dong]
        for cat, cnt in sorted(cats.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"- {cat}: {cnt:,}개")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    build_commercial_docs()
