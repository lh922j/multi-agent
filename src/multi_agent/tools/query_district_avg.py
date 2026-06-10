import json
from loguru import logger
from sqlalchemy import text

from ..db.database import get_engine
from ._district import _load


def _sgg_code_to_name() -> dict[str, str]:
    """sgg_code → 구이름 역매핑 (전국)."""
    inv: dict[str, str] = {}
    for name, codes in _load().items():
        for c in codes:
            inv[c] = name
    return inv


def _city_prefix(city: str) -> str | None:
    """도시명 → sgg_code 앞 2자리 prefix. 서울=11, 경기=41 등."""
    _MAP = {
        "서울": "11", "서울시": "11", "서울특별시": "11",
        "경기": "41", "경기도": "41",
        "인천": "28", "인천시": "28", "인천광역시": "28",
    }
    return _MAP.get(city.strip())


def query_district_avg_price(
    city: str = "서울",
    base_district: str = "",
    area_min: float = 60,
    area_max: float = 110,
    year_from: int = 2023,
    year_to: int = 2026,
    top_n: int = 5,
) -> str:
    """
    구(區) 단위 평균 매매가를 조회합니다. 두 가지 용도로 사용합니다:

    1. 도시 전체 평균 조회 (base_district 비어 있을 때):
       query_district_avg_price(city="서울") → 서울 전 구별 평균가 표 반환
       예: "서울 아파트 평균 매매가 알려줘"

    2. 유사 가격대 지역 찾기 (base_district 지정):
       query_district_avg_price(city="서울", base_district="마포구", top_n=5)
       → 마포구와 비슷한 평균가를 가진 구 top_n개 반환
       예: "마포구와 비슷한 가격대 지역 5곳 알려줘"

    Args:
        city: 도시명 (서울, 경기, 인천 등)
        base_district: 비교 기준 구이름. 비어 있으면 도시 전체 평균표 반환
        area_min: 전용면적 하한 (㎡), 기본 60
        area_max: 전용면적 상한 (㎡), 기본 110
        year_from: 조회 시작 연도
        year_to: 조회 종료 연도
        top_n: 유사 지역 반환 수 (base_district 지정 시)
    """
    prefix = _city_prefix(city)
    if not prefix:
        return f"'{city}'은 지원하지 않는 도시입니다. (서울, 경기, 인천 지원)"

    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT sgg_code,
                           AVG(deal_amount)  AS avg_price,
                           COUNT(*)          AS cnt
                    FROM   apt_trade
                    WHERE  sgg_code LIKE :prefix
                      AND  area_exclusive BETWEEN :area_min AND :area_max
                      AND  deal_year      BETWEEN :year_from AND :year_to
                    GROUP  BY sgg_code
                    ORDER  BY avg_price DESC
                """),
                {
                    "prefix": f"{prefix}%",
                    "area_min": area_min, "area_max": area_max,
                    "year_from": year_from, "year_to": year_to,
                },
            ).fetchall()
    except Exception as e:
        logger.error(f"[query_district_avg_price] 오류: {e}")
        return f"조회 오류: {e}"

    if not rows:
        return f"'{city}' 지역 데이터가 없습니다."

    code_to_name = _sgg_code_to_name()
    entries = [
        {"name": code_to_name.get(r.sgg_code, r.sgg_code),
         "avg_price": round(r.avg_price),
         "cnt": r.cnt}
        for r in rows
    ]

    # ── 도시 전체 평균표 ──────────────────────────────────────────
    if not base_district.strip():
        total_avg = sum(e["avg_price"] for e in entries) / len(entries)
        lines = [
            f"[ {city} 구별 평균 매매가 ({area_min}~{area_max}㎡ 기준, {year_from}~{year_to}년) ]",
            f"{'구이름':<10} {'평균 매매가':>12} {'거래건수':>8}",
            "-" * 38,
        ]
        for e in entries:
            avg_eok = e["avg_price"] / 10000
            lines.append(f"{e['name']:<10} {avg_eok:>8.1f}억원 {e['cnt']:>8,}건")
        lines.append("-" * 38)
        lines.append(f"{'서울 평균':<10} {total_avg/10000:>8.1f}억원")
        return "\n".join(lines)

    # ── 유사 가격대 지역 찾기 ─────────────────────────────────────
    base = base_district.strip()
    base_entry = next((e for e in entries if base in e["name"]), None)
    if not base_entry:
        return f"'{base}' 데이터가 없습니다. 구이름을 확인하세요 (예: 마포구, 강남구)."

    base_price = base_entry["avg_price"]
    others = [e for e in entries if e["name"] != base_entry["name"]]
    others.sort(key=lambda e: abs(e["avg_price"] - base_price))
    similar = others[:top_n]

    base_eok = base_price / 10000
    lines = [
        f"[ {base} 평균 매매가: {base_eok:.1f}억원 ]",
        f"↓ 유사 가격대 {top_n}개 구 ({area_min}~{area_max}㎡ 기준)",
        "",
        f"{'구이름':<10} {'평균 매매가':>12} {'차이':>10}",
        "-" * 40,
    ]
    for e in similar:
        eok = e["avg_price"] / 10000
        diff = (e["avg_price"] - base_price) / 10000
        sign = "+" if diff >= 0 else ""
        lines.append(f"{e['name']:<10} {eok:>8.1f}억원 {sign}{diff:>6.1f}억원")
    return "\n".join(lines)
