"""
RAG 전용 RAGAS 평가 스크립트

측정 지표 (ground_truth 불필요):
  - Faithfulness   : 답변이 검색된 context에 근거하는가
  - Answer Relevancy: 답변이 질문에 얼마나 관련 있는가

실행:
    python scripts/eval_rag.py
    python scripts/eval_rag.py --verbose
"""
import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from loguru import logger
from multi_agent.team import run_chat
from multi_agent.tools.rag import search_area_info


# ── RAG 평가 케이스 ─────────────────────────────────────────────
@dataclass
class RagEvalCase:
    id: str
    question: str
    search_query: str  # search_area_info에 직접 전달할 쿼리


RAG_CASES: list[RagEvalCase] = [
    RagEvalCase(
        id="rag_01",
        question="상계동 학군 어때?",
        search_query="상계동 학군",
    ),
    RagEvalCase(
        id="rag_02",
        question="대치동 교육 환경 알려줘",
        search_query="대치동 교육 환경",
    ),
    RagEvalCase(
        id="rag_03",
        question="노원구 학원 현황은?",
        search_query="노원구 학원 현황",
    ),
    RagEvalCase(
        id="rag_04",
        question="상계동 교통 어때?",
        search_query="상계동 교통",
    ),
]


async def collect_samples(cases: list[RagEvalCase], verbose: bool) -> dict:
    """run_chat + search_area_info를 실행해 RAGAS 입력 데이터 수집."""
    questions, answers, contexts_list = [], [], []

    for case in cases:
        logger.info(f"[{case.id}] 실행 중: {case.question}")
        thread_id = str(uuid.uuid4())

        # 1) 에이전트 전체 파이프라인 실행 → 최종 답변
        answer, _ = await run_chat(case.question, thread_id)

        # 2) search_area_info 직접 호출 → RAGAgent가 본 문서(context)
        context_text = search_area_info(case.search_query)
        # 단일 문자열을 문서 단위 리스트로 분리 ("---"로 구분)
        context_chunks = [c.strip() for c in context_text.split("---") if c.strip()]

        if verbose:
            print(f"\n[{case.id}] Q: {case.question}")
            print(f"  A: {answer[:200]}...")
            print(f"  Contexts: {len(context_chunks)}개 문서")

        questions.append(case.question)
        answers.append(answer)
        contexts_list.append(context_chunks)

    return {
        "question": questions,
        "answer": answers,
        "contexts": contexts_list,
    }


def run_ragas(data: dict) -> None:
    """RAGAS 평가 실행 후 결과 출력."""
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings

    dataset = Dataset.from_dict(data)

    from multi_agent.config import settings
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=settings.openai_api_key)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=settings.openai_api_key)

    logger.info("RAGAS 평가 실행 중 (faithfulness, answer_relevancy)...")
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy],
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=False,
    )

    print("\n" + "=" * 60)
    print("  RAGAS 평가 결과 (RAG 케이스 4건)")
    print("=" * 60)
    print(f"  Faithfulness     : {result['faithfulness']:.3f}  (0~1, 높을수록 context 기반 답변)")
    print(f"  Answer Relevancy : {result['answer_relevancy']:.3f}  (0~1, 높을수록 질문과 관련)")
    print("=" * 60)

    # 케이스별 상세 점수
    df = result.to_pandas()
    print("\n케이스별 상세:")
    for i, (_, row) in enumerate(df.iterrows()):
        case_id = RAG_CASES[i].id
        faith = row.get("faithfulness", float("nan"))
        rel = row.get("answer_relevancy", float("nan"))
        print(f"  [{case_id}] faithfulness={faith:.3f}  relevancy={rel:.3f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true", help="답변·context 출력")
    args = parser.parse_args()

    data = asyncio.run(collect_samples(RAG_CASES, args.verbose))
    run_ragas(data)


if __name__ == "__main__":
    main()
