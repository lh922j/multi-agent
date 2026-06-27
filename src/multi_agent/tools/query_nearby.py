import json
import math
from functools import lru_cache

import httpx
from loguru import logger
from sqlalchemy import text

from ..config import settings
from ..db.database import get_engine


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _bbox(lat: float, lon: float, radius_km: float):
    lat_d = radius_km / 111.0
    lon_d = radius_km / (111.0 * math.cos(math.radians(lat)))
    return lat - lat_d, lat + lat_d, lon - lon_d, lon + lon_d


@lru_cache(maxsize=512)
def _geocode(place_name: str) -> tuple[float, float] | None:
    if not settings.kakao_api_key or not place_name.strip():
        return None
    try:
        resp = httpx.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": place_name, "size": 1},
            headers={"Authorization": f"KakaoAK {settings.kakao_api_key}"},
            timeout=4.0,
        )
        docs = resp.json().get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception as e:
        logger.warning(f"[geocode] {place_name} 실패: {e}")
    return None


def query_trade_nearby(
    place_name: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    radius_km: float = 1.0,
    area_min: float = 0,
    area_max: float = 300,
    year_from: int = 2024,
    year_to: int = 2026,
    limit: int = 5,
) -> str:
    """
    역·랜드마크 등 특정 장소 근처 아파트 매매 실거래를 조회합니다.
    place_name 입력 시 좌표를 자동 조회합니다.

    Args:
        place_name: 장소명 (예: '강남역', '코엑스'). 입력 시 latitude/longitude 불필요
        latitude: 중심 위도 (place_name 미입력 시 사용)
        longitude: 중심 경도 (place_name 미입력 시 사용)
        radius_km: 검색 반경 km (기본 1.0)
        area_min: 전용면적 최솟값 (㎡)
        area_max: 전용면적 최댓값 (㎡)
        year_from: 조회 시작 연도
        year_to: 조회 종료 연도
        limit: 반환 건수 (최대 50)
    """
    if place_name.strip():
        coords = _geocode(place_name)
        if not coords:
            return f"'{place_name}'의 위치를 찾을 수 없습니다."
        latitude, longitude = coords

    if not latitude or not longitude:
        return "장소명(place_name) 또는 위도·경도를 입력해주세요."

    limit = min(limit, 50)
    lat_min, lat_max, lon_min, lon_max = _bbox(latitude, longitude, radius_km)

    sql = text("""
        SELECT t.apt_name, t.dong_name, t.area_exclusive, t.floor,
               t.deal_amount, t.deal_date, g.latitude, g.longitude
        FROM apt_trade t
        JOIN apt_geocode g ON t.apt_name = g.apt_name AND t.dong_name = g.dong_name
        WHERE g.latitude BETWEEN :lat_min AND :lat_max
          AND g.longitude BETWEEN :lon_min AND :lon_max
          AND t.area_exclusive BETWEEN :area_min AND :area_max
          AND t.deal_year BETWEEN :year_from AND :year_to
        ORDER BY t.deal_date DESC
        LIMIT :limit
    """)
    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(sql, {
                "lat_min": lat_min, "lat_max": lat_max,
                "lon_min": lon_min, "lon_max": lon_max,
                "area_min": area_min, "area_max": area_max,
                "year_from": year_from, "year_to": year_to,
                "limit": limit,
            }).fetchall()

        rows = [r for r in rows if _haversine_km(latitude, longitude, r.latitude, r.longitude) <= radius_km]
        if not rows:
            return f"반경 {radius_km}km 내 조건에 맞는 매매 거래가 없습니다."

        lines = [
            f"[ 매매 실거래 — {place_name or f'({latitude:.4f},{longitude:.4f})'} 반경 {radius_km}km ]",
            f"{'아파트명':<20} {'동명':<10} {'면적':>6} {'층':>4} {'매매금액':>12} {'거래일':>12} {'거리':>8}",
            "-" * 86,
        ]
        map_points = []
        for r in rows:
            dist = _haversine_km(latitude, longitude, r.latitude, r.longitude)
            lines.append(
                f"{r.apt_name:<20} {r.dong_name:<10} {r.area_exclusive:>5.1f}㎡ "
                f"{r.floor:>3}층 {int(r.deal_amount):>10,}만원 {str(r.deal_date):>12} {dist:.2f}km"
            )
            map_points.append({
                "apt_name": r.apt_name,
                "dong_name": r.dong_name,
                "area_exclusive": r.area_exclusive,
                "deal_amount": float(r.deal_amount),
                "latitude": r.latitude,
                "longitude": r.longitude,
                "type": "trade",
            })

        text_result = "\n".join(lines)
        if map_points:
            payload = json.dumps({"map_points": map_points, "text": text_result}, ensure_ascii=False)
            return f"§MAP§{payload}§END§"
        return text_result

    except Exception as e:
        logger.error(f"[query_trade_nearby] 오류: {e}")
        return f"조회 오류: {e}"


