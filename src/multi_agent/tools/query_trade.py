import json
from loguru import logger
from sqlalchemy import text

from ..db.database import get_engine
from ._district import district_sql_filter


def query_trade_data(
    district: str,
    area_min: float = 0,
    area_max: float = 300,
    year_from: int = 2024,
    year_to: int = 2026,
    limit: int = 5,
) -> str:
    """
    아파트 매매(매수·매도) 실거래 내역을 조회합니다.
    전세·월세는 query_rent_data를 사용하세요.

    Args:
        district: 동명 또는 구명 (예: '강남구', '역삼동')
        area_min: 전용면적 최솟값 (㎡)
        area_max: 전용면적 최댓값 (㎡)
        year_from: 조회 시작 연도
        year_to: 조회 종료 연도
        limit: 반환 건수 (최대 50)
    """
    if not district or not district.strip():
        return "지역 이름이 비어 있습니다."
    limit = min(limit, 50)

    district_filter, district_params = district_sql_filter(district)
    # JOIN 쿼리용: 테이블 alias 포함 (dong_name ambiguous 방지)
    district_filter_t, _ = district_sql_filter(district, dong_col="t.dong_name", sgg_col="t.sgg_code")

    sql_text = text(f"""
        SELECT apt_name, dong_name, area_exclusive, floor, deal_amount, deal_date
        FROM apt_trade
        WHERE {district_filter}
          AND area_exclusive BETWEEN :area_min AND :area_max
          AND deal_year BETWEEN :year_from AND :year_to
        ORDER BY deal_date DESC
        LIMIT :limit
    """)
    sql_map = text(f"""
        SELECT t.apt_name, t.dong_name, t.area_exclusive, t.deal_amount,
               g.latitude, g.longitude
        FROM apt_trade t
        LEFT JOIN apt_geocode g ON t.apt_name = g.apt_name AND t.dong_name = g.dong_name
        WHERE {district_filter_t}
          AND t.area_exclusive BETWEEN :area_min AND :area_max
          AND t.deal_year BETWEEN :year_from AND :year_to
          AND g.latitude IS NOT NULL
        ORDER BY t.deal_date DESC
        LIMIT 10
    """)

    params = {
        **district_params,
        "area_min": area_min,
        "area_max": area_max,
        "year_from": year_from,
        "year_to": year_to,
    }
    try:
        engine = get_engine()
        with engine.connect() as conn:
            text_rows = conn.execute(sql_text, {**params, "limit": limit}).fetchall()
            map_rows = conn.execute(sql_map, params).fetchall()

        if not text_rows:
            return f"'{district}' 지역에서 조건에 맞는 매매 거래가 없습니다."

        amounts = [r.deal_amount for r in text_rows]
        avg_eok = sum(amounts) / len(amounts) / 10000
        min_eok = min(amounts) / 10000
        max_eok = max(amounts) / 10000

        lines = [
            "[ 매매 실거래 ]",
            f"▶ 평균 {avg_eok:.1f}억원 | 최저 {min_eok:.1f}억원 | 최고 {max_eok:.1f}억원 (조회 {len(amounts)}건)",
            f"{'아파트명':<20} {'동명':<10} {'면적':>6} {'층':>4} {'매매금액':>10} {'거래일':>12}",
            "-" * 78,
        ]
        for r in text_rows:
            amt_eok = r.deal_amount / 10000
            amt_str = f"{amt_eok:.1f}억" if amt_eok >= 1 else f"{int(r.deal_amount):,}만원"
            lines.append(
                f"{r.apt_name:<20} {r.dong_name:<10} {r.area_exclusive:>5.1f}㎡ "
                f"{r.floor:>3}층 {amt_str:>8} {str(r.deal_date):>12}"
            )
        text_result = "\n".join(lines)

        map_points = [
            {
                "apt_name": r.apt_name,
                "dong_name": r.dong_name,
                "area_exclusive": r.area_exclusive,
                "deal_amount": float(r.deal_amount),
                "latitude": r.latitude,
                "longitude": r.longitude,
                "type": "trade",
            }
            for r in map_rows
        ]
        if map_points:
            payload = json.dumps({"map_points": map_points, "text": text_result}, ensure_ascii=False)
            return f"§MAP§{payload}§END§"
        return text_result

    except Exception as e:
        logger.error(f"[query_trade_data] 오류: {e}")
        return f"조회 오류: {e}"
