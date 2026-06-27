"""Tavily Search API 기반 웹 검색 도구.

GTX 개통 일정, 재개발 계획, 부동산 정책 등
ChromaDB에 없는 최신 정보 조회에 사용합니다.
"""
import httpx
from loguru import logger

from ..config import settings

_TAVILY_URL = "https://api.tavily.com/search"


def search_web(query: str) -> str:
    """
    최신 부동산 뉴스·정책·개발 계획을 웹에서 검색합니다.
    GTX 개통 일정, 재개발·재건축 계획, 정책 변화 등 실시간 정보가 필요할 때 사용하세요.
    ChromaDB에 정보가 없거나 오래된 경우 이 도구를 사용하세요.

    Args:
        query: 검색어 (예: 'GTX-B 개통 일정', '강남구 재건축 최신 뉴스')
    """
    if not settings.tavily_api_key:
        logger.warning("[search_web] TAVILY_API_KEY 미설정")
        return "[WEB_SEARCH_UNAVAILABLE] 웹 검색을 사용할 수 없습니다. 보유한 지식으로 답변하세요."

    try:
        resp = httpx.post(
            _TAVILY_URL,
            json={
                "api_key": settings.tavily_api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": True,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        lines = [f"[ 웹 검색 결과: {query} ]"]

        # Tavily 자동 요약이 있으면 먼저 표시
        if data.get("answer"):
            lines.append(f"\n요약: {data['answer']}")

        results = data.get("results", [])
        if not results:
            return f"[WEB_SEARCH_NO_RESULTS] '{query}'에 대한 검색 결과가 없습니다."

        lines.append("")
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            content = r.get("content", "")[:300]
            lines.append(f"{i}. {title}\n   {content}")

        return "\n".join(lines)

    except httpx.TimeoutException:
        logger.warning("[search_web] 요청 타임아웃")
        return "[WEB_SEARCH_TIMEOUT] 웹 검색 시간이 초과됐습니다. 보유한 지식으로 답변하세요."
    except Exception as e:
        logger.warning(f"[search_web] 오류: {e}")
        return "[WEB_SEARCH_ERROR] 웹 검색 중 오류가 발생했습니다. 보유한 지식으로 답변하세요."
