"""
지하철 역사·버스정류장 CSV → PostgreSQL 임포트

실행:
    python scripts/import_transport_csv.py
    python scripts/import_transport_csv.py --subway-only
    python scripts/import_transport_csv.py --bus-only
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from multi_agent.db.database import get_engine
from multi_agent.db.models import Base, SubwayStation, BusStop

DATA_DIR = Path(__file__).parents[1] / "data"
SUBWAY_CSV = DATA_DIR / "서울교통공사_1_8호선 역사 좌표(위경도) 정보_20250814.csv"
BUS_CSV    = DATA_DIR / "국토교통부_전국 버스정류장 위치정보_20251031.csv"


def import_subway(engine) -> int:
    df = pd.read_csv(SUBWAY_CSV, encoding="cp949")

    records = [
        {
            "line":         str(row["호선"]),
            "station_name": str(row["역명"]),
            "latitude":     float(row["위도"]),
            "longitude":    float(row["경도"]),
        }
        for _, row in df.iterrows()
        if pd.notna(row["위도"]) and pd.notna(row["경도"])
    ]

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE subway_station RESTART IDENTITY"))
        conn.execute(SubwayStation.__table__.insert(), records)

    logger.info(f"지하철 역사 임포트 완료: {len(records):,}건")
    return len(records)


def import_bus(engine) -> int:
    df = pd.read_csv(BUS_CSV, encoding="cp949", low_memory=False)
    df = df.dropna(subset=["위도", "경도"])

    records = []
    batch = 5000
    for _, row in df.iterrows():
        records.append({
            "stop_name": str(row["정류장명"])[:100],
            "city":      str(row.get("도시명", ""))[:50],
            "latitude":  float(row["위도"]),
            "longitude": float(row["경도"]),
        })

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE bus_stop RESTART IDENTITY"))
        for i in range(0, len(records), batch):
            conn.execute(BusStop.__table__.insert(), records[i:i+batch])
            if (i // batch + 1) % 10 == 0:
                logger.info(f"  버스정류장 진행: {min(i+batch, len(records)):,}/{len(records):,}")

    logger.info(f"버스정류장 임포트 완료: {len(records):,}건")
    return len(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subway-only", action="store_true")
    parser.add_argument("--bus-only", action="store_true")
    args = parser.parse_args()

    engine = get_engine()
    Base.metadata.create_all(engine)

    if not args.bus_only:
        import_subway(engine)
    if not args.subway_only:
        import_bus(engine)

    logger.info("완료. 다음 단계: python scripts/build_rag_docs.py --top 200")


if __name__ == "__main__":
    main()
