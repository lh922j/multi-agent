"""
학교·학원 CSV → PostgreSQL 임포트

실행:
    python scripts/import_education_csv.py
    python scripts/import_education_csv.py --school-only
    python scripts/import_education_csv.py --academy-only
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from multi_agent.db.database import get_engine
from multi_agent.db.models import Base, SchoolInfo, AcademyInfo

DATA_DIR = Path(__file__).parents[1] / "data"
SCHOOL_CSV = DATA_DIR / "학교기본정보_2026년+4월+30일+기준.csv"
ACADEMY_CSV = DATA_DIR / "학원교습소정보_2026년04월30일기준.csv"

SCHOOL_TYPES = {"초등학교", "중학교", "고등학교"}


def _extract_dong(address: str) -> str:
    """도로명주소에서 동 이름 추출. 예: '서울시 강남구 ... (대치동, ...)' → '대치동'"""
    if not isinstance(address, str):
        return ""
    m = re.search(r'[(\（]([가-힣]{1,6}동)', address)
    if m:
        return m.group(1)
    # 괄호 없이 주소 토큰에서 찾기
    for token in address.split():
        if token.endswith("동") and len(token) >= 2:
            return token
    return ""


def _extract_sgg(address: str) -> str:
    """도로명주소에서 구 이름 추출."""
    if not isinstance(address, str):
        return ""
    m = re.search(r'([가-힣]{1,6}구)\b', address)
    return m.group(1) if m else ""


def import_schools(engine) -> int:
    df = pd.read_csv(SCHOOL_CSV, encoding="cp949")
    df = df[df["학교종류명"].isin(SCHOOL_TYPES)].copy()

    records = []
    for _, row in df.iterrows():
        addr = str(row.get("도로명주소", ""))
        records.append({
            "school_name":    row.get("학교명", ""),
            "school_type":    row.get("학교종류명", ""),
            "sido":           row.get("시도명", ""),
            "sgg_name":       _extract_sgg(addr),
            "dong_name":      _extract_dong(addr),
            "address":        addr,
            "establish_type": row.get("설립명", ""),
            "hs_type":        row.get("고등학교구분명", "") or "",
            "special_type":   row.get("특수목적고등학교계열명", "") or "",
        })

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE school_info RESTART IDENTITY"))
        conn.execute(SchoolInfo.__table__.insert(), records)

    logger.info(f"학교 임포트 완료: {len(records):,}건")
    return len(records)


def import_academies(engine) -> int:
    df = pd.read_csv(ACADEMY_CSV, encoding="cp949")

    records = []
    for _, row in df.iterrows():
        addr = str(row.get("도로명주소", ""))
        records.append({
            "academy_name": str(row.get("학원명", ""))[:200],
            "sgg_name":     str(row.get("행정구역명", ""))[:30],
            "dong_name":    _extract_dong(addr),
            "field":        str(row.get("분야명", ""))[:50],
            "subject":      str(row.get("교습계열명", ""))[:100],
            "address":      addr,
            "capacity":     int(row["정원합계"]) if pd.notna(row.get("정원합계")) else 0,
        })

    # 배치 insert (5000건씩)
    batch = 5000
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE academy_info RESTART IDENTITY"))
        for i in range(0, len(records), batch):
            conn.execute(AcademyInfo.__table__.insert(), records[i:i+batch])
            if (i // batch + 1) % 5 == 0:
                logger.info(f"  진행: {min(i+batch, len(records)):,}/{len(records):,}")

    logger.info(f"학원 임포트 완료: {len(records):,}건")
    return len(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-only", action="store_true")
    parser.add_argument("--academy-only", action="store_true")
    args = parser.parse_args()

    engine = get_engine()
    Base.metadata.create_all(engine)  # 테이블 없으면 생성

    if not args.academy_only:
        import_schools(engine)
    if not args.school_only:
        import_academies(engine)

    logger.info("완료. 다음 단계: python scripts/build_rag_docs.py --top 100")


if __name__ == "__main__":
    main()
