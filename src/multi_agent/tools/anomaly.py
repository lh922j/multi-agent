from loguru import logger
from sqlalchemy import text
import pandas as pd

from ..db.database import get_engine
from ._district import district_sql_filter


def detect_anomaly(
    district: str,
    area_min: float = 0,
    area_max: float = 300,
    year_from: int = 2022,
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
               t.deal_year, t.deal_month,
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

        lines = [
            f"[ 이상거래 탐지 — {district} ]",
            f"분석 건수: {total:,}건 / 이상 거래: {anom_count}건 ({anom_count / total * 100:.1f}%)",
            "",
            f"{'아파트명':<20} {'동명':<10} {'면적':>6} {'층':>4} {'매매금액':>12} {'㎡당 가격':>10} {'거래일':>12}",
            "-" * 86,
        ]
        for _, r in anomalies.iterrows():
            lines.append(
                f"{r['apt_name']:<20} {r['dong_name']:<10} {r['area_exclusive']:>5.1f}㎡ "
                f"{int(r['floor']):>3}층 {int(r['deal_amount']):>10,}만원 "
                f"{int(r['price_per_sqm']):>8,}만원/㎡ {str(r['deal_date']):>12}"
            )
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[detect_anomaly] 오류: {e}")
        return f"이상거래 탐지 오류: {e}"
