"""
재개발·재건축 CSV 파일 → 구별 RAG 문서 생성

지원 파일 형식:
  - 서울시 정비사업 데이터 (서울특별시_*.csv)
  - 인천광역시 도시 및 주거환경 정비사업 추진현황 (인천광역시_*.csv)
  - 공공데이터 API 수집 캐시 (redevelopment_raw.json)

실행:
    python scripts/collect_redevelopment.py
    python scripts/collect_redevelopment.py --input rag/docs  # CSV 탐색 경로 지정
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

OUTPUT_DIR = Path(__file__).parents[1] / "rag" / "docs"
DATA_DIR   = Path(__file__).parents[1] / "data"

STAGE_ORDER = {
    "준공": 9, "이주·철거": 8, "착공": 7,
    "관리처분인가": 6, "관리처분계획인가": 6,
    "사업시행인가": 5, "사업시행계획인가": 5,
    "조합설립인가": 4, "추진위구성": 3, "추진위원회승인": 3,
    "정비구역지정": 2, "기타": 1,
}


def _stage_key(stage: str) -> int:
    s = (stage or "").strip()
    for k, v in STAGE_ORDER.items():
        if k in s:
            return v
    return 0


# ── 서울시 CSV 파싱 ─────────────────────────────────────────────

def parse_seoul(path: Path) -> dict[str, list[dict]]:
    df = pd.read_csv(path, encoding="cp949")
    by_sgg: dict[str, list[dict]] = defaultdict(list)
    for _, row in df.iterrows():
        sgg = str(row.get("시군구명") or "").strip()
        if not sgg:
            continue
        by_sgg[sgg].append({
            "zoneNm":    str(row.get("정비 구역명") or "").strip(),
            "prgrsStpCn": str(row.get("시행단계") or "").strip(),
            "hhCnt":     "",
            "gfa":       str(row.get("정비구역 면적(제곱미터)") or "").replace(",", "").strip(),
            "dsgnYmd":   str(row.get("고시일") or "")[:7],
            "usgRgn":    str(row.get("정비유형") or "").strip(),
            "ctpvNm":    "서울특별시",
        })
    return dict(by_sgg)


# ── 서울시 클린업시스템 XLS 파싱 (구별 사업장목록) ──────────────

def parse_cleanup_xls(path: Path) -> dict[str, list[dict]]:
    """서울시 정비사업 정보마당(클린업시스템) XLS — 구별 사업장목록.
    첫 행이 빈 행이고 두 번째 행이 헤더이므로 header=1로 읽는다.
    """
    df = pd.read_excel(path, header=1)
    df.columns = [str(c).strip() for c in df.columns]

    by_sgg: dict[str, list[dict]] = defaultdict(list)
    for _, row in df.iterrows():
        sgg = str(row.get("자치구") or "").strip()
        if not sgg or sgg == "nan":
            continue
        by_sgg[sgg].append({
            "zoneNm":     str(row.get("사업장명") or "").strip(),
            "prgrsStpCn": str(row.get("진행단계") or "").strip(),
            "hhCnt":      "",
            "gfa":        "",
            "dsgnYmd":    "",
            "usgRgn":     str(row.get("사업구분") or "").strip(),
            "ctpvNm":     "서울특별시",
        })
    return dict(by_sgg)


# ── 인천광역시 CSV 파싱 ─────────────────────────────────────────

def parse_incheon(path: Path) -> dict[str, list[dict]]:
    df = pd.read_csv(path, encoding="cp949")
    df.columns = [c.strip() for c in df.columns]
    by_sgg: dict[str, list[dict]] = defaultdict(list)
    for _, row in df.iterrows():
        sgg = str(row.get("구명") or "").strip()
        if not sgg:
            continue
        by_sgg[f"인천 {sgg}"].append({
            "zoneNm":    str(row.get("구 역 명") or row.get("구역명") or "").strip(),
            "prgrsStpCn": str(row.get("진행단계") or "").strip(),
            "hhCnt":     "",
            "gfa":       str(row.get("면적(제곱미터)") or "").replace(",", "").strip(),
            "dsgnYmd":   "",
            "usgRgn":    str(row.get("사업유형") or "").strip(),
            "ctpvNm":    "인천광역시",
        })
    return dict(by_sgg)


# ── 강남구 XLSX 파싱 (강남구홈페이지 주택건설사업 추진현황) ────────

def parse_gangnam_xlsx(path: Path) -> dict[str, list[dict]]:
    """강남구 주택건설사업 추진현황 XLSX.
    컬럼 레이아웃:
      1=단지명, 2=위치, 4=세대수, 6=구역면적(㎡)
      10=추진위원회승인, 11=조합설립인가, 12=사업시행계획인가
      13=관리처분계획인가, 14=착공신고, 15=준공, 16=추진단계
    """
    df = pd.read_excel(path, header=None, engine="openpyxl")

    records = []
    current_section = "재건축"
    _SECTION_KEYWORDS = {
        "재건축 정비사업": "재건축",
        "소규모주택정비사업": "소규모",
        "시장정비사업": "시장정비",
        "리모델링": "리모델링",
    }
    # 날짜 컬럼으로부터 진행단계 역추정 (추진단계 셀이 비어있을 때)
    _DATE_COLS: list[tuple[str, int]] = [
        ("준공", 15), ("착공신고", 14), ("관리처분계획인가", 13),
        ("사업시행계획인가", 12), ("조합설립인가", 11), ("추진위원회승인", 10),
    ]

    def _safe(val) -> str:
        return str(val).strip() if pd.notna(val) else ""

    for _, row in df.iterrows():
        # 섹션 헤더 감지 (col 0 또는 col 1)
        head = _safe(row[0]) + _safe(row[1])
        for kw, sec in _SECTION_KEYWORDS.items():
            if kw in head:
                current_section = sec
                break

        zone_nm = _safe(row[1])
        if not zone_nm or zone_nm in ("단지명", "No"):
            continue

        stage = _safe(row[16])
        if not stage:
            for stage_name, col_idx in _DATE_COLS:
                val = _safe(row[col_idx])
                if val and val != "nan":
                    stage = stage_name
                    break

        gfa_raw = _safe(row[6]).replace(",", "")
        records.append({
            "zoneNm":     zone_nm,
            "prgrsStpCn": stage,
            "hhCnt":      _safe(row[4]),
            "gfa":        gfa_raw,
            "dsgnYmd":    "",
            "usgRgn":     current_section,
            "ctpvNm":     "서울특별시",
        })

    return {"강남구": records}


# ── API 캐시 JSON 파싱 ──────────────────────────────────────────

def parse_json_cache(path: Path) -> dict[str, list[dict]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    by_sgg: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        sgg = (r.get("sggNm") or "").strip()
        if sgg:
            by_sgg[sgg].append(r)
    return dict(by_sgg)


# ── RAG 문서 생성 ───────────────────────────────────────────────

def build_doc(sgg: str, zones: list[dict]) -> str:
    by_stage: dict[str, list[dict]] = defaultdict(list)
    for z in zones:
        stage = (z.get("prgrsStpCn") or "기타").strip()
        by_stage[stage].append(z)

    sorted_stages = sorted(by_stage.keys(), key=_stage_key, reverse=True)

    lines = [
        f"# {sgg} 재개발·재건축 정비사업 현황",
        "",
        f"총 {len(zones)}개 정비사업 구역이 등록되어 있습니다.",
        "",
        "## 진행단계별 현황",
    ]
    for stage in sorted_stages:
        zlist = by_stage[stage]
        lines.append(f"- **{stage}**: {len(zlist)}개 구역")
    lines.append("")

    top = sorted(zones, key=lambda z: _stage_key(z.get("prgrsStpCn") or ""), reverse=True)[:15]
    lines.append("## 주요 정비사업 구역 (진행단계 높은 순)")
    for z in top:
        name  = z.get("zoneNm", "").strip()
        stage = z.get("prgrsStpCn", "").strip()
        gfa   = z.get("gfa", "").strip()
        dt    = z.get("dsgnYmd", "")[:7]
        usg   = z.get("usgRgn", "").strip()
        if not name:
            continue
        detail = f"{name}: {stage}"
        if gfa:
            try:
                detail += f" | 면적 {float(gfa):,.0f}㎡"
            except (ValueError, TypeError):
                pass
        if dt:
            detail += f" | 고시 {dt}"
        if usg:
            detail += f" | {usg}"
        lines.append(f"- {detail}")
    lines.append("")

    active = [s for s in sorted_stages if _stage_key(s) >= 5]
    lines.append("## 투자 관점 요약")
    if active:
        cnt = sum(len(by_stage[s]) for s in active)
        lines.append(
            f"{sgg}은 사업시행인가 이상 진행 단계의 정비사업이 {cnt}개 구역으로, "
            "재개발·재건축 호재가 있는 지역입니다."
        )
    else:
        lines.append(f"{sgg}의 정비사업은 초기 단계가 많아 중장기 관점에서 모니터링이 필요합니다.")
    lines.append("")

    return "\n".join(lines)


# ── 메인 ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default="rag/docs",
                        help="CSV 파일 탐색 경로 (기본: rag/docs)")
    args = parser.parse_args()

    search_dir = Path(args.input)
    all_by_sgg: dict[str, list[dict]] = {}

    # ── XLSX 파일 자동 탐지 (구청 홈페이지 공식 자료) ───────────────
    import unicodedata
    for xlsx_path in sorted(Path("data").glob("*.xlsx")):
        # macOS는 파일명을 NFD로 저장 → NFC로 정규화해서 비교
        nfc_name = unicodedata.normalize("NFC", xlsx_path.name)
        if "강남구" in nfc_name or "주택건설사업" in nfc_name:
            logger.info(f"[강남구] {xlsx_path.name}")
            for sgg, zones in parse_gangnam_xlsx(xlsx_path).items():
                all_by_sgg.setdefault(sgg, []).extend(zones)

    # ── XLS 파일 자동 탐지 (클린업시스템 구별 사업장목록) ─────────
    for xls_path in sorted(Path("data").glob("*.xls")):
        logger.info(f"[XLS] {xls_path.name}")
        for sgg, zones in parse_cleanup_xls(xls_path).items():
            all_by_sgg.setdefault(sgg, []).extend(zones)

    # ── CSV 파일 자동 탐지 ─────────────────────────────────────
    for csv_path in sorted(search_dir.glob("*.csv")):
        name = csv_path.name
        if "서울" in name:
            logger.info(f"[서울] {name}")
            for sgg, zones in parse_seoul(csv_path).items():
                all_by_sgg.setdefault(sgg, []).extend(zones)
        elif "인천" in name and "정비" in name:
            logger.info(f"[인천] {name}")
            for sgg, zones in parse_incheon(csv_path).items():
                all_by_sgg.setdefault(sgg, []).extend(zones)

    # ── API 캐시 JSON (data/redevelopment_raw.json) ────────────
    cache = DATA_DIR / "redevelopment_raw.json"
    if cache.exists():
        logger.info(f"[캐시] {cache.name}")
        for sgg, zones in parse_json_cache(cache).items():
            all_by_sgg.setdefault(sgg, []).extend(zones)

    if not all_by_sgg:
        logger.error("처리할 파일이 없습니다. rag/docs/ 에 CSV 파일을 확인하세요.")
        return

    # ── RAG 문서 생성 ──────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for sgg, zones in sorted(all_by_sgg.items()):
        doc = build_doc(sgg, zones)
        fname = f"{sgg}_재건축재개발.txt"
        (OUTPUT_DIR / fname).write_text(doc, encoding="utf-8")
        saved += 1
        logger.debug(f"  {fname} ({len(zones)}개 구역)")

    logger.info(f"완료: {saved}개 구 RAG 문서 생성")
    logger.info("다음 단계: python scripts/build_vector_index.py")


if __name__ == "__main__":
    main()
