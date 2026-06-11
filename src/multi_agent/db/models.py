from sqlalchemy import (
    Column, String, Float, Integer, Date, Boolean,
    BigInteger, Index, Text, DateTime
)
from datetime import datetime, timezone
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class AptTrade(Base):
    """아파트 매매 실거래"""
    __tablename__ = "apt_trade"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    apt_name = Column(String(100), nullable=False)
    sgg_code = Column(String(10))
    dong_name = Column(String(50))
    area_exclusive = Column(Float)
    floor = Column(Integer)
    deal_amount = Column(Float)        # 만원
    deal_date = Column(Date)
    deal_year = Column(Integer)
    deal_month = Column(Integer)
    build_year = Column(Integer)
    dealing_type = Column(String(20))

    __table_args__ = (
        Index("ix_apt_trade_dong", "dong_name"),
        Index("ix_apt_trade_sgg", "sgg_code"),
        Index("ix_apt_trade_date", "deal_year", "deal_month"),
    )


class AptRent(Base):
    """아파트 전월세"""
    __tablename__ = "apt_rent"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    apt_name = Column(String(100), nullable=False)
    sgg_code = Column(String(10))
    dong_name = Column(String(50))
    area_exclusive = Column(Float)
    floor = Column(Integer)
    deposit = Column(Float)            # 보증금 만원
    monthly_rent = Column(Float)       # 월세 만원 (전세=0)
    is_jeonse = Column(Boolean)
    deal_date = Column(Date)
    deal_year = Column(Integer)
    deal_month = Column(Integer)
    build_year = Column(Integer)

    __table_args__ = (
        Index("ix_apt_rent_dong", "dong_name"),
        Index("ix_apt_rent_sgg", "sgg_code"),
        Index("ix_apt_rent_type", "is_jeonse"),
    )


class AptGeocode(Base):
    """아파트 좌표 (Kakao 지오코딩)"""
    __tablename__ = "apt_geocode"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    apt_name = Column(String(100), nullable=False)
    dong_name = Column(String(50))
    latitude = Column(Float)
    longitude = Column(Float)
    address_full = Column(Text)

    __table_args__ = (
        Index("ix_apt_geocode_name", "apt_name", "dong_name"),
    )


class CommercialStore(Base):
    """소상공인 개별 업소 (SBIZ API)"""
    __tablename__ = "commercial_store"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    store_name = Column(String(200))
    branch_name = Column(String(100))
    large_category = Column(String(50))   # 대분류 (예: 음식)
    mid_category = Column(String(50))     # 중분류 (예: 한식)
    small_category = Column(String(50))   # 소분류 (예: 삼겹살)
    industry_code = Column(String(20))    # 업종코드
    sgg_code = Column(String(10))
    dong_name = Column(String(50))
    address = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)
    open_date = Column(String(8))         # YYYYMMDD
    close_date = Column(String(8))
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index("ix_comm_store_dong", "dong_name"),
        Index("ix_comm_store_sgg", "sgg_code"),
        Index("ix_comm_store_category", "large_category", "mid_category"),
        Index("ix_comm_store_active", "is_active"),
    )


class SchoolInfo(Base):
    """학교 기본 정보"""
    __tablename__ = "school_info"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    school_name = Column(String(100))
    school_type = Column(String(20))    # 초등학교/중학교/고등학교
    sido = Column(String(20))
    sgg_name = Column(String(30))       # 구 이름
    dong_name = Column(String(30))      # 동 이름
    address = Column(Text)
    establish_type = Column(String(10)) # 공립/사립
    hs_type = Column(String(20))        # 일반고/특목고
    special_type = Column(String(30))   # 과학고/외고 등

    __table_args__ = (
        Index("ix_school_sgg", "sgg_name"),
        Index("ix_school_type", "school_type"),
        Index("ix_school_sido", "sido"),
    )


class AcademyInfo(Base):
    """학원·교습소 정보"""
    __tablename__ = "academy_info"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    academy_name = Column(String(200))
    sgg_name = Column(String(30))       # 행정구역명 (구)
    dong_name = Column(String(30))      # 도로명주소에서 추출
    field = Column(String(50))          # 분야명
    subject = Column(String(100))       # 교습계열명
    address = Column(Text)
    capacity = Column(Integer)          # 정원합계

    __table_args__ = (
        Index("ix_academy_sgg", "sgg_name"),
        Index("ix_academy_field", "field"),
        Index("ix_academy_dong", "dong_name"),
    )


class SubwayStation(Base):
    """지하철 역사 정보 (서울교통공사 1~8호선)"""
    __tablename__ = "subway_station"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    line = Column(String(20))        # 호선 (예: 2)
    station_name = Column(String(50))
    latitude = Column(Float)
    longitude = Column(Float)

    __table_args__ = (
        Index("ix_subway_name", "station_name"),
        Index("ix_subway_line", "line"),
    )


class BusStop(Base):
    """버스 정류장 위치 정보"""
    __tablename__ = "bus_stop"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    stop_name = Column(String(100))
    city = Column(String(50))
    latitude = Column(Float)
    longitude = Column(Float)

    __table_args__ = (
        Index("ix_bus_stop_city", "city"),
        Index("ix_bus_stop_loc", "latitude", "longitude"),
    )


class ChatSession(Base):
    """Streamlit 대화 세션 영속 저장"""
    __tablename__ = "chat_session"

    session_id = Column(String(36), primary_key=True)
    thread_id = Column(String(36), nullable=False)
    title = Column(String(200), default="새 대화")
    messages_json = Column(Text, default="[]")
    map_entries_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class CommercialArea(Base):
    """상권 집계 통계 (지역 + 업종별 요약)"""
    __tablename__ = "commercial_area"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sgg_code = Column(String(10))
    dong_name = Column(String(50))
    large_category = Column(String(50))
    store_count = Column(Integer)
    active_count = Column(Integer)
    open_rate = Column(Float)             # 개업률 (%)
    close_rate = Column(Float)            # 폐업률 (%)
    reference_year = Column(Integer)
    reference_quarter = Column(Integer)

    __table_args__ = (
        Index("ix_comm_area_dong_cat", "dong_name", "large_category"),
        Index("ix_comm_area_sgg", "sgg_code"),
    )
