from loguru import logger
from sqlalchemy import text
import pandas as pd

from ..db.database import get_engine
from ._district import district_sql_filter


def detect_anomaly(
    district: str,
    area_min: float = 0,
    area_max: float = 300,
    year_from: int = 2020,
    year_to: int = 2026,
    contamination: float = 0.02,
) -> str:
    """
    지역 아파트 매매 거래 중 이상거래(비정상 가격)를 탐지합니다.
    Isolation Forest 알고리즘을 사용합니다.

    Args:
        district: 동명 또는 구명 (예: '강남구', '역삼동')
        area_min: 전용면적 최솟값 (㎡)
        area_max: 전용면적 최댓값 (㎡)
        year_from: 분석 시작 연도
        year_to: 분석 종료 연도
        contamination: 이상치 비율 (기본 0.02 = 2%)
    """
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    district_filter, district_params = district_sql_filter(district, dong_col="t.dong_name", sgg_col="t.sgg_code")
    sql = text(f"""
        SELECT t.apt_name, t.dong_name, t.area_exclusive, t.floor,
               t.deal_amount, t.deal_date, t.build_year,
               t.deal_year, t.deal_month, t.dealing_type,
               g.latitude, g.longitude
        FROM apt_trade t
        LEFT JOIN apt_geocode g ON t.apt_name = g.apt_name AND t.dong_name = g.dong_name
        WHERE {district_filter}
          AND t.area_exclusive BETWEEN :area_min AND :area_max
          AND t.deal_year BETWEEN :year_from AND :year_to
        ORDER BY t.deal_date DESC
    """)

    try:
        engine = get_engine()
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={
                **district_params,
                "area_min": area_min, "area_max": area_max,
                "year_from": year_from, "year_to": year_to,
            })

        if len(df) < 20:
            return f"'{district}' 지역의 데이터가 부족합니다 (최소 20건 필요, 현재 {len(df)}건)."

        df["price_per_sqm"] = df["deal_amount"] / df["area_exclusive"]
        df["building_age"] = 2025 - df["build_year"].fillna(2000)

        features = ["deal_amount", "price_per_sqm", "area_exclusive", "floor",
                    "building_age", "deal_year", "deal_month"]
        if df["latitude"].notna().sum() > len(df) * 0.5:
            features += ["latitude", "longitude"]

        X = df[features].fillna(df[features].median())
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        clf = IsolationForest(contamination=contamination, random_state=42, n_jobs=1)
        df["anomaly_score"] = -clf.fit_predict(X_scaled)
        df["is_anomaly"] = clf.predict(X_scaled) == -1

        anomalies = df[df["is_anomaly"]].sort_values("price_per_sqm", ascending=False).head(10)
        total = len(df)
        anom_count = int(df["is_anomaly"].sum())

        # 직거래 비율 집계
        direct_total = int((df["dealing_type"] == "직거래").sum())
        direct_anomaly = int((anomalies["dealing_type"] == "직거래").sum())
        direct_ratio_total = direct_total / total * 100 if total else 0
        direct_ratio_anomaly = direct_anomaly / anom_count * 100 if anom_count else 0

        lines = [
            f"[ 이상거래 탐지 — {district} ]",
            f"분석 건수: {total:,}건 / 이상 거래: {anom_count}건 ({anom_count / total * 100:.1f}%)",
            f"직거래 비율: 전체 {direct_ratio_total:.1f}% / 이상거래 중 {direct_ratio_anomaly:.1f}%",
            "",
            f"{'아파트명':<20} {'동명':<10} {'면적':>6} {'층':>4} {'매매금액':>12} {'㎡당 가격':>10} {'거래유형':>8} {'거래일':>12}",
            "-" * 95,
        ]
        for _, r in anomalies.iterrows():
            lines.append(
                f"{r['apt_name']:<20} {r['dong_name']:<10} {r['area_exclusive']:>5.1f}㎡ "
                f"{int(r['floor']):>3}층 {int(r['deal_amount']):>10,}만원 "
                f"{int(r['price_per_sqm']):>8,}만원/㎡ {str(r.get('dealing_type', '')):>8} {str(r['deal_date']):>12}"
            )
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[detect_anomaly] 오류: {e}")
        return f"이상거래 탐지 오류: {e}"


def query_direct_trade_ratio(
    district: str = "",
    top_n: int = 10,
    year_from: int = 2020,
    year_to: int = 2026,
) -> str:
    """
    직거래 비율이 높은 지역(구/동)을 조회합니다.
    dealing_type = '직거래' 기준으로 집계합니다.

    Args:
        district: 구/동 이름 필터 (예: '강남구', '역삼동'). 빈 문자열이면 전체 조회
        top_n: 상위 몇 개 지역을 반환할지 (기본 10)
        year_from: 분석 시작 연도
        year_to: 분석 종료 연도
    """
    district_filter, district_params = ("1=1", {})
    if district:
        district_filter, district_params = district_sql_filter(district, dong_col="dong_name", sgg_col="sgg_code")

    sql = text(f"""
        SELECT dong_name,
               COUNT(*) AS total,
               SUM(CASE WHEN dealing_type = '직거래' THEN 1 ELSE 0 END) AS direct_count,
               ROUND(
                   SUM(CASE WHEN dealing_type = '직거래' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1
               ) AS direct_ratio
        FROM apt_trade
        WHERE deal_year BETWEEN :year_from AND :year_to
          AND dealing_type IN ('직거래', '중개거래')
          AND {district_filter}
        GROUP BY dong_name
        HAVING COUNT(*) >= 30
        ORDER BY direct_ratio DESC
        LIMIT :top_n
    """)
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(sql, {"year_from": year_from, "year_to": year_to, "top_n": top_n, **district_params})
            rows = result.fetchall()

        if not rows:
            return f"직거래 비율 데이터가 없습니다. (지역: {district or '전체'})"

        label = f"{district} " if district else ""
        lines = [
            f"[ {label}직거래 비율 상위 {top_n}개 지역 ({year_from}~{year_to}) ]",
            "",
            f"{'지역':<15} {'전체 거래':>8} {'직거래':>8} {'직거래 비율':>10}",
            "-" * 46,
        ]
        for dong, total, direct, ratio in rows:
            lines.append(f"{dong:<15} {total:>8,}건 {direct:>8,}건 {ratio:>9.1f}%")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[query_direct_trade_ratio] 오류: {e}")
        return f"직거래 비율 조회 오류: {e}"
