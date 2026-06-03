"""ChromaDB 벡터 RAG 기반 지역 정보 검색."""
from functools import lru_cache
from pathlib import Path

from loguru import logger

from ..config import settings

CHROMA_DIR = Path(__file__).parents[3] / "data" / "chroma"
COLLECTION_NAME = "realestate_areas"


@lru_cache(maxsize=1)
def _get_cohere():
    """Cohere 클라이언트 lazy 초기화. API 키 없으면 None."""
    if not settings.cohere_api_key:
        logger.warning("[rag] COHERE_API_KEY 미설정 — re-ranking 비활성화")
        return None
    try:
        import cohere
        return cohere.ClientV2(settings.cohere_api_key)
    except Exception as e:
        logger.warning(f"[rag] Cohere 초기화 실패: {e}")
        return None


def _rerank(query: str, docs: list[str], top_n: int = 3) -> list[int]:
    """Cohere re-ranking으로 문서 순위 반환 (인덱스 리스트). 실패 시 원래 순서."""
    co = _get_cohere()
    if not co or not docs:
        return list(range(min(top_n, len(docs))))
    try:
        resp = co.rerank(
            model="rerank-multilingual-v3.0",
            query=query,
            documents=docs,
            top_n=top_n,
        )
        return [r.index for r in resp.results]
    except Exception as e:
        logger.warning(f"[rag] Cohere re-ranking 실패: {e}")
        return list(range(min(top_n, len(docs))))


@lru_cache(maxsize=1)
def _get_collection():
    """ChromaDB 컬렉션 lazy 초기화."""
    try:
        import chromadb
        from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        embed_fn = OpenAIEmbeddingFunction(
            api_key=settings.openai_api_key,
            model_name="text-embedding-3-small",
        )
        col = client.get_collection(name=COLLECTION_NAME, embedding_function=embed_fn)
        logger.info(f"[rag] ChromaDB 컬렉션 로드: {col.count()}개 문서")
        return col
    except Exception as e:
        logger.warning(f"[rag] ChromaDB 초기화 실패 (벡터 인덱스 미구축?): {e}")
        return None


def search_area_info(query: str, mode: str = "local") -> str:
    """
    지역 특성 정보(학군·교통·상권·개발호재)를 벡터 검색으로 조회합니다.
    부동산 가격 조회가 아닌 지역 정보 질문에만 사용하세요.

    Args:
        query: 검색 질문 (예: '강남구 학군 특징', '노원구 상계동 학원 현황')
        mode: 'local' (특정 지역 심층) 또는 'global' (전체 트렌드, 다수 문서 반환)
    """
    n_results = 3 if mode == "local" else 6
    col = _get_collection()

    if col is not None:
        try:
            candidate_docs: list[str] = []
            candidate_names: list[str] = []

            # 1차: 지역명 직접 조회 (ID 기반, 정확도 우선)
            import re
            loc_m = re.search(r"([\w가-힣]{1,6}(?:동|구|읍|면))", query)
            if loc_m:
                direct = col.get(ids=[loc_m.group(1)])
                if direct["documents"]:
                    candidate_docs.append(direct["documents"][0])
                    candidate_names.append(loc_m.group(1))

            # 2차: 벡터 유사도 검색 (후보 풀 확보 — re-ranking 전 넉넉하게)
            pool_size = min(10, col.count())
            result = col.query(query_texts=[query], n_results=pool_size)
            seen = set(candidate_names)
            for doc, meta in zip(
                result.get("documents", [[]])[0],
                result.get("metadatas", [[]])[0],
            ):
                dong = meta.get("dong_name", "")
                if dong not in seen:
                    candidate_docs.append(doc)
                    candidate_names.append(dong)
                    seen.add(dong)

            if not candidate_docs:
                return _fallback_search(query)

            # 3차: Cohere Re-ranking — 후보 중 가장 관련 높은 순으로 재정렬
            ranked_idx = _rerank(query, candidate_docs, top_n=n_results)
            parts = []
            for idx in ranked_idx:
                dong = candidate_names[idx]
                parts.append(f"[{dong}]\n{candidate_docs[idx][:1500]}")

            return "\n\n---\n\n".join(parts)

        except Exception as e:
            logger.error(f"[rag] 벡터 검색 오류: {e}")

    return _fallback_search(query)


