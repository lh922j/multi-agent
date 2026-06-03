from functools import lru_cache
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from .models import Base
from ..config import settings


@lru_cache(maxsize=1)
def get_engine():
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    return engine


def get_session() -> Session:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return SessionLocal()


def init_db():
    """테이블 생성 (최초 실행 시)"""
    engine = get_engine()
    Base.metadata.create_all(engine)


def check_connection() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
