import json
from loguru import logger
from sqlalchemy import text

from ..db.database import get_engine
from ._district import district_sql_filter

# 사용자 키워드 → DB mid_category/large_category 매핑
_CATEGORY_ALIAS: dict[str, str] = {
    "카페": "비알코올",
    "커피": "비알코올",
    "카페숍": "비알코올",
    "음식점": "음식",
    "식당": "음식",
    "레스토랑": "음식",
    "주점": "주점",
    "술집": "주점",
    "바": "주점",
    "편의점": "편의점",
    "치킨": "닭",
    "패스트푸드": "패스트",
    "빵집": "빵",
    "베이커리": "빵",
    "약국": "약국",
    "병원": "의원",
    "학원": "교육",
}


def query_commercial_data(
    district: str,
    category: str = "",
    top_n: int = 10,
) -> str:
    """
    지역별 상권 현황(업종별 점포 수)을 조회합니다.
    특정 동네나 구의 상권 분포를 파악할 때 사용합니다.

    Args:
        district: 동명 또는 구명 (예: '홍대', '마포구', '역삼동', '작전동')
        category: 업종 키워드 필터 (예: '카페', '음식', '편의점', '한식'. 빈 값이면 전체)
        top_n: 반환 업종 수 (기본 10)
    """
    if not district or not district.strip():
        return "지역 이름이 비어 있습니다."

    district_filter, district_params = district_sql_filter(district, dong_col="dong_name", sgg_col="sgg_code")

    # 사용자 키워드 → DB 카테고리명 변환
    cat_key = _CATEGORY_ALIAS.get(category.strip(), category.strip())

    # commercial_store용 cat_filter (large/mid 만 검색 — small_category 제외하여 오매칭 방지)
    store_cat_filter = ""
    params: dict = {**district_params, "top_n": top_n}
    if cat_key:
        store_cat_filter = (
            "AND (large_category ILIKE :cat_pat "
            "OR mid_category ILIKE :cat_pat)"
        )
        params["cat_pat"] = f"%{cat_key}%"

    # commercial_area용 cat_filter (large_category만 존재)
    area_cat_filter = ""
    if cat_key:
        area_cat_filter = "AND large_category ILIKE :cat_pat"

    try:
        engine = get_engine()
        with engine.connect() as conn:
            # ── 1. commercial_area (집계 테이블) 우선 시도 ──
            area_sql = text(f"""
                SELECT dong_name, large_category, store_count, active_count, open_rate
                FROM commercial_area
                WHERE {district_filter} {area_cat_filter}
                ORDER BY store_count DESC
                LIMIT :top_n
            """)
            area_rows = conn.execute(area_sql, params).fetchall()

            if area_rows:
                lines = [
                    f"[ 상권 분석 — {district} ]",
                    f"{'동명':<12} {'업종':<12} {'전체':>7} {'영업 중':>7} {'영업률':>7}",
                    "-" * 55,
                ]
                for r in area_rows:
                    lines.append(
                        f"{r.dong_name:<12} {r.large_category:<12} "
                        f"{r.store_count:>7,}개 {r.active_count:>7,}개 {r.open_rate:>6.1f}%"
                    )
                text_result = "\n".join(lines)

            else:
                # ── 2. commercial_store 직접 집계 ──
                total_sql = text(f"""
                    SELECT COUNT(*) FROM commercial_store
                    WHERE {district_filter} AND is_active = true {store_cat_filter}
                """)
                total = conn.execute(total_sql, params).scalar() or 0

                if total == 0:
                    hint = f" (업종 키워드: '{category}')" if category.strip() else ""
                    return f"'{district}' 지역의 상권 데이터가 없습니다{hint}."

                group_sql = text(f"""
                    SELECT mid_category, COUNT(*) AS cnt
                    FROM commercial_store
                    WHERE {district_filter} AND is_active = true {store_cat_filter}
                    GROUP BY mid_category
                    ORDER BY cnt DESC
                    LIMIT :top_n
                """)
                group_rows = conn.execute(group_sql, params).fetchall()

                cat_label = f" — {category}" if category.strip() else ""
                lines = [
                    f"[ 상권 현황 — {district}{cat_label} ]",
                    f"총 영업 중 점포: {total:,}개",
                    "",
                    f"{'업종(중분류)':<20} {'점포 수':>8}",
                    "-" * 30,
                ]
                for r in group_rows:
                    lines.append(f"{(r.mid_category or '미분류'):<20} {r.cnt:>8,}개")
                text_result = "\n".join(lines)

            # ── 3. 지도용 점포 좌표 (카테고리 필터 적용) ──
            store_sql = text(f"""
                SELECT store_name, large_category, mid_category, dong_name, latitude, longitude
                FROM commercial_store
                WHERE {district_filter} AND is_active = true {store_cat_filter}
                  AND latitude IS NOT NULL AND longitude IS NOT NULL
                ORDER BY RANDOM()
                LIMIT 10
            """)
            store_rows = conn.execute(store_sql, params).fetchall()

        map_points = [
            {
                "apt_name": r.store_name,
                "dong_name": r.dong_name,
                "area_exclusive": 0,
                "deal_amount": 0,
                "latitude": r.latitude,
                "longitude": r.longitude,
                "type": "commercial",
                "category": r.mid_category or r.large_category,
            }
            for r in store_rows
        ]
        if map_points:
            payload = json.dumps({"map_points": map_points, "text": text_result}, ensure_ascii=False)
            return f"§MAP§{payload}§END§"
        return text_result

    except Exception as e:
        logger.error(f"[query_commercial_data] 오류: {e}")
        return f"조회 오류: {e}"
