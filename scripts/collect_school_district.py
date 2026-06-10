"""
학교·학원 데이터 → 구별 학군 RAG 문서 생성

지원 파일:
  - 서울시 학교 기본정보.csv (서울시 열린데이터광장)
  - 서울시 강남구 학원 교습소정보.csv
  - 학교기본정보_2026년+4월+30일+기준.csv (전국)
  - 학원교습소정보_2026년04월30일기준.csv (전국)

실행:
    python scripts/collect_school_district.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

OUTPUT_DIR = Path(__file__).parents[1] / "rag" / "docs"
DATA_DIR   = Path(__file__).parents[1] / "data"

# 학원 분야명 → 학군 관련 키워드
_EDU_FIELDS = {"입시.검정 및 보습", "국제화", "종합(대)", "인문사회(대)"}


def parse_schools(path: Path) -> dict[str, dict]:
    """학교 기본정보 CSV → 구별 학교 현황."""
    try:
        df = pd.read_csv(path, encoding="cp949", on_bad_lines="skip")
    except Exception:
        df = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")

    df.columns = [c.strip() for c in df.columns]
    addr_col = next((c for c in df.columns if "도로명주소" in c and "상세" not in c), None)
    if not addr_col:
        logger.warning(f"[학교] 주소 컬럼 없음: {path.name}")
        return {}

    # 구별, 학교종류별 학교명 set (중복 제거 — 국가 파일은 학과별 행 분리됨)
    by_sgg: dict[str, dict] = defaultdict(lambda: defaultdict(set))
    for _, row in df.iterrows():
        addr = str(row.get(addr_col) or "")
        sgg = ""
        for token in addr.split():
            if token.endswith("구") and len(token) >= 3:
                sgg = token
                break
        if not sgg:
            continue
        kind = str(row.get("학교종류명") or "").strip()
        name = str(row.get("학교명") or "").strip()
        if name:
            by_sgg[sgg][kind].add(name)

    return {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in by_sgg.items()}


def parse_academies(path: Path, sgg_filter: str | None = None) -> dict[str, dict]:
    """학원·교습소 CSV → 구별 학원 현황."""
    try:
        df = pd.read_csv(path, encoding="cp949", on_bad_lines="skip")
    except Exception:
        df = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")

    df.columns = [c.strip() for c in df.columns]

    # 컬럼명 정규화 (파일마다 다를 수 있음)
    sgg_col = next((c for c in df.columns if "행정구역" in c or "시군구" in c or "구명" in c), None)
    field_col = next((c for c in df.columns if "분야명" in c), None)
    name_col = next((c for c in df.columns if "학원명" in c or "교습소명" in c), None)
    status_col = next((c for c in df.columns if "등록상태" in c), None)

    if not sgg_col or not name_col:
        logger.warning(f"[학원] 필수 컬럼 없음: {path.name}")
        return {}

    by_sgg: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for _, row in df.iterrows():
        sgg = str(row.get(sgg_col) or "").strip()
        if not sgg or (sgg_filter and sgg_filter not in sgg):
            continue
        # 등록취소 학원 제외
        if status_col and "취소" in str(row.get(status_col) or ""):
            continue
        field = str(row.get(field_col) or "기타").strip()
        by_sgg[sgg][field] += 1

    return {k: dict(v) for k, v in by_sgg.items()}


def build_school_doc(sgg: str, schools: dict, academies: dict) -> str:
    lines = [
        f"# {sgg} 학군 현황",
        "",
        f"## 학교 현황",
    ]

    total_schools = sum(len(v) for v in schools.values())
    lines.append(f"총 {total_schools}개 학교가 있습니다.")
    lines.append("")

    # 학교 종류별 목록
    for kind in ["초등학교", "중학교", "고등학교", "특수목적고등학교", "각종학교(중)", "외국인학교"]:
        school_list = schools.get(kind, [])
        if school_list:
            lines.append(f"**{kind}** ({len(school_list)}개): {', '.join(school_list[:10])}")
            if len(school_list) > 10:
                lines.append(f"  (외 {len(school_list)-10}개)")
    lines.append("")

    if academies:
        lines.append("## 학원·교습소 현황")
        total_aca = sum(academies.values())
        lines.append(f"총 {total_aca:,}개 학원·교습소가 등록되어 있습니다.")
        lines.append("")
        for field, cnt in sorted(academies.items(), key=lambda x: -x[1]):
            lines.append(f"- **{field}**: {cnt:,}개")
        lines.append("")

        # 입시/보습 비율 계산
        exam_cnt = academies.get("입시.검정 및 보습", 0)
        if exam_cnt and total_aca:
            pct = exam_cnt / total_aca * 100
            lines.append("## 학군 특성 요약")
            lines.append(
                f"{sgg}는 입시·보습 학원 비중이 {pct:.0f}%로, "
                + ("전국 최고 수준의 교육 특구입니다." if pct > 50 else "입시 수요가 높은 지역입니다.")
            )
    lines.append("")

    return "\n".join(lines)


def main():
    # 학교 데이터 로드
    school_by_sgg: dict[str, dict] = {}
    for fname in ["서울시 학교 기본정보.csv", "학교기본정보_2026년+4월+30일+기준.csv"]:
        path = DATA_DIR / fname
        if path.exists():
            logger.info(f"[학교] {fname}")
            for sgg, data in parse_schools(path).items():
                if sgg not in school_by_sgg:
                    school_by_sgg[sgg] = {}
                for kind, names in data.items():
                    existing = set(school_by_sgg[sgg].get(kind, []))
                    school_by_sgg[sgg][kind] = sorted(existing | set(names))

    # 학원 데이터 로드
    academy_by_sgg: dict[str, dict] = {}
    for fname in ["서울시 강남구 학원 교습소정보.csv", "학원교습소정보_2026년04월30일기준.csv"]:
        path = DATA_DIR / fname
        if path.exists():
            logger.info(f"[학원] {fname}")
            for sgg, data in parse_academies(path).items():
                if sgg not in academy_by_sgg:
                    academy_by_sgg[sgg] = {}
                for field, cnt in data.items():
                    academy_by_sgg[sgg][field] = academy_by_sgg[sgg].get(field, 0) + cnt

    # 두 데이터 모두 있는 구만 문서 생성
    all_sgg = set(school_by_sgg) | set(academy_by_sgg)
    if not all_sgg:
        logger.error("처리할 학교/학원 데이터가 없습니다.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for sgg in sorted(all_sgg):
        schools = school_by_sgg.get(sgg, {})
        academies = academy_by_sgg.get(sgg, {})
        if not schools and not academies:
            continue
        doc = build_school_doc(sgg, schools, academies)
        fname = f"{sgg}_학군.txt"
        (OUTPUT_DIR / fname).write_text(doc, encoding="utf-8")
        saved += 1
        logger.debug(f"  {fname} (학교 {sum(len(v) for v in schools.values())}개, 학원 {sum(academies.values())}개)")

    logger.info(f"완료: {saved}개 구 학군 RAG 문서 생성")
    logger.info("다음 단계: python scripts/build_vector_index.py")


if __name__ == "__main__":
    main()
