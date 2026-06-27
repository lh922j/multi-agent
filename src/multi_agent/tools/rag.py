"""BM25 + 벡터 하이브리드 RAG + FlashRank 재정렬."""
import re
from functools import lru_cache
from pathlib import Path

from loguru import logger

from ..config import settings

CHROMA_DIR = Path(__file__).parents[3] / "data" / "chroma"
COLLECTION_NAME = "realestate_areas"


@lru_cache(maxsize=1)
def _get_collection():
    try:
        import chromadb
        from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        embed_fn = OpenAIEmbeddingFunction(
            api_key=settings.openai_api_key,
            model_name="text-embedding-3-small",
        )
        col = client.get_collection(name=COLLECTION_NAME, embedding_function=embed_fn)
        logger.info(f"[rag] ChromaDB 로드: {col.count()}개 청크")
        return col
    except Exception as e:
        logger.warning(f"[rag] ChromaDB 초기화 실패: {e}")
        return None


@lru_cache(maxsize=1)
def _get_kiwi():
    """kiwipiepy 형태소 분석기 — 한국어 BM25 토크나이징용."""
    try:
        from kiwipiepy import Kiwi
        kiwi = Kiwi()
        logger.info("[rag] Kiwi 형태소 분석기 초기화 완료")
        return kiwi
    except Exception as e:
        logger.warning(f"[rag] Kiwi 초기화 실패 (fallback to regex): {e}")
        return None


def _tokenize(text: str) -> list[str]:
    """한국어 형태소 분석 토크나이징. Kiwi 없으면 regex fallback."""
    kiwi = _get_kiwi()
    if kiwi:
        tokens = kiwi.tokenize(text.lower())
        return [t.form for t in tokens if len(t.form) > 1]
    return re.findall(r'\w+', text.lower())


@lru_cache(maxsize=1)
def _get_bm25():
    """BM25 인덱스 — ChromaDB 전체 문서로 startup 시 구축."""
    try:
        from rank_bm25 import BM25Okapi

        col = _get_collection()
        if col is None:
            return None, [], []

        all_data = col.get(include=["documents"])
        docs = all_data["documents"]
        ids = all_data["ids"]

        tokenized = [_tokenize(doc) for doc in docs]
        bm25 = BM25Okapi(tokenized)
        logger.info(f"[rag] BM25 인덱스 구축: {len(docs)}개")
        return bm25, docs, ids
    except Exception as e:
        logger.warning(f"[rag] BM25 초기화 실패: {e}")
        return None, [], []


@lru_cache(maxsize=1)
def _get_ranker():
    """FlashRank 초기화."""
    try:
        from flashrank import Ranker
        ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank")
        logger.info("[rag] FlashRank 초기화 완료")
        return ranker
    except Exception as e:
        logger.warning(f"[rag] FlashRank 초기화 실패: {e}")
        return None


def _rrf_merge(bm25_ids: list[str], vector_ids: list[str], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion으로 BM25·벡터 점수 병합."""
    scores: dict[str, float] = {}
    for rank, doc_id in enumerate(bm25_ids):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    for rank, doc_id in enumerate(vector_ids):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)


def _flashrank(query: str, passages: list[tuple[str, str]], top_n: int) -> list[str]:
    """FlashRank reranking. passages: [(id, text), ...]"""
    ranker = _get_ranker()
    if not ranker or not passages:
        return [p[0] for p in passages[:top_n]]
    try:
        from flashrank import RerankRequest
        rerank_input = [{"id": i, "text": text} for i, (_, text) in enumerate(passages)]
        results = ranker.rerank(RerankRequest(query=query, passages=rerank_input))
        return [passages[r["id"]][0] for r in results[:top_n]]
    except Exception as e:
        logger.warning(f"[rag] FlashRank rerank 실패: {e}")
        return [p[0] for p in passages[:top_n]]


def search_area_info(query: str, mode: str = "local") -> str:
    """
    지역 특성 정보(학군·재건축·개발호재)를 BM25+벡터 하이브리드 검색으로 조회합니다.
    부동산 가격 조회가 아닌 지역 정보 질문에만 사용하세요.

    Args:
        query: 검색 질문 (예: '강남구 학군 특징', '노원구 재건축 현황')
        mode: 'local' (특정 지역) 또는 'global' (광역 트렌드)
    """
    top_n = 3 if mode == "local" else 6
    pool = 15

    col = _get_collection()
    if col is None:
        return f"[DATA_NOT_AVAILABLE] '{query}' — 벡터 인덱스 없음. 보유한 지식으로 답변하세요."

    try:
        # 1. BM25 키워드 검색
        bm25, all_docs, all_ids = _get_bm25()
        bm25_ids: list[str] = []
        if bm25:
            tokens = _tokenize(query)
            scores = bm25.get_scores(tokens)
            top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:pool]
            bm25_ids = [all_ids[i] for i in top_idx if scores[i] > 0]

        # 2. 벡터 유사도 검색
        vec_result = col.query(query_texts=[query], n_results=pool)
        vector_ids: list[str] = vec_result.get("ids", [[]])[0]
        vector_docs: list[str] = vec_result.get("documents", [[]])[0]

        if not bm25_ids and not vector_ids:
            return f"[DATA_NOT_AVAILABLE] '{query}' — 관련 문서를 찾을 수 없습니다."

        # 3. RRF 병합
        merged_ids = _rrf_merge(bm25_ids, vector_ids)[:pool]

        # id → 텍스트 매핑
        id_to_doc: dict[str, str] = {i: d for i, d in zip(all_ids, all_docs)}
        for vid, vdoc in zip(vector_ids, vector_docs):
            id_to_doc[vid] = vdoc

        passages = [(doc_id, id_to_doc[doc_id]) for doc_id in merged_ids if doc_id in id_to_doc]
        if not passages:
            return f"[DATA_NOT_AVAILABLE] '{query}' — 보유한 지식으로 답변하세요."

        # 4. FlashRank reranking
        top_ids = _flashrank(query, passages, top_n=top_n)

        parts = [id_to_doc[doc_id][:1500] for doc_id in top_ids if doc_id in id_to_doc]
        return "\n\n---\n\n".join(parts)

    except Exception as e:
        logger.error(f"[rag] 하이브리드 검색 오류: {e}")
        return f"[DATA_NOT_AVAILABLE] '{query}' — 보유한 지식으로 답변하세요."
