# CourseMate (세종대 수강편람 도우미)

세종대학교 수강편람 기반으로 과목 탐색, 시간표 추천, 졸업요건 진단, 학사일정 확인을 지원하는 FastAPI 웹 프로젝트입니다.

## 주요 기능
- 수강편람 기반 챗봇 Q&A
- 학과/학번 기반 이수체계도(로드맵) 조회
- 과목 미리보기(요약 설명)
- 학사일정/공휴일 조회
- 조건 기반 시간표 추천 및 대안 제시

## 프로젝트 구조
```text
course_mate_-project/
└─ Upstage/
   ├─ server.py               # FastAPI 엔트리포인트
   ├─ requirements.txt        # 의존성 목록
   ├─ static/                 # 웹 UI(HTML/CSS/이미지)
   ├─ advisor/                # 시간표/졸업요건 로직
   ├─ chatbot/                # 임베딩·벡터검색·답변 파이프라인
   ├─ features/               # 로드맵/캘린더/과목설명 기능
   └─ data/                   # 수강편람 PDF, 시간표/교과과정 데이터
```

## 빠른 시작
1. 의존성 설치
   ```bash
   cd Upstage
   pip install -r requirements.txt
   ```
2. 서버 실행
   ```bash
   uvicorn server:app --reload
   ```
3. 브라우저 접속  
   `http://localhost:8000`

## 챗봇 기능 사용 전 준비(선택)
챗봇 응답 품질을 위해 벡터 DB를 준비하려면:
1. `Upstage/chatbot/secrets.json` 파일 생성
   ```json
   { "UPSTAGE_API_KEY": "YOUR_KEY" }
   ```
2. `Upstage` 경로에서 벡터 DB 생성
   ```bash
   python chatbot/pipeline.py
   ```

## API 예시
- `POST /api/chat` : 수강편람 질의응답
- `GET /api/departments` : 로드맵 지원 학과/연도 목록
- `GET /api/roadmap?department=...&year=...` : 이수체계도 조회
- `GET /api/course-info?name=...` : 과목 설명
- `GET /api/calendar/events` : 학사일정 목록
- `POST /api/timetable/recommend` : 시간표 추천

## 참고
- 데이터 파일(`Upstage/data`)이 없으면 일부 기능이 제한될 수 있습니다.
- 챗봇 API 키 또는 벡터 DB가 없으면 `/api/chat`은 안내 메시지를 반환합니다.
