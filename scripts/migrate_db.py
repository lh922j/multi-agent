"""
SQLite(realestate/) → PostgreSQL 마이그레이션

실행:
    python scripts/migrate_db.py
"""
import sqlite3
from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy import text

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from multi_agent.config import settings
from multi_agent.db.database import get_engine, init_db


CHUNK_SIZE = 5_000


def _migrate_table(sqlite_conn: sqlite3.Connection, table: str, pg_table: str, transform=None):
    logger.info(f"[migrate] {table} → {pg_table} 시작")
    engine = get_engine()
    offset = 0
    total = 0
    while True:
        df = pd.read_sql(f"SELECT * FROM {table} LIMIT {CHUNK_SIZE} OFFSET {offset}", sqlite_conn)
        if df.empty:
            break
        if transform:
            df = transform(df)
        df.to_sql(pg_table, engine, if_exists="append", index=False, method="multi")
        total += len(df)
        offset += CHUNK_SIZE
        logger.info(f"  {pg_table}: {total:,}건 완료")
    logger.success(f"[migrate] {pg_table} 총 {total:,}건 완료")


_TRADE_COLS = ["apt_name", "sgg_code", "dong_name", "area_exclusive", "floor",
               "deal_amount", "deal_date", "deal_year", "deal_month", "build_year", "dealing_type"]

_RENT_COLS  = ["apt_name", "sgg_code", "dong_name", "area_exclusive", "floor",
               "deposit", "monthly_rent", "is_jeonse", "deal_date", "deal_year",
               "deal_month", "build_year"]

_GEO_COLS   = ["apt_name", "dong_name", "latitude", "longitude", "address_full"]


def _transform_trade(df: pd.DataFrame) -> pd.DataFrame:
    if "deal_date" not in df.columns and "deal_year" in df.columns:
        df["deal_date"] = pd.to_datetime(
            df["deal_year"].astype(str) + "-" +
            df["deal_month"].astype(str).str.zfill(2) + "-01"
        ).dt.date
    # PostgreSQL 스키마에 있는 컬럼만 유지
    keep = [c for c in _TRADE_COLS if c in df.columns]
    return df[keep]


def _transform_rent(df: pd.DataFrame) -> pd.DataFrame:
    if "deal_date" not in df.columns and "deal_year" in df.columns:
        df["deal_date"] = pd.to_datetime(
            df["deal_year"].astype(str) + "-" +
            df["deal_month"].astype(str).str.zfill(2) + "-01"
        ).dt.date
    if "is_jeonse" not in df.columns and "monthly_rent" in df.columns:
        df["is_jeonse"] = df["monthly_rent"].fillna(0) == 0
    keep = [c for c in _RENT_COLS if c in df.columns]
    return df[keep]


def _transform_geocode(df: pd.DataFrame) -> pd.DataFrame:
    # SQLite에 address_full 없음 → query_used로 대체
    if "address_full" not in df.columns:
        df["address_full"] = df.get("query_used", "")
    keep = [c for c in _GEO_COLS if c in df.columns]
    return df[keep]


def main():
    sqlite_path = Path(settings.sqlite_db_path)
    if not sqlite_path.exists():
        logger.error(f"SQLite DB 없음: {sqlite_path}")
        return

    logger.info(f"SQLite: {sqlite_path}")
    logger.info(f"PostgreSQL: {settings.database_url}")

    init_db()
    logger.info("PostgreSQL 테이블 생성 완료")

    sqlite_conn = sqlite3.connect(sqlite_path)
    try:
        tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", sqlite_conn)
        logger.info(f"SQLite 테이블 목록: {tables['name'].tolist()}")

        if "apt_trade" in tables["name"].values:
            _migrate_table(sqlite_conn, "apt_trade", "apt_trade", _transform_trade)
        if "apt_rent" in tables["name"].values:
            _migrate_table(sqlite_conn, "apt_rent", "apt_rent", _transform_rent)
        if "apt_geocode" in tables["name"].values:
            _migrate_table(sqlite_conn, "apt_geocode", "apt_geocode", _transform_geocode)
    finally:
        sqlite_conn.close()

    logger.success("마이그레이션 완료")


if __name__ == "__main__":
    main()
