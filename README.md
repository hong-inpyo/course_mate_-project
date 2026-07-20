🎓 CourseMate
AI 기반 학사 의사결정 지원 서비스

CourseMate는 학생들이 복잡한 수강편람과 교과과정을 쉽게 확인하고, 개인 조건에 맞는 수강 계획을 세울 수 있도록 지원하는 웹 서비스입니다.

🔗 서비스 링크
배포 서비스: https://course-mate-project.onrender.com/

✨ 주요 기능
💬 수강편람 기반 AI 챗봇
사용자의 자연어 질문에 대해 수강편람을 기반으로 답변
질문과 데이터베이스 청크 간 유사도를 비교해 관련 내용 검색
답변과 함께 근거가 되는 출처 제공
수강편람에 없는 내용은 임의로 생성하지 않도록 설계

📖 수강편람 원문 열람
웹사이트 내에서 수강편람 원문 확인
챗봇이 제공한 출처를 검색해 관련 규정과 세부 조건 확인

🗺️ 교과과정 로드맵
학과와 입학연도에 따른 학년·학기별 교과과정 제공
전체 로드맵을 통한 교육과정 흐름 확인
과목 카드 클릭 시 주요 학습 내용과 세부 정보 제공

📅 학사일정 관리
주요 학사일정을 D-day 카드와 연간·월간 달력으로 제공
자연어로 입력한 개인 일정의 날짜와 일정명을 인식해 달력에 등록

🗓️ 개인 맞춤형 시간표 생성
학과, 입학연도, 학년, 목표 학점 등 기본 정보 반영
희망 과목, 제외 과목, 기이수 과목 입력
공강 요일, 차단 시간대, 과목 수 제한 등 세부 조건 설정
조건을 반영한 시간표 추천안 3개 제공
신청 과목 목록, 건물 이동 동선, 졸업요건 진단 제공

🏗️ 시스템 구성
CourseMate는 수강편람과 교과과정 데이터를 구조화한 뒤, 이를 검색 및 생성 기능에 활용합니다.

수강편람 문서 파싱 및 Markdown 변환
주제 단위 청킹 및 데이터 정제
청크 임베딩 생성 및 벡터 데이터베이스 저장
사용자 질문과 청크 간 유사도 비교
관련 청크를 기반으로 최종 답변 생성

시간표 추천·졸업요건 진단 기능은 별도로, 학과별 강의시간표·교과과정·동일과목 데이터를 규칙 기반 로직으로 계산하고, Solar가 이를 자연어로 설명·조정하는 방식으로 동작합니다.

🧠 활용한 Upstage API
Document Parse API
수강편람 문서를 구조화된 Markdown 형태로 변환
Embedding API (solar-embedding-2-query / -passage)
사용자 질문과 문서 청크의 임베딩 생성
Solar Pro 3 API
검색된 데이터를 바탕으로 최종 답변과 기능별 결과 생성

🛠️ 기술 스택
Frontend
HTML5 / CSS3 / Vanilla JavaScript (별도 빌드 과정 없는 단일 SPA)

Backend
Python
FastAPI / Uvicorn

Data
ChromaDB (수강편람 청크 임베딩 벡터 저장소)
Excel / JSON 기반 로컬 데이터 (수강편람 PDF, 학과별 교과과정, 강의시간표, 동일과목 정보 등)

AI
Upstage Document Parse API
Upstage Embedding API
Upstage Solar Pro 3 API

Deployment
Render (Web Service)

☁️ 배포 (Render)
Build Command: pip install -r requirements.txt
Start Command: uvicorn server:app --host 0.0.0.0 --port $PORT
Environment Variable: UPSTAGE_API_KEY