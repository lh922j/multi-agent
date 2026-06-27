import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from loguru import logger

from ..config import settings

_MODEL_PATH = settings.model_path
_RENT_MODEL_PATH = settings.rent_model_path
_WORKER = str(Path(__file__).parent / "_predict_subprocess.py")
_RAG_DIR = Path(__file__).parents[1] / "rag"

with open(_RAG_DIR / "spatial_coords.json", encoding="utf-8") as _f:
    _spatial = json.load(_f)
_SUBWAY_COORDS = np.array(list(_spatial["subway_stations"].values()))
_OFFICE_COORDS = np.array(list(_spatial["office_locations"].values()))

with open(_RAG_DIR / "lawd_cd_to_sgg_code.json", encoding="utf-8") as _f:
    _LAWD_TO_GEO = json.load(_f)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2) ** 2
    return float(6371.0 * 2 * np.arcsin(np.sqrt(a)))


def _min_dist_km(lat: float, lon: float, ref_coords: np.ndarray) -> float:
    lats = np.radians(ref_coords[:, 0])
    lons = np.radians(ref_coords[:, 1])
    dlat = lats - np.radians(lat)
    dlon = lons - np.radians(lon)
    a = np.sin(dlat / 2) ** 2 + np.cos(np.radians(lat)) * np.cos(lats) * np.sin(dlon / 2) ** 2
    return float(6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1))).min())


def _run_predict(row: dict) -> float:
    env = os.environ.copy()
    env.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    result = subprocess.run(
        [sys.executable, _WORKER, _MODEL_PATH],
        input=json.dumps(row),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"exit code {result.returncode}")
    return float(result.stdout.strip())


def predict_price(
    area_exclusive: float,
    floor: int,
    build_year: int,
    district_code: str,
    latitude: float,
    longitude: float,
    deal_year: int = 2025,
    deal_month: int = 1,
    dealing_type: str = "중개거래",
) -> str:
    """
    학습된 LightGBM 모델로 아파트 매매 예상 가격을 예측합니다.

    Args:
        area_exclusive: 전용면적 (㎡), 예: 84.0
        floor: 층수, 예: 10
        build_year: 건축연도, 예: 2010
        district_code: 시군구 코드 5자리, 예: '11680' (강남구)
        latitude: 위도, 예: 37.5172
        longitude: 경도, 예: 127.0473
        deal_year: 거래 연도 (기본 2025)
        deal_month: 거래 월 (기본 1)
        dealing_type: 거래유형 ('중개거래' 또는 '직거래')
    """
    gangnam_lat, gangnam_lon = 37.4979, 127.0276
    geo_sgg_code = _LAWD_TO_GEO.get(str(district_code), "unknown")
    season_map = {12: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 3, 10: 3, 11: 3}

    row = {
        "area_exclusive": area_exclusive,
        "floor": floor,
        "building_age": 2025 - build_year,
        "deal_year": deal_year,
        "deal_month": deal_month,
        "deal_season": season_map[deal_month],
        "latitude": latitude,
        "longitude": longitude,
        "dist_to_gangnam_km": _haversine(latitude, longitude, gangnam_lat, gangnam_lon),
        "dist_to_subway_km": round(_min_dist_km(latitude, longitude, _SUBWAY_COORDS), 3),
        "dist_to_cityhall_km": round(_min_dist_km(latitude, longitude, _OFFICE_COORDS), 3),
        "dealing_type": dealing_type,
        "sgg_code": geo_sgg_code,
    }

    logger.info(f"[predict] area={area_exclusive}㎡ floor={floor} sgg={district_code}")
    try:
        log_pred = _run_predict(row)
        predicted = int(np.expm1(log_pred))
        return (
            f"예측 매매가: {predicted:,}만원 ({predicted / 10000:.2f}억원)\n"
            f"입력 조건: {area_exclusive}㎡ / {floor}층 / {build_year}년 준공 / {district_code}"
        )
    except Exception as e:
        logger.error(f"[predict] 오류: {e}")
        return f"예측 오류: {e}"


def predict_rent_price(
    area_exclusive: float,
    floor: int,
    build_year: int,
    district_code: str,
    latitude: float,
    longitude: float,
    deal_year: int = 2025,
    deal_month: int = 1,
) -> str:
    """
    학습된 LightGBM 모델로 아파트 전세 보증금 예상 가격을 예측합니다.

    Args:
        area_exclusive: 전용면적 (㎡), 예: 66.0
        floor: 층수, 예: 10
        build_year: 건축연도, 예: 2010
        district_code: 시군구 코드 5자리, 예: '11440' (마포구)
        latitude: 위도
        longitude: 경도
        deal_year: 거래 연도 (기본 2025)
        deal_month: 거래 월 (기본 1)
    """
    gangnam_lat, gangnam_lon = 37.4979, 127.0276
    geo_sgg_code = _LAWD_TO_GEO.get(str(district_code), "unknown")
    season_map = {12: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 3, 10: 3, 11: 3}

    row = {
        "area_exclusive": area_exclusive,
        "floor": floor,
        "building_age": 2025 - build_year,
        "deal_year": deal_year,
        "deal_month": deal_month,
        "deal_season": season_map[deal_month],
        "latitude": latitude,
        "longitude": longitude,
        "dist_to_gangnam_km": _haversine(latitude, longitude, gangnam_lat, gangnam_lon),
        "dist_to_subway_km": round(_min_dist_km(latitude, longitude, _SUBWAY_COORDS), 3),
        "dist_to_cityhall_km": round(_min_dist_km(latitude, longitude, _OFFICE_COORDS), 3),
        "sgg_code": geo_sgg_code,
    }

    logger.info(f"[predict_rent] area={area_exclusive}㎡ floor={floor} sgg={district_code}")
    try:
        log_pred = subprocess.run(
            [sys.executable, _WORKER, _RENT_MODEL_PATH],
            input=json.dumps(row),
            capture_output=True,
            text=True,
            timeout=30,
            env={**__import__("os").environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
        )
        if log_pred.returncode != 0:
            raise RuntimeError(log_pred.stderr.strip())
        predicted = int(np.expm1(float(log_pred.stdout.strip())))
        return (
            f"예측 전세 보증금: {predicted:,}만원 ({predicted / 10000:.2f}억원)\n"
            f"입력 조건: {area_exclusive}㎡ / {floor}층 / {build_year}년 준공 / {district_code}"
        )
    except Exception as e:
        logger.error(f"[predict_rent] 오류: {e}")
        return f"예측 오류: {e}"
