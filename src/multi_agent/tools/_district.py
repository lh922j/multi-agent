import json
import re
from functools import lru_cache
from pathlib import Path

_CODES_PATH = Path(__file__).parents[1] / "rag" / "district_codes.json"

# 비공식 지명 → 행정동 별칭 매핑 (query_commercial_data용 dong_name LIKE 검색에 활용)
_DONG_ALIASES: dict[str, str] = {
    "홍대": "서교동",    # 홍대 = 마포구 서교동 일대
    "이태원": "이태원동",
    "신촌": "창천동",
    "건대": "화양동",
    "혜화": "혜화동",
    "성수": "성수동",
    "망원": "망원동",
    "합정": "합정동",
}


@lru_cache(maxsize=1)
def _load() -> dict[str, list[str]]:
    with open(_CODES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    flat: dict[str, list[str]] = {}
    for region_codes in data.values():
        for name, codes in region_codes.items():
            flat.setdefault(name, [])
            for c in codes:
                if c not in flat[name]:
                    flat[name].append(c)
    return flat


def get_sgg_codes(district: str) -> list[str]:
    return _load().get(district.strip(), [])


def district_sql_filter(district: str, dong_col: str = "dong_name", sgg_col: str = "sgg_code") -> tuple[str, dict]:
    d = district.strip()

    # "송파구 잠실동", "강남구 역삼동" 형태 → 동명만 추출해 검색
    m = re.match(r'^.+[구군시]\s+(.+동)$', d)
    if m:
        d = m.group(1)

    # 비공식 지명 별칭 우선 적용 (예: "홍대" → "서교동")
    d = _DONG_ALIASES.get(d, d)

    codes = get_sgg_codes(d)
    if codes:
        placeholders = ",".join(f"'{c}'" for c in codes)
        sql = f"({dong_col} LIKE :district OR {sgg_col} IN ({placeholders}))"
        return sql, {"district": f"%{d}%"}

    # "작전동" 처럼 끝이 "동"이면 "작전1동", "작전2동"도 매칭
    if d.endswith("동"):
        base = d[:-1]
        sql = f"({dong_col} LIKE :district OR {dong_col} LIKE :district_broad)"
        return sql, {"district": f"%{d}%", "district_broad": f"%{base}%"}

    sql = f"{dong_col} LIKE :district"
    return sql, {"district": f"%{d}%"}