# ── Fallback: DB 집계 (벡터 인덱스 미구축 시) ────────────────────────────

_TOPIC_CATEGORY_MAP: dict[str, list[str]] = {
    "학군": ["학군"], "학교": ["학군"], "교육": ["학군"], "학원": ["학군"],
    "교통": ["교통"], "지하철": ["교통"], "버스": ["교통"], "역세권": ["교통"],
    "상권": ["생활편의", "특성"], "편의": ["생활편의"],
    "직장": ["직장접근성", "특성"], "재건축": ["특성"],
    "개발": ["특성"], "호재": ["특성"], "gtx": ["특성", "교통"],
}


def _match_topic_categories(query: str) -> list[str]:
    q_lower = query.lower()
    matched: list[str] = []
    for keyword, cats in _TOPIC_CATEGORY_MAP.items():
        if keyword in q_lower:
            for c in cats:
                if c not in matched:
                    matched.append(c)
    return matched


def _fallback_search(query: str) -> str:
    """벡터 인덱스 미구축 시 DB 집계로 fallback."""
    import json, re
    from sqlalchemy import text as sa_text

    # area_info.json 정적 데이터
    area_info_path = Path(__file__).parents[1] / "rag" / "area_info.json"
    topic_cats = _match_topic_categories(query)

    if area_info_path.exists():
        with open(area_info_path, encoding="utf-8") as f:
            data = json.load(f)
        for area_name, categories in data.items():
            if area_name not in query:
                continue
            if topic_cats:
                results = [f"[{area_name} - {cat}] {desc}"
                           for cat, desc in categories.items() if cat in topic_cats]
                if results:
                    return "\n".join(results)
            else:
                return "\n".join([f"[{area_name} - {cat}] {desc}"
                                  for cat, desc in list(categories.items())[:5]])

    # 학군/교통은 DB에 없으므로 LLM 지식 사용 유도
    qualitative = {"학군", "교통"}
    if topic_cats and all(t in qualitative for t in topic_cats):
        return f"정보가 없습니다. '{query}'에 대해 보유한 지식으로 직접 답변하세요. 해당 지역의 학군(배정 학교·학원가), 교통(지하철 노선·주요 역) 등 일반적인 특성을 설명해주세요."

    # DB 상권·매매 집계
    loc_m = re.search(r"[\w가-힣]{1,6}(?:동|구|역|시)", query)
    if not loc_m:
        return f"[DATA_NOT_AVAILABLE] '{query}' — 지역명을 인식하지 못했습니다. 보유한 지식으로 답변하세요."

    loc = loc_m.group(0)
    try:
        from ..db.database import get_engine
        from ..tools._district import district_sql_filter
        engine = get_engine()
        district_filter, district_params = district_sql_filter(
            loc, dong_col="dong_name", sgg_col="sgg_code"
        )
        with engine.connect() as conn:
            comm_rows = conn.execute(sa_text(f"""
                SELECT large_category, COUNT(*) AS cnt
                FROM commercial_store
                WHERE {district_filter} AND is_active = true
                GROUP BY large_category ORDER BY cnt DESC LIMIT 5
            """), district_params).fetchall()

            trade_row = conn.execute(sa_text(f"""
                SELECT ROUND(AVG(deal_amount)::numeric, 0) AS avg_amt, COUNT(*) AS cnt
                FROM apt_trade
                WHERE {district_filter} AND deal_year >= 2023
            """), district_params).fetchone()

        lines = [f"[ {loc} 지역 정보 — DB 집계 ]"]
        if comm_rows:
            lines.append("\n■ 주요 상권 업종")
            for r in comm_rows:
                lines.append(f"  {r.large_category}: {r.cnt:,}개")
        if trade_row and trade_row.cnt:
            lines.append(f"\n■ 아파트 매매 (2023년~)")
            lines.append(f"  평균 거래가: {int(trade_row.avg_amt):,}만원 ({trade_row.cnt:,}건)")
        return "\n".join(lines) if len(lines) > 1 else f"'{loc}' 지역 정보를 찾을 수 없습니다."

    except Exception as e:
        logger.error(f"[rag] DB fallback 오류: {e}")
        return f"[DATA_NOT_AVAILABLE] '{query}' — 보유한 지식으로 답변하세요."
