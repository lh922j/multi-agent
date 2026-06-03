import json
from loguru import logger
from sqlalchemy import text

from ..db.database import get_engine
from ._district import district_sql_filter


def query_rent_data(
    district: str,
    area_min: float = 0,
    area_max: float = 300,
    rent_type: str = "전체",
    year_from: int = 2024,
    year_to: int = 2026,
    limit: int = 5,
) -> str:
    """
    아파트 전세·월세 임대차 실거래 내역을 조회합니다.
    매매 조회는 query_trade_data를 사용하세요.

    Args:
        district: 동명 또는 구명 (예: '강남구', '역삼동')
        area_min: 전용면적 최솟값 (㎡)
        area_max: 전용면적 최댓값 (㎡)
        rent_type: '전세' / '월세' / '전체'
        year_from: 조회 시작 연도
        year_to: 조회 종료 연도
        limit: 반환 건수 (최대 50)
    """
    if not district or not district.strip():
        return "지역 이름이 비어 있습니다."
    limit = min(limit, 50)

    district_filter, district_params = district_sql_filter(district)
    # JOIN 쿼리용: 테이블 alias 포함 (dong_name ambiguous 방지)
    district_filter_r, _ = district_sql_filter(district, dong_col="r.dong_name", sgg_col="r.sgg_code")

    type_filter = ""
    if rent_type == "전세":
        type_filter = "AND is_jeonse = true"
    elif rent_type == "월세":
        type_filter = "AND is_jeonse = false"

    sql_text = text(f"""
        SELECT apt_name, dong_name, area_exclusive, floor,
               deposit, monthly_rent, is_jeonse, deal_date
        FROM apt_rent
        WHERE {district_filter}
          AND area_exclusive BETWEEN :area_min AND :area_max
          AND deal_year BETWEEN :year_from AND :year_to
          {type_filter}
        ORDER BY deal_date DESC
        LIMIT :limit
    """)
    sql_map = text(f"""
        SELECT r.apt_name, r.dong_name, r.area_exclusive,
               r.deposit, r.is_jeonse,
               g.latitude, g.longitude
        FROM apt_rent r
        LEFT JOIN apt_geocode g ON r.apt_name = g.apt_name AND r.dong_name = g.dong_name
        WHERE {district_filter_r}
          AND r.area_exclusive BETWEEN :area_min AND :area_max
          AND r.deal_year BETWEEN :year_from AND :year_to
          {type_filter}
          AND g.latitude IS NOT NULL
        ORDER BY r.deal_date DESC
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
            return f"'{district}' 지역에서 조건에 맞는 전·월세 거래가 없습니다."

        def _fmt_amt(val: float) -> str:
            eok = val / 10000
            return f"{eok:.1f}억" if eok >= 1 else f"{int(val):,}만원"

        lines = [
            "[ 전세·월세 임대차 실거래 ]",
            f"{'아파트명':<20} {'동명':<10} {'면적':>6} {'유형':>4} {'보증금':>10} {'월세':>8} {'거래일':>12}",
            "-" * 84,
        ]
        for r in text_rows:
            kind = "전세" if r.is_jeonse else "월세"
            monthly = _fmt_amt(r.monthly_rent) if not r.is_jeonse else "-"
            lines.append(
                f"{r.apt_name:<20} {r.dong_name:<10} {r.area_exclusive:>5.1f}㎡ "
                f"{kind:>4} {_fmt_amt(r.deposit):>8} {monthly:>8} {str(r.deal_date):>12}"
            )
        text_result = "\n".join(lines)

        map_points = [
            {
                "apt_name": r.apt_name,
                "dong_name": r.dong_name,
                "area_exclusive": r.area_exclusive,
                "deal_amount": float(r.deposit),
                "latitude": r.latitude,
                "longitude": r.longitude,
                "type": "rent",
            }
            for r in map_rows
        ]
        if map_points:
            payload = json.dumps({"map_points": map_points, "text": text_result}, ensure_ascii=False)
            return f"§MAP§{payload}§END§"
        return text_result

    except Exception as e:
        logger.error(f"[query_rent_data] 오류: {e}")
        return f"조회 오류: {e}"
