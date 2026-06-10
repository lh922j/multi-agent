# 부동산·상권 멀티에이전트 AI

> "역삼동 84㎡ 전세 시세 알려줘", "강남구 이상거래 탐지해줘", "상계동 학군 어때?"  
> 자연어 한 문장으로 아파트 시세 조회·가격 예측·이상거래 탐지·지역 정보 검색이 가능한 AI 서비스입니다.

![아키텍처](docs/architecture.png?v=3)

---

## 개요

| 항목 | 내용 |
|------|------|
| 에이전트 프레임워크 | AutoGen 0.4 Swarm + Handoff (`autogen-agentchat==0.4.9.3`) |
| LLM | GPT-4o-mini |
| 가격 예측 모델 | LightGBM (수도권 실거래 1,129,994건 학습, R² 0.88) |
| Vector RAG | ChromaDB + Cohere Re-ranking (`rerank-multilingual-v3.0`) |
| DB | PostgreSQL 14 (Docker) |
| 모니터링 | Langfuse (에이전트별 실행 흐름 추적) |
| 프론트엔드 | Streamlit + pydeck (지도 시각화) |
| 평균 응답 시간 | 7.2초 (진행 중) |

---

## 왜 만들었나

네이버 부동산·직방은 데이터는 풍부하지만 필터 설정 → 지역 선택 → 목록 탐색을 직접 거쳐야 합니다.  
ChatGPT는 자연어로 질문할 수 있지만 실거래 데이터가 없습니다.

이 프로젝트는 **실거래 데이터 기반 응답 + 자연어 인터페이스**를 동시에 제공합니다.  
또한 직거래·이상거래를 탐지해 시세 왜곡 없이 신뢰할 수 있는 데이터를 사용합니다.

---

## 에이전트 구조

질문이 들어오면 규칙 기반 라우터가 유형을 분류하고, 전문 에이전트가 직접 최종 답변을 작성합니다. (ReportAgent 제거 — 응답 속도 34% 향상)

```
┌─────────────────────────────────────────────────────────┐
│                     사용자 질문                          │
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              KeywordRouterAgent (규칙 기반)              │
│  LLM 없이 키워드만으로 라우팅 → 비용 절감 + 안정성 확보  │
└──┬──────────┬──────────┬──────────┬──────────┬──────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
DataQuery  Prediction   RAG      Anomaly   즉시 거부
  Agent      Agent     Agent      Agent    (LLM 없음)
   │          │          │          │          │
   │  답변 + TERMINATE 직접 작성    │          │
   └──────────┴──────────┴──────────┘          │
                     │                          │
                     ▼                          ▼
           Streamlit UI 출력            "서비스 범위 외"
         (텍스트 답변 + pydeck 지도)       0.2s 응답
```

### 에이전트별 역할

| 에이전트 | LLM | 담당 도구 | 처리 질문 예시 |
|----------|-----|-----------|----------------|
| **KeywordRouterAgent** | ✗ 규칙 기반 | — | 모든 질문의 첫 관문 |
| **DataQueryAgent** | GPT-4o-mini | `query_trade_data` `query_rent_data` `query_commercial_data` `query_nearby` | "역삼동 시세", "마포구 음식점" |
| **PredictionAgent** | GPT-4o-mini | `predict_price` `get_station_coordinates` | "강남구 84㎡ 가격 예측" |
| **RAGAgent** | GPT-4o-mini | `search_area_info` | "상계동 학군", "대치동 교통" |
| **AnomalyAgent** | GPT-4o-mini | `detect_anomaly` | "강남구 이상거래 탐지" |

---

## 사용 데이터

### 부동산 실거래 (PostgreSQL)

국토교통부 실거래가 공공 API(data.go.kr, 무료)로 수집합니다.

| 테이블 | 규모 | 설명 |
|--------|------|------|
| `apt_trade` | 1,129,994건 (2020~2026) | 수도권 아파트 매매 실거래 |
| `apt_rent` | 수도권 전체 | 아파트 전세·월세 실거래 |
| `apt_geocode` | 14,273개 단지 | Kakao 지오코딩으로 확보한 단지 좌표 |

### 상권 (PostgreSQL)

소상공인시장진흥공단 상권정보 CSV로 수집합니다.

| 테이블 | 설명 |
|--------|------|
| `commercial_store` | 개별 업소 (업종·좌표·개폐업일) |
| `commercial_area` | 동·업종별 집계 통계 |

### 교육·교통 (PostgreSQL)

교육부·서울교통공사·국토교통부 공공 CSV를 파싱해 적재합니다.

| 테이블 | 규모 | 출처 |
|--------|------|------|
| `school_info` | 12,074개교 (초·중·고) | 교육부 학교기본정보 |
| `academy_info` | 138,275개 | 교육부 학원교습소정보 |
| `subway_station` | 276개 역 (1~8호선) | 서울교통공사 역사 좌표 |
| `bus_stop` | 227,060개 | 국토교통부 전국 버스정류장 |

### Vector RAG 문서 (`rag/docs/`, 197개)

