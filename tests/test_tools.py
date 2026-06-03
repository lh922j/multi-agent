"""
Tool 단위 테스트 — PostgreSQL 연결 필요.
실행: pytest tests/test_tools.py -v
"""
import json
import re
import pytest

from multi_agent.tools.query_trade import query_trade_data
from multi_agent.tools.query_rent import query_rent_data
from multi_agent.tools.anomaly import detect_anomaly

_MAP_RE = re.compile(r"§MAP§(.+?)§END§", re.DOTALL)


def _parse_map(result: str):
    m = _MAP_RE.search(result)
    if m:
        return json.loads(m.group(1))
    return None


class TestQueryTradeData:
    def test_returns_string(self):
        result = query_trade_data(district="역삼동", limit=3)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_district_error(self):
        result = query_trade_data(district="")
        assert "비어 있습니다" in result

    def test_map_payload_structure(self):
        result = query_trade_data(district="역삼동", area_min=55, area_max=95)
        payload = _parse_map(result)
        if payload:
            assert "map_points" in payload
            assert "text" in payload
            for pt in payload["map_points"]:
                assert "latitude" in pt
                assert "longitude" in pt
                assert pt["type"] == "trade"

    def test_no_data_region(self):
        result = query_trade_data(district="존재하지않는동네", limit=3)
        assert "없습니다" in result or len(result) < 100


class TestQueryRentData:
    def test_jeonse_filter(self):
        result = query_rent_data(district="역삼동", rent_type="전세", limit=3)
        assert isinstance(result, str)

    def test_monthly_filter(self):
        result = query_rent_data(district="역삼동", rent_type="월세", limit=3)
        assert isinstance(result, str)

    def test_map_payload_type(self):
        result = query_rent_data(district="역삼동")
        payload = _parse_map(result)
        if payload:
            for pt in payload["map_points"]:
                assert pt["type"] == "rent"


class TestDetectAnomaly:
    def test_returns_string(self):
        result = detect_anomaly(district="강남구", year_from=2022, year_to=2024)
        assert isinstance(result, str)

    def test_insufficient_data_message(self):
        result = detect_anomaly(district="존재하지않는동네")
        assert "없습니다" in result or "부족" in result or "오류" in result
