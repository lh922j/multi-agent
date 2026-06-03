import json
from functools import lru_cache
from pathlib import Path

_CODES_PATH = Path(__file__).parents[1] / "rag" / "district_codes.json"


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
    codes = get_sgg_codes(district)
    if codes:
        placeholders = ",".join(f"'{c}'" for c in codes)
        sql = f"({dong_col} LIKE :district OR {sgg_col} IN ({placeholders}))"
        return sql, {"district": f"%{district}%"}

    # "작전동" 처럼 끝이 "동"이면 "작전1동", "작전2동"도 매칭
    if district.endswith("동"):
        base = district[:-1]  # "작전동" → "작전"
        sql = f"({dong_col} LIKE :district OR {dong_col} LIKE :district_broad)"
        return sql, {"district": f"%{district}%", "district_broad": f"%{base}%"}

    sql = f"{dong_col} LIKE :district"
    return sql, {"district": f"%{district}%"}
