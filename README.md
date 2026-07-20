# Course Mate

Course Mate는 학습 관리 및 코스 정보 관리를 돕는 웹 기반 프로젝트입니다. 이 저장소는 Python(백엔드)과 HTML(프론트엔드)을 주로 사용하여 구현되어 있습니다.

## 주요 기능

- 코스(과목) 목록 보기 및 검색
- 코스 상세 정보 페이지
- 코스 추가/수정/삭제 (관리자 기능)
- 사용자 친화적인 UI (HTML 기반)

> 참고: 저장소에 포함된 코드와 기능은 현재 개발 중일 수 있습니다. README는 일반적인 프로젝트 소개와 실행 방법을 안내하기 위한 템플릿입니다. 필요하면 세부 내용을 추가로 맞춰 드리겠습니다.

## 기술 스택

- 언어: Python, HTML
- 프레임워크/라이브러리: (예: Flask 또는 Django — 실제 사용중인 프레임워크가 있다면 여기에 기재하세요)

## 설치 및 실행 (로컬)

1. 저장소 클론

```bash
git clone https://github.com/hong-inpyo/course_mate_-project.git
cd course_mate_-project
```

2. 가상 환경 생성 및 활성화 (권장)

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

4. 데이터베이스 마이그레이션 및 초기 설정

(프로젝트가 Django, Flask 등 어떤 프레임워크를 사용하는지에 따라 아래 명령을 수정하세요.)

- Django 예시:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

- Flask 예시:

```bash
export FLASK_APP=app.py
export FLASK_ENV=development
flask run
```

5. 브라우저에서 애플리케이션 접속

http://localhost:8000 또는 http://127.0.0.1:5000 (사용하는 프레임워크에 따라 포트가 달라집니다)

## 프로젝트 구조 (예시)

```
course_mate_-project/
├─ app/                # 애플리케이션 소스 (예: Flask/Django 앱)
├─ templates/          # HTML 템플릿
├─ static/             # CSS, JS, 이미지 등 정적 파일
├─ requirements.txt
└─ README.md
```

실제 구조는 저장소의 폴더 구성을 참고하여 본 README를 업데이트할 수 있습니다.

## 기여 방법

1. 이 저장소를 포크하세요.
2. 새로운 브랜치를 만드세요: `git checkout -b feature/your-feature`
3. 변경 사항을 커밋하세요: `git commit -m "Add some feature"`
4. 브랜치에 푸시하고 풀 리퀘스트를 생성하세요.

## 라이선스

기본적으로 MIT 라이선스를 권장합니다. 원하시면 다른 라이선스로 변경해 드립니다.

---

작성자: hong-inpyo

(원하시면 한국어/영어 상세 설명, 프로젝트 구조 자동 반영, 또는 특정 프레임워크에 맞춘 README로 수정해드릴게요.)