def query_rent_nearby(
    place_name: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
    radius_km: float = 1.0,
    area_min: float = 0,
    area_max: float = 300,
    rent_type: str = "전체",
    year_from: int = 2024,
    year_to: int = 2026,
    limit: int = 5,
) -> str:
    """
    역·랜드마크 등 특정 장소 근처 아파트 전·월세 실거래를 조회합니다.
    place_name 입력 시 좌표를 자동 조회합니다.

    Args:
        place_name: 장소명 (예: '홍대입구역', '잠실역'). 입력 시 latitude/longitude 불필요
        latitude: 중심 위도 (place_name 미입력 시 사용)
        longitude: 중심 경도 (place_name 미입력 시 사용)
        radius_km: 검색 반경 km (기본 1.0)
        area_min: 전용면적 최솟값 (㎡)
        area_max: 전용면적 최댓값 (㎡)
        rent_type: '전세' / '월세' / '전체'
        year_from: 조회 시작 연도
        year_to: 조회 종료 연도
        limit: 반환 건수 (최대 50)
    """
    if place_name.strip():
        coords = _geocode(place_name)
        if not coords:
            return f"'{place_name}'의 위치를 찾을 수 없습니다."
        latitude, longitude = coords

    if not latitude or not longitude:
        return "장소명(place_name) 또는 위도·경도를 입력해주세요."

    limit = min(limit, 50)
    lat_min, lat_max, lon_min, lon_max = _bbox(latitude, longitude, radius_km)

    type_filter = ""
    if rent_type == "전세":
        type_filter = "AND r.is_jeonse = true"
    elif rent_type == "월세":
        type_filter = "AND r.is_jeonse = false"

    sql = text(f"""
        SELECT r.apt_name, r.dong_name, r.area_exclusive, r.floor,
               r.deposit, r.monthly_rent, r.is_jeonse, r.deal_date,
               g.latitude, g.longitude
        FROM apt_rent r
        JOIN apt_geocode g ON r.apt_name = g.apt_name AND r.dong_name = g.dong_name
        WHERE g.latitude BETWEEN :lat_min AND :lat_max
          AND g.longitude BETWEEN :lon_min AND :lon_max
          AND r.area_exclusive BETWEEN :area_min AND :area_max
          AND r.deal_year BETWEEN :year_from AND :year_to
          {type_filter}
        ORDER BY r.deal_date DESC
        LIMIT :limit
    """)
    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(sql, {
                "lat_min": lat_min, "lat_max": lat_max,
                "lon_min": lon_min, "lon_max": lon_max,
                "area_min": area_min, "area_max": area_max,
                "year_from": year_from, "year_to": year_to,
                "limit": limit,
            }).fetchall()

        rows = [r for r in rows if _haversine_km(latitude, longitude, r.latitude, r.longitude) <= radius_km]
        if not rows:
            return f"반경 {radius_km}km 내 조건에 맞는 전·월세 거래가 없습니다."

        lines = [
            f"[ 전·월세 실거래 — {place_name or f'({latitude:.4f},{longitude:.4f})'} 반경 {radius_km}km ]",
            f"{'아파트명':<20} {'동명':<10} {'면적':>6} {'유형':>4} {'보증금':>10} {'월세':>8} {'거래일':>12}",
            "-" * 84,
        ]
        map_points = []
        for r in rows:
            dist = _haversine_km(latitude, longitude, r.latitude, r.longitude)
            kind = "전세" if r.is_jeonse else "월세"
            monthly = f"{int(r.monthly_rent):,}만원" if not r.is_jeonse else "-"
            lines.append(
                f"{r.apt_name:<20} {r.dong_name:<10} {r.area_exclusive:>5.1f}㎡ "
                f"{kind:>4} {int(r.deposit):>8,}만원 {monthly:>8} {str(r.deal_date):>12} ({dist:.2f}km)"
            )
            map_points.append({
                "apt_name": r.apt_name,
                "dong_name": r.dong_name,
                "area_exclusive": r.area_exclusive,
                "deal_amount": float(r.deposit),
                "latitude": r.latitude,
                "longitude": r.longitude,
                "type": "rent",
            })

        text_result = "\n".join(lines)
        if map_points:
            payload = json.dumps({"map_points": map_points, "text": text_result}, ensure_ascii=False)
            return f"§MAP§{payload}§END§"
        return text_result

    except Exception as e:
        logger.error(f"[query_rent_nearby] 오류: {e}")
        return f"조회 오류: {e}"
