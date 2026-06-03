"""
DB 데이터로 Vector RAG 입력 문서(.txt) 자동 생성

실행:
    python scripts/build_rag_docs.py
    python scripts/build_rag_docs.py --top 50   # 상위 50개 동만
    python scripts/build_rag_docs.py --sgg 11   # 서울만
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from loguru import logger
from sqlalchemy import text
from multi_agent.db.database import get_engine
from multi_agent.tools._district import _load as _load_codes


def _build_code_to_sgg() -> dict[str, str]:
    """sgg_code → 구/시 이름 역방향 매핑"""
    result = {}
    for name, codes in _load_codes().items():
        for code in codes:
            result[code] = name
    return result


_CODE_TO_SGG = _build_code_to_sgg()

OUTPUT_DIR = Path(__file__).parents[1] / "rag" / "docs"


def get_top_dongs(conn, top_n: int, sgg_prefix: str) -> list[tuple[str, str]]:
    """거래량 기준 상위 동 목록 반환 (dong_name, sgg_code)."""
    sgg_filter = f"AND sgg_code::text LIKE '{sgg_prefix}%'" if sgg_prefix else ""
    rows = conn.execute(text(f"""
        SELECT dong_name, sgg_code::text, COUNT(*) as cnt
        FROM apt_trade
        WHERE dong_name IS NOT NULL AND dong_name != ''
        {sgg_filter}
        GROUP BY dong_name, sgg_code
        ORDER BY cnt DESC
        LIMIT :top_n
    """), {"top_n": top_n}).fetchall()
    return [(r.dong_name, r.sgg_code) for r in rows]


def build_document(conn, dong_name: str, sgg_code: str) -> str:
    """한 동에 대한 부동산·상권 요약 문서 생성."""
    lines = [f"# {dong_name} 부동산·상권 현황 보고서\n"]

    # ── 매매 현황 ──────────────────────────────────────────
    trade = conn.execute(text("""
        SELECT
            COUNT(*) as cnt,
            ROUND(AVG(deal_amount)::numeric, 0) as avg_amt,
            ROUND(MIN(deal_amount)::numeric, 0) as min_amt,
            ROUND(MAX(deal_amount)::numeric, 0) as max_amt,
            ROUND(AVG(area_exclusive)::numeric, 1) as avg_area
        FROM apt_trade
        WHERE dong_name = :dong AND deal_year >= 2020
    """), {"dong": dong_name}).fetchone()

    if trade and trade.cnt:
        avg_eok = trade.avg_amt / 10000
        max_eok = trade.max_amt / 10000
        lines.append("## 아파트 매매 실거래 (2020년~)")
        lines.append(f"- 총 거래 건수: {trade.cnt:,}건")
        lines.append(f"- 평균 매매가: {avg_eok:.1f}억원 ({int(trade.avg_amt):,}만원)")
        lines.append(f"- 최고 매매가: {max_eok:.1f}억원")
        lines.append(f"- 평균 전용면적: {trade.avg_area}㎡\n")

        # 주요 아파트 TOP5
        apts = conn.execute(text("""
            SELECT apt_name, COUNT(*) as cnt,
                   ROUND(AVG(deal_amount)::numeric, 0) as avg_amt
            FROM apt_trade
            WHERE dong_name = :dong AND deal_year >= 2022
            GROUP BY apt_name ORDER BY cnt DESC LIMIT 5
        """), {"dong": dong_name}).fetchall()
        if apts:
            lines.append("### 주요 아파트 단지 (거래량 기준)")
            for a in apts:
                lines.append(f"- {a.apt_name}: 평균 {a.avg_amt/10000:.1f}억 ({a.cnt}건)")
            lines.append("")

        # 연도별 추이
        yearly = conn.execute(text("""
            SELECT deal_year,
                   COUNT(*) as cnt,
                   ROUND(AVG(deal_amount)::numeric, 0) as avg_amt
            FROM apt_trade
            WHERE dong_name = :dong AND deal_year >= 2021
            GROUP BY deal_year ORDER BY deal_year
        """), {"dong": dong_name}).fetchall()
        if yearly:
            lines.append("### 연도별 매매 추이")
            for y in yearly:
                lines.append(f"- {y.deal_year}년: {y.cnt}건, 평균 {y.avg_amt/10000:.1f}억")
            lines.append("")

    # ── 전세·월세 현황 ──────────────────────────────────────
    rent = conn.execute(text("""
        SELECT
            SUM(CASE WHEN is_jeonse THEN 1 ELSE 0 END) as jeonse_cnt,
            SUM(CASE WHEN NOT is_jeonse THEN 1 ELSE 0 END) as wolse_cnt,
            ROUND(AVG(CASE WHEN is_jeonse THEN deposit END)::numeric, 0) as avg_jeonse,
            ROUND(AVG(CASE WHEN NOT is_jeonse THEN deposit END)::numeric, 0) as avg_wolse_dep,
            ROUND(AVG(CASE WHEN NOT is_jeonse THEN monthly_rent END)::numeric, 0) as avg_wolse_rent
        FROM apt_rent
        WHERE dong_name = :dong AND deal_year >= 2022
    """), {"dong": dong_name}).fetchone()

    if rent and (rent.jeonse_cnt or rent.wolse_cnt):
        lines.append("## 전세·월세 현황 (2022년~)")
        if rent.jeonse_cnt:
            lines.append(f"- 전세 거래: {rent.jeonse_cnt:,}건, 평균 보증금 {rent.avg_jeonse/10000:.1f}억")
        if rent.wolse_cnt:
            lines.append(f"- 월세 거래: {rent.wolse_cnt:,}건, 평균 보증금 {rent.avg_wolse_dep/10000:.1f}억 / 월 {int(rent.avg_wolse_rent):,}만원")
        lines.append("")

    # ── 상권 현황 ──────────────────────────────────────────
    comm_total = conn.execute(text("""
        SELECT COUNT(*) FROM commercial_store
        WHERE dong_name = :dong AND is_active = true
    """), {"dong": dong_name}).scalar()

    if comm_total:
        lines.append("## 상권 현황")
        lines.append(f"- 총 영업 중 점포: {comm_total:,}개\n")

        categories = conn.execute(text("""
            SELECT large_category, mid_category, COUNT(*) as cnt
            FROM commercial_store
            WHERE dong_name = :dong AND is_active = true
            GROUP BY large_category, mid_category
            ORDER BY cnt DESC LIMIT 10
        """), {"dong": dong_name}).fetchall()

        if categories:
            lines.append("### 주요 업종 분포")
            for c in categories:
                lines.append(f"- {c.large_category} > {c.mid_category}: {c.cnt:,}개")
            lines.append("")

    # ── 학군 현황 ──────────────────────────────────────────
    # sgg_code → 구 이름 역방향 매핑으로 구 이름 조회
    sgg_name = _CODE_TO_SGG.get(sgg_code, "")

    schools = []
    academies = []
    if sgg_name:
        schools = conn.execute(text("""
            SELECT school_type, school_name, hs_type, special_type
            FROM school_info
            WHERE sgg_name = :sgg
            ORDER BY school_type, school_name
        """), {"sgg": sgg_name}).fetchall()

        academies = conn.execute(text("""
            SELECT field, subject, COUNT(*) as cnt
            FROM academy_info
            WHERE sgg_name = :sgg
            GROUP BY field, subject
            ORDER BY cnt DESC
            LIMIT 8
        """), {"sgg": sgg_name}).fetchall()

    if schools or academies:
        lines.append("## 학군 현황")

    if schools:
        elem = [s.school_name for s in schools if s.school_type == "초등학교"]
        mid  = [s.school_name for s in schools if s.school_type == "중학교"]
        high = [s.school_name for s in schools if s.school_type == "고등학교"]
        specials = [f"{s.school_name}({s.special_type})" for s in schools
                    if s.hs_type == "특수목적고" and s.special_type]

        if elem:
            lines.append(f"- 초등학교: {len(elem)}개 ({', '.join(elem[:5])}{'...' if len(elem)>5 else ''})")
        if mid:
            lines.append(f"- 중학교: {len(mid)}개 ({', '.join(mid[:5])}{'...' if len(mid)>5 else ''})")
        if high:
            lines.append(f"- 고등학교: {len(high)}개 ({', '.join(high[:5])}{'...' if len(high)>5 else ''})")
        if specials:
            lines.append(f"- 특수목적고: {', '.join(specials)}")
        lines.append("")

    if academies:
        lines.append("### 학원·교습소 현황")
        for a in academies:
            lines.append(f"- {a.field} ({a.subject}): {a.cnt:,}개")
        lines.append("")

    # ── 교통 현황 ──────────────────────────────────────────
    centroid = conn.execute(text("""
        SELECT AVG(latitude) as lat, AVG(longitude) as lon
        FROM apt_geocode WHERE dong_name = :dong
    """), {"dong": dong_name}).fetchone()

    if centroid and centroid.lat:
        lat, lon = centroid.lat, centroid.lon

        # Haversine 상수: 2 * R = 2 * 6371000 m
        haversine_expr = """
            2 * 6371000 * asin(sqrt(
                power(sin(radians(latitude - :lat) / 2), 2) +
                cos(radians(:lat)) * cos(radians(latitude)) *
                power(sin(radians(longitude - :lon) / 2), 2)
            ))
        """

        stations = conn.execute(text(f"""
            SELECT station_name, line,
                   round(({haversine_expr})::numeric, 0) as dist_m
            FROM subway_station
            WHERE ({haversine_expr}) <= 2000
            ORDER BY dist_m LIMIT 5
        """), {"lat": lat, "lon": lon}).fetchall()

        bus_cnt = conn.execute(text(f"""
            SELECT COUNT(*) FROM bus_stop
            WHERE ({haversine_expr}) <= 1000
        """), {"lat": lat, "lon": lon}).scalar() or 0

        if stations or bus_cnt:
            lines.append("## 교통 현황")
            if stations:
                station_strs = [f"{s.station_name}역({s.line}호선, {int(s.dist_m):,}m)"
                                for s in stations]
                lines.append(f"- 인근 지하철역 (2km 이내): {', '.join(station_strs)}")
            if bus_cnt:
                lines.append(f"- 버스정류장: {bus_cnt:,}개 (1km 이내)")
            lines.append("")

    if len(lines) <= 2:
        return ""

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=100, help="생성할 동 수 (기본 100)")
    parser.add_argument("--sgg", type=str, default="", help="sgg_code 앞자리 필터 (예: 11=서울, 28=인천)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_engine()

    with engine.connect() as conn:
        dongs = get_top_dongs(conn, args.top, args.sgg)
        logger.info(f"대상 동 수: {len(dongs)}개")

        success, skip = 0, 0
        for dong_name, sgg_code in dongs:
            try:
                doc = build_document(conn, dong_name, sgg_code)
                if not doc:
                    skip += 1
                    continue
                safe_name = dong_name.replace("/", "_").replace(" ", "_")
                out_path = OUTPUT_DIR / f"{safe_name}.txt"
                out_path.write_text(doc, encoding="utf-8")
                success += 1
                if success % 10 == 0:
                    logger.info(f"진행: {success}/{len(dongs)}")
            except Exception as e:
                logger.error(f"[{dong_name}] 오류: {e}")
                skip += 1

    logger.info(f"완료: {success}개 생성, {skip}개 건너뜀")
    logger.info(f"출력 경로: {OUTPUT_DIR}")
    logger.info("\n다음 단계:")
    logger.info("  python scripts/build_vector_index.py")


if __name__ == "__main__":
    main()
