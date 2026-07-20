# 🎓 CourseMate

AI 기반 학사 의사결정 지원 서비스

CourseMate는 학생들이 복잡한 수강편람과 교과과정을 쉽게 확인하고, 개인 조건에 맞는 수강 계획을 세울 수 있도록 지원하는 웹 서비스입니다.

🔗 서비스 링크

- 배포 서비스: https://course-mate-project.onrender.com/

---

## ✨ 주요 기능

### 💬 수강편람 기반 AI 챗봇
- 사용자의 자연어 질문에 대해 수강편람을 기반으로 답변합니다.
- 질문과 데이터베이스 청크 간 유사도를 비교해 관련 내용을 검색합니다.
- 답변과 함께 근거가 되는 출처를 제공합니다.
- 수강편람에 없는 내용은 임의로 생성하지 않도록 설계되어 있습니다.

### 📖 수강편람 원문 열람
- 웹사이트 내에서 수강편람 원문을 확인할 수 있습니다.
- 챗봇이 제공한 출처를 통해 관련 규정과 세부 조건을 확인할 수 있습니다.

### 🗺️ 교과과정 로드맵
- 학과와 입학연도에 따른 학년·학기별 교과과정을 제공합니다.
- 전체 로드맵을 통해 교육과정의 흐름을 한눈에 확인할 수 있습니다.
- 과목 카드 클릭 시 주요 학습 내용과 세부 정보를 제공합니다.

### 📅 학사일정 관리
- 주요 학사일정을 D-day 카드와 연간·월간 달력으로 제공합니다.
- 자연어로 입력한 개인 일정의 날짜와 일정명을 인식해 달력에 등록합니다.

### 🗓️ 개인 맞춤형 시간표 생성
- 학과, 입학연도, 학년, 목표 학점 등 기본 정보를 반영합니다.
- 희망 과목, 제외 과목, 기이수 과목을 입력할 수 있습니다.
- 공강 요일, 차단 시간대, 과목 수 제한 등 세부 조건을 설정할 수 있습니다.
- 조건을 반영한 시간표 추천안 3개를 제공합니다.
- 신청 과목 목록, 건물 이동 동선, 졸업요건 진단을 제공합니다.

---

## 🏗️ 시스템 구성

CourseMate는 수강편람과 교과과정 데이터를 구조화한 뒤, 이를 검색 및 생성 기능에 활용합니다.

핵심 처리 흐름:
1. 수강편람 문서 파싱 및 Markdown 변환
2. 주제 단위 청킹 및 데이터 정제
3. 청크 임베딩 생성 및 벡터 데이터베이스 저장
4. 사용자 질문과 청크 간 유사도 비교
5. 관련 청크를 기반으로 최종 답변 생성

- 시간표 추천·졸업요건 진단 기능은 별도로 규칙 기반 로직을 통해 계산하고, Upstage의 Solar를 이용해 자연어로 설명·조정합니다.

---

## 🧠 활용한 Upstage API 및 주요 도구

- Document Parse API: 수강편람 문서를 구조화된 Markdown으로 변환
- Embedding API (solar-embedding-2-query / -passage): 문서 청크 및 사용자 질문 임베딩 생성
- Solar Pro 3 API: 검색된 데이터를 바탕으로 최종 답변 및 기능별 결과 생성
- 벡터 DB: ChromaDB
- Backend: Python (FastAPI / Uvicorn)
- Frontend: HTML5 / CSS3 / Vanilla JavaScript (단일 SPA)
- Deployment: Render

언어 구성: Python 57.8% / HTML 42.2%

---

## 🛠️ 기술 스택

- Frontend: HTML5 / CSS3 / Vanilla JavaScript
- Backend: Python, FastAPI, Uvicorn
- Data: ChromaDB, Excel / JSON 기반 로컬 데이터
- AI: Upstage (Document Parse, Embedding, Solar Pro 3)
- Deployment: Render

---

## 로컬 개발 — 설치 및 실행

> 실제 파일명(server.py 등)과 스크립트 이름에 따라 일부 명령을 조정하세요.

1. 저장소 클론
```bash
git clone https://github.com/hong-inpyo/course_mate_-project.git
cd course_mate_-project
```

2. 가상 환경 생성 및 활성화
```bash
python -m venv venv
# macOS / Linux
source venv/bin/activate
# Windows (PowerShell)
venv\Scripts\Activate.ps1
```

3. 의존성 설치
```bash
pip install -r requirements.txt
```

4. 환경 변수 설정
- 필수
  - UPSTAGE_API_KEY: Upstage API 키
- 권장
  - CHROMA_PERSIST_DIRECTORY: ChromaDB 영속 디렉터리 경로
  - DATABASE_URL: 사용 시 DB 연결 URL

예시 `.env`:
```
UPSTAGE_API_KEY=your_upstage_api_key_here
CHROMA_PERSIST_DIRECTORY=./chroma_db
DATABASE_URL=sqlite:///./dev.db
```

5. 문서 파싱 및 임베딩 생성 (데이터 준비)
```bash
# 예시 (스크립트 파일명에 따라 변경)
python scripts/parse_and_embed.py --source data/syllabus.pdf --out-dir data/parsed
# 또는
python scripts/build_embeddings.py
```

6. 개발 서버 실행
```bash
uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

웹 접속: http://127.0.0.1:8000

---

## ☁️ 배포 (Render)

- Build Command: pip install -r requirements.txt
- Start Command: uvicorn server:app --host 0.0.0.0 --port $PORT
- Environment Variable: UPSTAGE_API_KEY

(기본 설정은 상기와 같으며, Health check 엔드포인트 추가 및 환경변수 추가/관리 권장을 권장합니다.)

---

## 보안·운영 주의사항

- UPSTAGE_API_KEY 등 민감 정보는 레포에 커밋하지 마세요. `.env`를 `.gitignore`에 추가하세요.
- 임베딩 생성은 비용이 수반되므로 배치 처리 및 캐싱 전략을 권장합니다.
- 검색 기반 리트리벌에서 근거를 항상 포함하도록 하여 허위 생성(hallucination)을 방지하세요.

---

## 테스트

- 유닛 테스트가 있다면 `pytest` 또는 `python -m unittest`로 실행하세요.
- 파이프라인(파싱 → 임베딩 → 검색 → 응답 생성)에 대한 통합 테스트 추가 권장

---

## 기여 방법

1. 저장소 포크
2. 브랜치 생성: `git checkout -b feature/your-feature`
3. 커밋: `git commit -m "Add some feature"`
4. 푸시 후 풀 리퀘스트 생성

---

## 라이선스

MIT 라이선스를 권장합니다. 원하시면 다른 라이선스로 변경해 드립니다.

---

작성자: hong-inpyo

원하시면 아래도 함께 만들어 드립니다:
- `.env.example` 및 `.gitignore` 생성
- `LICENSE` 파일 추가 (MIT 템플릿)
- Readme에 API 사용 예시(예: /api/chat) 및 배지 추가