위 DB 데이터를 동 단위로 집계해 자동 생성한 `.txt` 문서입니다.  
각 문서는 한 동(洞)의 전체 현황을 담고 있으며, ChromaDB에 임베딩되어 벡터 검색에 사용됩니다.

```
# 상계동 부동산·상권 현황 보고서

## 아파트 매매 실거래 (2020년~)
- 총 거래 건수: 4,312건 / 평균 매매가: 5.5억원

## 전세·월세 현황 (2022년~)
- 전세 평균 보증금: 2.6억원

## 상권 현황
- 총 영업 중 점포: 2,841개

## 학군 현황
- 초등학교 42개, 중학교 26개, 고등학교 25개
- 입시·보습 학원 2,100개

## 교통 현황
- 인근 지하철역: 마들역(7호선, 429m), 노원역(4호선, 1,018m)
- 버스정류장: 134개 (1km 이내)
```

검색 흐름: 동명 직접 조회 → 벡터 유사도 검색 (후보 10개) → **Cohere Re-ranking** (최종 3개 선택)

---

## 평가 (진행 중)

현재 진행 중인 프로젝트로, 평균 응답 시간 **7.2초** 기준으로 동작 확인 중입니다.

| 유형 | 건수 | 예시 질문 |
|------|------|-----------|
| 상권 조회 | 3 | "작전동 카페 몇 개야?" |
| 매매 시세 | 2 | "강남구 84㎡ 매매 시세 알려줘" |
| 전세 시세 | 1 | "마포구 84㎡ 전세 시세는?" |
| 지역 정보 | 4 | "상계동 학군 어때?", "상계동 교통 어때?" |
| 가격 예측 | 2 | "강남구 84㎡ 가격 예측해줘" |
| 이상거래 탐지 | 2 | "강남구 이상거래 탐지해줘" |
| 범위 외 거부 | 2 | "오늘 날씨 어때?" |
| **합계** | **16/16 (100%)** | — |

---

## 설치 및 실행

### 사전 요구사항

- Python 3.11+
- Docker Desktop (PostgreSQL 실행용)
- API 키: OpenAI, Kakao, Cohere
- Langfuse 계정 (선택, 모니터링)

### 1. 환경 설정

```bash
git clone https://github.com/lh922j/multi-agent.git
cd multi-agent

cp .env.example .env
# .env 파일에 API 키 입력

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. PostgreSQL 실행

```bash
docker compose up -d
# pgAdmin: http://localhost:5050
```

### 3. 데이터 적재

```bash
# 기존 실거래 SQLite → PostgreSQL (realestate/ 프로젝트 필요)
python scripts/migrate_db.py

# CSV 파일을 data/ 폴더에 배치 후 임포트
python scripts/import_education_csv.py   # 학교·학원
python scripts/import_transport_csv.py  # 지하철·버스
python scripts/import_commercial_csv.py # 상권
```

### 4. Vector RAG 구축

```bash
# DB → 동별 .txt 문서 생성
python scripts/build_rag_docs.py --top 200

# ChromaDB 임베딩
python scripts/build_vector_index.py
```

### 5. 앱 실행

```bash
streamlit run app/streamlit_app.py
```

### 6. 평가

```bash
python scripts/eval.py   # 골든셋 16건 자동 평가
```

---

## 디렉토리 구조

```
multi-agent/
├── app/
│   └── streamlit_app.py          # Streamlit UI (채팅 + pydeck 지도)
├── docs/
│   └── architecture.png          # 아키텍처 다이어그램
├── rag/
│   └── docs/                     # 동별 RAG 문서 197개 (.txt)
├── scripts/
│   ├── build_rag_docs.py         # DB 집계 → 동별 문서 생성
│   ├── build_vector_index.py     # ChromaDB 임베딩·인덱싱
│   ├── eval.py                   # 골든셋 자동 평가
│   ├── import_commercial_csv.py  # 상권 CSV → PostgreSQL
│   ├── import_education_csv.py   # 학교·학원 CSV → PostgreSQL
│   ├── import_transport_csv.py   # 지하철·버스 CSV → PostgreSQL
│   └── migrate_db.py             # SQLite → PostgreSQL 마이그레이션
├── src/multi_agent/
│   ├── agents/                   # 6개 에이전트 정의
│   │   ├── router.py             # KeywordRouterAgent (규칙 기반)
│   │   ├── data_query.py
│   │   ├── prediction.py
│   │   ├── rag_agent.py
│   │   ├── anomaly.py
│   │   └── report.py
│   ├── tools/                    # 에이전트 도구 함수
│   ├── db/                       # SQLAlchemy 모델 + DB 엔진
│   ├── team.py                   # Swarm 조립 + stream_chat()
│   ├── api/main.py               # FastAPI 엔드포인트
│   └── config.py                 # 환경변수 관리
├── tests/
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## 관련 프로젝트

- [realestate](https://github.com/lh922j/realestate) — 국토교통부 API 수집 + LightGBM 가격 예측 모델 학습 파이프라인
- [realestate_agent](https://github.com/lh922j/realestate_agent) — LangGraph 기반 단일 에이전트 버전 (이 프로젝트의 이전 버전)
