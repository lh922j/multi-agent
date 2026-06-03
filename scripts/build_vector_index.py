"""
rag/docs/*.txt → ChromaDB 벡터 인덱스 구축

실행:
    python scripts/build_vector_index.py
    python scripts/build_vector_index.py --reset   # 기존 인덱스 삭제 후 재구축
"""
import argparse
import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

INPUT_DIR = Path(__file__).parents[1] / "rag" / "docs"
CHROMA_DIR = Path(__file__).parents[1] / "data" / "chroma"
COLLECTION_NAME = "realestate_areas"


def build_index(reset: bool = False) -> None:
    import chromadb
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
    from multi_agent.config import settings

    txt_files = sorted(INPUT_DIR.glob("*.txt"))
    if not txt_files:
        logger.error(f"txt 파일 없음: {INPUT_DIR}")
        return

    logger.info(f"문서 수: {len(txt_files)}개")

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    embed_fn = OpenAIEmbeddingFunction(
        api_key=settings.openai_api_key,
        model_name="text-embedding-3-small",
    )

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            logger.info("기존 컬렉션 삭제 완료")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    existing_ids = set(collection.get()["ids"])
    logger.info(f"기존 문서 수: {len(existing_ids)}개")

    ids, docs, metas = [], [], []
    for f in txt_files:
        doc_id = f.stem  # 파일명 = 동 이름
        if doc_id in existing_ids and not reset:
            continue
        content = f.read_text(encoding="utf-8")
        if not content.strip():
            continue
        ids.append(doc_id)
        docs.append(content)
        metas.append({"dong_name": doc_id, "source": "db_aggregation"})

    if not ids:
        logger.info("추가할 신규 문서 없음")
        return

    # 배치 임베딩 (100개씩)
    batch = 100
    for i in range(0, len(ids), batch):
        collection.upsert(
            ids=ids[i:i+batch],
            documents=docs[i:i+batch],
            metadatas=metas[i:i+batch],
        )
        logger.info(f"임베딩 진행: {min(i+batch, len(ids))}/{len(ids)}")

    total = collection.count()
    logger.info(f"완료 — 컬렉션 총 {total}개 문서")
    logger.info(f"경로: {CHROMA_DIR}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="기존 인덱스 삭제 후 재구축")
    args = parser.parse_args()
    build_index(reset=args.reset)


if __name__ == "__main__":
    main()
