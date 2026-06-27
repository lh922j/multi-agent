import sys
from pathlib import Path
from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    _PROJECT_ROOT = Path(__file__).parents[4]  # 로컬: .../Project/
except IndexError:
    _PROJECT_ROOT = Path(__file__).parents[2]  # Docker: /app
_DEFAULT_SQLITE = str(_PROJECT_ROOT / "realestate" / "data" / "processed" / "realestate.db")
_DEFAULT_MODEL = str(_PROJECT_ROOT / "realestate" / "data" / "models" / "price_model_trade_lgbm_complex.pkl")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenAI
    openai_api_key: str = ""

    # Pinecone (미사용, 추후 제거 예정)
    pinecone_api_key: str = ""
    pinecone_index_name: str = "realestate-graphrag"

    # PostgreSQL
    database_url: str = "postgresql+psycopg2://admin:admin1234@localhost:5432/realestate"

    # 기존 realestate/ 자산
    sqlite_db_path: str = _DEFAULT_SQLITE
    model_path: str = _DEFAULT_MODEL

    # Cohere (Re-ranking)
    cohere_api_key: str = ""

    # Kakao
    kakao_api_key: str = ""

    # SGIS 행정구역 경계 API
    sgis_service_id: str = ""     # 서비스 ID (= consumer_key)
    sgis_security_key: str = ""   # 보안 키 (= consumer_secret)

    # Tavily Search (최신 뉴스·정책 웹 검색)
    tavily_api_key: str = ""

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    log_level: str = "INFO"


settings = Settings()

_LOG_DIR = Path(__file__).parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logger.remove()
logger.add(
    sys.stdout,
    level=settings.log_level,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
)
logger.add(
    _LOG_DIR / "debug.log",
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
)
