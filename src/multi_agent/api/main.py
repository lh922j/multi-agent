from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from ..team import run_chat, clear_history
from ..db.database import check_connection


@asynccontextmanager
async def lifespan(app: FastAPI):
    if check_connection():
        logger.info("PostgreSQL 연결 확인")
    else:
        logger.warning("PostgreSQL 연결 실패 — DB 쿼리가 동작하지 않을 수 있습니다")
    logger.info("AutoGen Swarm 준비 완료")
    yield
    logger.info("서버 종료")


app = FastAPI(
    title="부동산 AI 멀티에이전트",
    description="AutoGen 0.4 Swarm + GraphRAG + Pinecone 기반 부동산·상권 분석 API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "강남구 84㎡ 아파트 최근 매매 시세 알려줘",
                "thread_id": "user-123",
            }
        }
    }


class ChatResponse(BaseModel):
    answer: str
    map_points: list[dict] = []
    thread_id: str


@app.get("/health")
async def health():
    db_ok = check_connection()
    return {"status": "ok", "db": "connected" if db_ok else "disconnected"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    logger.info(f"[API] /chat thread={request.thread_id} msg={request.message[:80]}")
    try:
        answer, map_points = await run_chat(request.message, request.thread_id)
    except Exception as e:
        logger.error(f"[API] /chat 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    logger.info(f"[API] 응답: {answer[:80]}")
    return ChatResponse(answer=answer, map_points=map_points, thread_id=request.thread_id)


@app.delete("/chat/{thread_id}")
async def reset_chat(thread_id: str):
    clear_history(thread_id)
    return {"status": "cleared", "thread_id": thread_id}
