"""
소상공인시장진흥공단 상가(상권)정보 CSV 파일 → PostgreSQL 임포트

파일 위치: multi-agent/data/ 폴더에 넣어두세요.

실행:
    python scripts/import_commercial_csv.py --file data/소상공인시장진흥공단_상가(상권)정보_20260331.csv
"""
import argparse
from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy import text

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from multi_agent.db.database import get_engine, init_db

CHUNK_SIZE = 50_000

# SBIZ CSV 컬럼명 → DB 컬럼명 매핑
COLUMN_MAP = {
    "상호명": "store_name",
    "지점명": "branch_name",
    "상권업종대분류명": "large_category",
    "상권업종중분류명": "mid_category",
    "상권업종소분류명": "small_category",
    "상권업종소분류코드": "industry_code",
    "시군구코드": "sgg_code",
    "행정동명": "dong_name",
    "도로명주소": "address",
    "위도": "latitude",
    "경도": "longitude",
    "개업일자": "open_date",
    "폐업일자": "close_date",
}


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    # 컬럼명 매핑
    df = df.rename(columns=COLUMN_MAP)

    # 필요한 컬럼만 유지
    keep = [v for v in COLUMN_MAP.values() if v in df.columns]
    df = df[keep].copy()

    # 타입 변환
    for col in ("latitude", "longitude"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # is_active: 폐업일자 없으면 영업 중
    if "close_date" in df.columns:
        df["is_active"] = df["close_date"].isna() | (df["close_date"].astype(str).str.strip() == "")
    else:
        df["is_active"] = True

    # sgg_code 앞 5자리만 사용
    if "sgg_code" in df.columns:
        df["sgg_code"] = df["sgg_code"].astype(str).str[:5]

    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        default=None,
        help="특정 CSV 파일 경로. 미지정 시 data/ 폴더의 모든 CSV 파일을 임포트",
    )
    parser.add_argument("--encoding", default="cp949", help="파일 인코딩 (기본: cp949)")
    args = parser.parse_args()

    data_dir = Path(__file__).parents[1] / "data"

    if args.file:
        csv_files = [Path(args.file)]
    else:
        csv_files = sorted(data_dir.glob("*.csv"))

    if not csv_files:
        logger.error(f"CSV 파일 없음: {data_dir}")
        return

    logger.info(f"임포트할 파일 {len(csv_files)}개:")
    for f in csv_files:
        logger.info(f"  - {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")

    init_db()
    engine = get_engine()

    # 기존 데이터 삭제 여부 확인
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM commercial_store")).scalar()
    if count and count > 0:
        logger.warning(f"commercial_store에 기존 데이터 {count:,}건이 있습니다.")
        ans = input("기존 데이터를 삭제하고 새로 임포트할까요? (y/N): ").strip().lower()
        if ans == "y":
            with engine.connect() as conn:
                conn.execute(text("TRUNCATE TABLE commercial_store RESTART IDENTITY"))
                conn.commit()
            logger.info("기존 데이터 삭제 완료")
        else:
            logger.info("기존 데이터 유지, 추가 임포트합니다.")

    # 파일별 청크 단위 임포트
    total = 0
    for file_path in csv_files:
        logger.info(f"\n[{file_path.name}] 임포트 시작...")
        file_total = 0
        for chunk in pd.read_csv(
            file_path,
            encoding=args.encoding,
            chunksize=CHUNK_SIZE,
            low_memory=False,
            dtype=str,
        ):
            df = _clean_df(chunk)
            df.to_sql("commercial_store", engine, if_exists="append", index=False, method="multi")
            file_total += len(df)
            total += len(df)
        logger.info(f"  → {file_total:,}건 완료")

    logger.success(f"상가 데이터 임포트 완료: 총 {total:,}건")

    # 집계 통계 재생성
    logger.info("commercial_area 집계 통계 생성 중...")
    agg_sql = text("""
        INSERT INTO commercial_area
            (sgg_code, dong_name, large_category, store_count, active_count,
             open_rate, close_rate, reference_year, reference_quarter)
        SELECT
            sgg_code, dong_name, large_category,
            COUNT(*) AS store_count,
            SUM(CASE WHEN is_active THEN 1 ELSE 0 END) AS active_count,
            ROUND(SUM(CASE WHEN is_active THEN 1 ELSE 0 END)::numeric / COUNT(*) * 100, 1) AS open_rate,
            ROUND((1 - SUM(CASE WHEN is_active THEN 1 ELSE 0 END)::numeric / COUNT(*)) * 100, 1) AS close_rate,
            2026 AS reference_year,
            1 AS reference_quarter
        FROM commercial_store
        GROUP BY sgg_code, dong_name, large_category
        ON CONFLICT DO NOTHING
    """)
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE commercial_area RESTART IDENTITY"))
        conn.execute(agg_sql)
        conn.commit()
    logger.success("commercial_area 집계 완료")


if __name__ == "__main__":
    main()
