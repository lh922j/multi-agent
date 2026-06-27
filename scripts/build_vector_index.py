"""
rag/docs/*.txt → 섹션 청킹 → ChromaDB 벡터 인덱스 구축

실행:
    python scripts/build_vector_index.py
    python scripts/build_vector_index.py --reset   # 기존 인덱스 삭제 후 재구축
"""
import argparse
import re
import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

INPUT_DIR = Path(__file__).parents[1] / "rag" / "docs"
CHROMA_DIR = Path(__file__).parents[1] / "data" / "chroma"
COLLECTION_NAME = "realestate_areas"


def chunk_by_section(content: str, doc_id: str) -> list[tuple[str, str, dict]]:
    """## 헤더 기준 섹션 분리 청킹."""
    h1_match = re.search(r'^# (.+)$', content, re.MULTILINE)
    doc_title = h1_match.group(1).strip() if h1_match else doc_id

    sections = re.split(r'\n(?=## )', content)
    chunks = []

    for section in sections:
        section = section.strip()
        if not section or len(section) < 20:
            continue

        first_line = section.split('\n')[0]

        if first_line.startswith('## '):
            section_name = first_line.replace('## ', '').strip()
            full_text = f"[{doc_title}]\n{section}"
        elif first_line.startswith('# '):
            # H1만 있고 ## 없는 첫 블록은 건너뜀 (제목줄만인 경우)
            remaining = '\n'.join(section.split('\n')[1:]).strip()
            if not remaining:
                continue
            section_name = first_line.replace('# ', '').strip()
            full_text = section
        else:
            section_name = "기타"
            full_text = section

        chunk_id = f"{doc_id}__{section_name}"
        chunks.append((chunk_id, full_text, {
            "dong_name": doc_id,
            "section": section_name,
            "source": "csv_aggregation",
        }))

    return chunks


def build_index(reset: bool = False) -> None:
    import chromadb
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
    from multi_agent.config import settings

    txt_files = sorted(INPUT_DIR.glob("*.txt"))
    if not txt_files:
        logger.error(f"txt 파일 없음: {INPUT_DIR}")
        return

    logger.info(f"문서 파일 수: {len(txt_files)}개")

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
    logger.info(f"기존 청크 수: {len(existing_ids)}개")

    ids, docs, metas = [], [], []

    for f in txt_files:
        doc_id = f.stem
        content = f.read_text(encoding="utf-8")
        if not content.strip():
            continue

        chunks = chunk_by_section(content, doc_id)
        for chunk_id, chunk_text, meta in chunks:
            if chunk_id in existing_ids and not reset:
                continue
            ids.append(chunk_id)
            docs.append(chunk_text)
            metas.append(meta)

    if not ids:
        logger.info("추가할 신규 청크 없음")
        return

    logger.info(f"신규 청크 수: {len(ids)}개")

    batch = 100
    for i in range(0, len(ids), batch):
        collection.upsert(
            ids=ids[i:i+batch],
            documents=docs[i:i+batch],
            metadatas=metas[i:i+batch],
        )
        logger.info(f"임베딩 진행: {min(i+batch, len(ids))}/{len(ids)}")

    total = collection.count()
    logger.info(f"완료 — 컬렉션 총 {total}개 청크")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="기존 인덱스 삭제 후 재구축")
    args = parser.parse_args()
    build_index(reset=args.reset)


if __name__ == "__main__":
    main()
