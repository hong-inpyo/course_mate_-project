"""
세종대 수강편람 챗봇 - 웹 서버 (FastAPI)

FastAPI + 순수 HTML/CSS/JS(SPA) 구조.

실행 방법:
    pip install fastapi uvicorn
    uvicorn server:app --reload

브라우저에서 http://localhost:8000 접속.
"""

import os
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

_ROOT = os.path.dirname(os.path.abspath(__file__))   # 프로젝트 루트 (이 파일 위치)

# 챗봇(chromadb·벡터DB)은 무거워서 import 시점에 올리지 않고, 실제 호출될 때 지연 로딩한다.
# 배포 환경(Render 등)에 벡터DB가 없어도 서버 기동과 나머지 기능은 정상 동작하게 하기 위함.
from features.roadmap_logic import (
    load_and_clean, scan_available_excels, EXCEL_DIR,
    CATEGORY_INFO, CATEGORY_ORDER, semester_sort_key,
)

app = FastAPI(title="세종대 수강편람 챗봇 API")


# ────────────────────────────────────────────────────────────────
# 챗봇 API
# ────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str


@app.post("/api/chat")
def chat(req: ChatRequest):
    # 지연 import: 벡터DB(chromadb)가 없거나 키가 없어도 서버 자체는 죽지 않고
    # 이 엔드포인트만 안내 메시지를 돌려준다.
    try:
        from chatbot.pipeline import search, generate_answer
        hits = search(req.question, top_k=10)
        answer = generate_answer(req.question, hits)
    except Exception as e:
        return {"answer": "지금은 챗봇 답변을 제공할 수 없어요. "
                          "(검색용 벡터DB가 준비되지 않았거나 API 키가 설정되지 않았습니다.)",
                "sources": [], "error": str(e)}
    return {
        "answer": answer,
        "sources": [
            {"chunk_id": h["chunk_id"], "section_path": h["section_path"], "distance": h["distance"]}
            for h in hits
        ],
    }


# ────────────────────────────────────────────────────────────────
# 이수체계도 API
# ────────────────────────────────────────────────────────────────

@app.get("/api/departments")
def get_departments():
    """curriculum_excels/ 폴더에서 사용 가능한 학과+연도 목록."""
    available = scan_available_excels()
    return {dept: years for dept, years in available.items()}


@app.get("/api/roadmap")
def get_roadmap(department: str, year: int):
    path = os.path.join(EXCEL_DIR, f"{department}_{year}.xlsx")
    if not os.path.exists(path):
        return {"error": f"{department} {year}학년도 데이터를 찾을 수 없어요."}

    df = load_and_clean(path)
    semesters = sorted(df["학기라벨"].unique(), key=semester_sort_key)

    result = []
    for sem in semesters:
        sem_df = df[df["학기라벨"] == sem]
        courses = []
        for cat in CATEGORY_ORDER:
            cat_df = sem_df[sem_df["이수구분"] == cat]
            for _, row in cat_df.iterrows():
                courses.append({
                    "name": row["교과목명"],
                    "credit": float(row["학점"]),
                    "category": cat,
                    "categoryName": CATEGORY_INFO[cat]["name"],
                    "color": CATEGORY_INFO[cat]["color"],
                })
        result.append({"semester": sem, "courses": courses})

    return {"department": department, "year": year, "semesters": result, "categories": CATEGORY_INFO}


# ────────────────────────────────────────────────────────────────
# 과목 미리보기 API
# ────────────────────────────────────────────────────────────────

from features.course_preview import explain_course

_explain_cache = {}


@app.get("/api/course-info")
def course_info(name: str):
    if name not in _explain_cache:
        _explain_cache[name] = explain_course(name)
    return {"course": name, "explanation": _explain_cache[name]}


# ────────────────────────────────────────────────────────────────
# 수강편람 원문 뷰어 API
# ────────────────────────────────────────────────────────────────

import io
import fitz
from fastapi.responses import StreamingResponse

MANUAL_PDF_PATH = os.path.join(_ROOT, "data", "2026-1학기_수강편람.pdf")


@app.get("/api/manual/info")
def manual_info():
    if not os.path.exists(MANUAL_PDF_PATH):
        return {"error": f"'{MANUAL_PDF_PATH}' 파일을 찾을 수 없어요.", "total_pages": 0}
    doc = fitz.open(MANUAL_PDF_PATH)
    return {"total_pages": len(doc)}


@app.get("/api/manual/page/{page_num}")
def manual_page(page_num: int, zoom: float = 1.8):
    if not os.path.exists(MANUAL_PDF_PATH):
        return {"error": f"'{MANUAL_PDF_PATH}' 파일을 찾을 수 없어요."}
    doc = fitz.open(MANUAL_PDF_PATH)
    if page_num < 1 or page_num > len(doc):
        return {"error": "페이지 범위를 벗어났어요."}
    page = doc[page_num - 1]
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    return StreamingResponse(io.BytesIO(pix.tobytes("png")), media_type="image/png")


@app.get("/api/manual/file")
def manual_file():
    """PDF 원본 그대로 서빙 — 브라우저 내장 PDF 뷰어(썸네일·확대·인쇄 등)로 열람."""
    if not os.path.exists(MANUAL_PDF_PATH):
        return {"error": f"'{MANUAL_PDF_PATH}' 파일을 찾을 수 없어요."}
    return FileResponse(
        MANUAL_PDF_PATH,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=\"manual.pdf\""},
    )


# ────────────────────────────────────────────────────────────────
# 학사일정 API
# ────────────────────────────────────────────────────────────────

from features.calendar_data import get_all_events, get_upcoming_events, get_holidays


@app.get("/api/calendar/events")
def calendar_events():
    return {"events": get_all_events()}


@app.get("/api/calendar/upcoming")
def calendar_upcoming(limit: int = 8):
    return {"events": get_upcoming_events(limit=limit)}


@app.get("/api/calendar/holidays")
def calendar_holidays():
    return {"holidays": get_holidays()}


class ParseEventRequest(BaseModel):
    text: str


@app.post("/api/calendar/parse-event")
def parse_event(req: ParseEventRequest):
    """'6월 22일 종강', '6/22 종강', '6-22 종강' 같은 자유 형식 텍스트를
    {date, event} 구조화된 데이터로 변환. 연도가 명시 안 되어 있으면 2026년으로 간주."""
    from openai import OpenAI
    from chatbot.pipeline import UPSTAGE_API_KEY, CHAT_BASE_URL

    client = OpenAI(api_key=UPSTAGE_API_KEY, base_url=CHAT_BASE_URL)

    schema = {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD 형식의 날짜"},
            "event": {"type": "string", "description": "일정 내용 (날짜 표현은 제외하고 순수 내용만)"},
        },
        "required": ["date", "event"],
    }

    resp = client.chat.completions.create(
        model="solar-pro3",
        messages=[
            {
                "role": "system",
                "content": (
                    "사용자가 자유 형식으로 입력한 날짜+일정 텍스트를 구조화된 데이터로 변환해줘. "
                    "'6월 22일 종강', '6/22 종강', '6-22 종강' 같은 다양한 표기를 모두 인식해야 해. "
                    "연도가 명시되어 있지 않으면 2026년으로 간주해. "
                    "날짜는 반드시 YYYY-MM-DD 형식으로, event는 날짜 표현을 제외한 순수 일정 내용만 담아."
                ),
            },
            {"role": "user", "content": req.text},
        ],
        response_format={"type": "json_schema", "json_schema": {"name": "event_schema", "schema": schema}},
    )

    import json
    result = json.loads(resp.choices[0].message.content)
    return result


# ────────────────────────────────────────────────────────────────
# 시간표 생성 · 졸업요건 진단 API (지훈 파트)
#   결정론적 파이프라인(timetable_solver·requirements·advisor)을 REST로 래핑.
#   경로는 /api/timetable/* 로 네임스페이스 (챗봇 /api/chat 과 분리).
# ────────────────────────────────────────────────────────────────
import glob
import pandas as pd
from advisor import timetable_solver as T
from advisor import equiv_courses
from advisor import requirements
from advisor import curriculum          # 학과명→교과과정 파일 해석(개명·띄어쓰기 흡수)
from advisor import advisor_agent
from advisor import timetable_explain   # 추천안 해설(선택) — TT_EXPLAIN 로 on/off
from advisor.knowledge_base import CUR_XLSX, OLD_XLSX, RENAME_JSON

TT_EXPLAIN = False   # 추천안 Solar 해설 사용 여부. False면 해설만 빠지고 나머지는 그대로 동작.
# 솔버 탐색 노드 상한. 후보 과목끼리 시간이 잘 안 겹치면 조합이 폭발해 응답이 9초까지 늘어난다.
# 탐색을 끊어도 best는 노드마다 갱신되므로 유효한 시간표가 남는다(검증: 8학과×2학년 전부 18학점 동일, 9초→2초).
NODE_BUDGET = 20000

_TT_DIR = os.path.join(_ROOT, "data")
_DF = T.load_courses(CUR_XLSX)          # 기동 시 1회 로드(캐시)
_EQMAP = equiv_courses.load()
_YCOL = next(c for c in _DF.columns if "학년" in c)


def _all_course_names():
    """'이미 들은 과목' 검색용 넓은 과목명 집합 — 연도별 시간표 + 공식 동일과목(옛 이름)."""
    names = set(_DF["교과목명"].astype(str))
    for xl in glob.glob(os.path.join(_TT_DIR, "**", "*강의시간표*.xlsx"), recursive=True):
        try:
            names |= set(pd.read_excel(xl, sheet_name=0)["교과목명"].astype(str))
        except Exception:
            pass
    for k, v in _EQMAP.items():
        names.add(k)
        names.update(v)
    return sorted(n for n in names if n and n != "nan")


TT_YEARS = [2026, 2025, 2024]     # 드롭다운에 올릴 입학년도(학번)


def _supported_depts(year):
    """해당 입학년도에 시간표를 만들 수 있는 학과만 추린다.

    시간표 엑셀의 '개설학과전공'에는 계열·단과대(IT계열, 대양휴머니티칼리지 등)와
    옛 학과까지 94개가 섞여 있다. 그대로 드롭다운에 내보내면 골라도 결과가 안 나온다.

    기준은 '그 입학년도에 이 학과 교과과정이 있는가'. 연도별로 따로 계산해야
    2025엔 있고 2026엔 없어진 학과(국방시스템공학과·기계공학과 등)를 2025 학번이
    고를 수 있고, 통합으로 사라진 학과는 2026에서 안 보인다.
    학과명 표기가 시간표와 교과과정 파일 사이에 다른 경우(띄어쓰기·학부 접두어·개명)는
    curriculum 쪽 해석을 그대로 쓴다 — 판정 로직을 두 군데 두면 어긋난다.
    """
    def has_curriculum(dept):
        r = curriculum._resolve(dept, year)
        return bool(r) and r[2] == year      # 다른 해로 폴백한 경우는 그 해에 없는 학과

    out = []
    for d in sorted(_DF["개설학과전공"].astype(str).unique()):
        if not has_curriculum(d):
            continue
        try:
            if "오류" in requirements.diagnose_any({"학과": d, "학번": year,
                                                  "총이수학점": 0, "이수과목": []}):
                continue
        except Exception:
            continue
        out.append(d)
    return out


def _display_name(dept, year):
    """화면에 보여줄 이름 — 개명된 학과는 그 해 교과과정의 이름으로 바꿔 보여준다.

    시간표 데이터엔 옛 이름이 남아 있다(2026 '국제학부 일어일문학전공' → 실제 '국제일본학전공').
    다만 학부 접두어만 다른 경우('글로벌인재학부 국제통상전공' ↔ 파일 '국제통상전공')는
    접두어가 있는 쪽이 학생에게 익숙하므로 시간표 이름을 그대로 쓴다.
    검색 키는 시간표 이름이어야 하므로 값(value)은 바꾸지 않는다.
    """
    r = curriculum._resolve(dept, year)
    if not r:
        return dept
    hit = r[1]
    return dept if dept.replace(" ", "").endswith(hit.replace(" ", "")) else hit


# 드롭다운 목록(과목명·연도별 학과)은 매번 계산하면 26초 걸린다 — 과거 강의시간표 엑셀
# 14개를 읽고(13.7초) 학과마다 교과과정을 조회하기(7.8초) 때문. 원본 파일이 바뀌지 않는 한
# 결과가 항상 같으므로 JSON으로 저장해 두고 읽는다(26초 → 2초).
# 데이터 파일을 갱신했으면 이 파일을 지우고 한 번 실행하면 다시 만들어진다.
_META_CACHE = os.path.join(_ROOT, "cache", "dropdown_meta.json")


def _load_meta():
    """캐시가 있으면 읽고, 없으면 계산한 뒤 저장을 시도한다.
    저장 실패(읽기전용 파일시스템 등)는 무시 — 계산 결과는 이미 메모리에 있어 동작에 지장 없다."""
    import json
    if os.path.exists(_META_CACHE):
        try:
            with open(_META_CACHE, encoding="utf-8") as f:
                m = json.load(f)
            return m["과목명들"], {int(y): v for y, v in m["학과들_연도별"].items()}
        except Exception:
            pass                                  # 캐시가 깨졌으면 그냥 다시 계산

    names = _all_course_names()
    depts = {y: [{"값": d, "이름": _display_name(d, y)} for d in _supported_depts(y)]
             for y in TT_YEARS}
    try:
        os.makedirs(os.path.dirname(_META_CACHE), exist_ok=True)
        with open(_META_CACHE, "w", encoding="utf-8") as f:
            json.dump({"과목명들": names, "학과들_연도별": depts}, f, ensure_ascii=False)
    except Exception:
        pass
    return names, depts


_NAMES, _DEPTS_BY_YEAR = _load_meta()


def _tt_suggest_taken(dept, grade):
    """학과·학년 기준 아래 학년 전공필수·전공기초 → '이미 들었을 과목' 추천."""
    sub = _DF[(_DF["개설학과전공"] == dept)
              & (_DF["이수구분"].isin(["전공필수", "전공기초"]))]
    sub = sub[pd.to_numeric(sub[_YCOL], errors="coerce") < grade]
    return sorted(sub["교과목명"].astype(str).unique())


class TimetableProfile(BaseModel):
    학과: str
    학번: int
    학년: int
    트랙: str = ""
    선호: str = "오전"
    목표학점: int = 18
    전공개수: int = 0
    교양개수: int = 0
    사이버강좌: bool = False
    동선최적화: bool = False
    희망과목: list[str] = []
    희망상세: dict = {}               # {과목명: {"교수": str, "분반": str}} — 빈 문자열이면 상관없음
    고정과목: list[dict] = []          # pin: [{학수번호, 분반, 시간}] — 재계산 시 항상 이 분반으로 고정
    이수과목: list[str] = []          # 과목명만 (자동추천·수동 태그)
    이수상세: list[dict] = []         # 성적표 업로드 시 [{과목,학점,성적}] — 있으면 이걸 우선 사용
    공강요일: list[str] = []
    차단시간: list[str] = []
    공강처리: str = ""
    선호교수: list[str] = []
    제외과목: list[str] = []          # 안 들을 과목(하드 조건) — 이름 일치 과목 통째 제외
    채움구분: str = ""                # 빈자리를 채울 이수구분 지정(말로 조정: '균형필수로 채워줘')
    채움상한: int = 0                 # 채움구분 과목의 최대 개수(기존 개수 유지용) — 0이면 제한 없음
    영어강의제외: bool = False
    팀플제외: bool = False
    PNP제외: bool = False
    우선순위: dict = {}               # 소프트조건 우선순위(동순위 허용) 예 {"시간대":1,"공강":2,"동선":1}


def _to_profile(p: TimetableProfile) -> dict:
    prof = {
        "학과": p.학과, "학번": p.학번, "학년": p.학년,
        "선호": p.선호, "목표학점": p.목표학점, "사이버강좌": p.사이버강좌,
        "희망과목": p.희망과목,
        # 성적표 업로드(이수상세)가 있으면 학점·성적까지 정확히, 없으면 과목명만(학점 3·성적 A0 가정)
        "이수과목": (p.이수상세 if p.이수상세
                  else [{"과목": n, "학점": 3, "성적": "A0"} for n in p.이수과목]),
    }
    # 졸업학점 진단용 총이수학점 (이수과목은 미이수 제외된 상태 → 그대로 합산)
    prof["총이수학점"] = sum(float(c.get("학점", 0) or 0) for c in prof["이수과목"])
    if p.트랙.strip():
        prof["트랙"] = p.트랙.strip()
    if p.전공개수:
        prof["전공개수"] = p.전공개수
    if p.교양개수:
        prof["교양개수"] = p.교양개수
    if p.공강요일:
        prof["공강요일"] = p.공강요일
    if p.차단시간:
        prof["차단시간"] = p.차단시간
    if p.공강처리 == "연강":
        prof["연강선호"] = True
    elif p.공강처리 == "큰공강":
        prof["우주공강방지"] = True
    if p.동선최적화:
        prof["동선최적화"] = True
    if p.선호교수:
        prof["선호교수"] = p.선호교수
    if p.제외과목:
        prof["제외과목"] = p.제외과목
    if p.채움구분:
        prof["채움구분"] = p.채움구분
        if p.채움상한:
            prof["채움상한"] = p.채움상한
    if p.희망상세:
        prof["희망상세"] = p.희망상세
    if p.우선순위:
        # 순위(1·2·3, 동순위 허용) → 벌점 가중치(1순위=4배, 2순위=2배, 3순위=1배)
        w = {1: 4, 2: 2, 3: 1}
        prof["우선순위가중치"] = {k: w.get(int(v or 1), 1) for k, v in p.우선순위.items()}
    if p.영어강의제외:
        prof["영어강의제외"] = True
    if p.팀플제외:
        prof["팀플제외"] = True
    if p.PNP제외:
        prof["PNP제외"] = True
    return prof


def _py(v):
    return v.item() if hasattr(v, "item") else v


def _clean(v, default=""):
    s = str(v).strip()
    return default if s in ("nan", "None", "", "NaN") else s


def _course_json(c: dict) -> dict:
    sec = c["sec"]
    return {
        "학수번호": str(c.get("학수번호", "")),   # 자연어 직접편집 시 시간표 복원용
        "교과목명": str(c["교과목명"]), "이수구분": str(c["이수구분"]),
        "트랙": c.get("트랙", "주전공"), "학점": float(c["credits"]), "학년": str(_py(c["학년"])),
        "시간": str(sec["시간"]), "강의실": _clean(sec["강의실"], "미정"),
        "교수": _clean(sec.get("교수"), "미정"),
        "분반": str(_py(sec["분반"])), "사이버": bool(sec.get("사이버")),
        "이러닝": sec.get("이러닝") or "",
        "언어": _clean(sec.get("언어"), ""),        # 해설: 영어강의 판정용
        "slots": [[str(d), int(s), int(e)] for d, s, e in sec["slots"]],
        "계획서": c.get("계획서"),
    }


def _diag_json(d: dict) -> dict:
    import json as _json
    if "오류" in d:
        return {"오류": d["오류"]}
    b = d["균형교양필수"]
    raw = {
        "공통필수": {"이수": d["공통필수"]["이수"], "미이수": d["공통필수"]["미이수"]},
        "균형교양": {"필요": b.get("필요"), "이수학점": b["이수학점"], "이수영역": b["이수영역"],
                   "남은학점": b["남은학점"], "완료": b["완료"], "후보": b.get("후보풀", [])},
        "학문기초": {"필요학점": d["학문기초교양필수"]["필요학점"],
                   "이수": d["학문기초교양필수"]["이수"], "미이수": d["학문기초교양필수"]["미이수"]},
        "졸업학점": d["졸업학점"], "졸업인증": d["졸업인증"],
    }
    return _json.loads(_json.dumps(raw, default=lambda o: _py(o) if hasattr(o, "item") else str(o)))


@app.get("/api/timetable/meta")
def tt_meta():
    return {"학과들_연도별": {str(y): d for y, d in _DEPTS_BY_YEAR.items()},
            "학번들": TT_YEARS, "과목명들": _NAMES,
            "기본학과": "인공지능데이터사이언스학과"}


@app.get("/api/timetable/suggest_taken")
def tt_suggest_taken(dept: str, grade: int):
    return {"추천이수": _tt_suggest_taken(dept, grade)}


@app.get("/api/timetable/course_sections")
def tt_course_sections(name: str):
    """희망과목의 이번 학기 개설 분반 목록(분반·교수·시간) — 교수/분반 지정 드롭다운용."""
    sub = _DF[_DF["교과목명"].astype(str) == name]
    out, seen = [], set()
    for _, g in sub.groupby("학수번호"):
        for s in T._make_sections(g):
            분반, 교수 = str(_py(s["분반"])), _clean(s.get("교수"), "미정")
            if (분반, 교수) in seen:            # 교차개설(같은 분반이 여러 학과 행) 중복 제거
                continue
            seen.add((분반, 교수))
            out.append({"분반": 분반, "교수": 교수, "시간": _clean(s.get("시간"), "")})
    out.sort(key=lambda x: x["분반"])
    return {"분반들": out}


def _hhmm(s):
    """'13:30' → 810(분). 빈 값이면 None."""
    s = str(s or "").strip()
    if not s or ":" not in s:
        return None
    h, m = s.split(":")[:2]
    return int(h) * 60 + int(m)


@app.get("/api/timetable/search")
def tt_search(과목명: str = "", 교수: str = "", 학과: str = "", 학년: str = "",
              요일: str = "", 시작: str = "", 종료: str = "", limit: int = 100):
    """직접 편집용 개설강좌 검색 — 필터에 맞는 분반을 납작한 목록으로 반환.
    반환 각 항목은 시간표에 바로 꽂을 수 있는 한 분반(과목 정보 + slots 포함)."""
    sub = _DF
    if 과목명:
        sub = sub[sub["교과목명"].astype(str).str.contains(과목명, case=False, na=False)]
    if 학과:
        sub = sub[sub["개설학과전공"].astype(str).str.contains(학과, na=False)]
    if 학년:
        sub = sub[sub[_YCOL].astype(str).str.contains(str(학년), na=False)]
    lo, hi = _hhmm(시작), _hhmm(종료)
    out = []
    for _, g in sub.groupby("학수번호"):
        r0 = g.iloc[0]
        for s in T._make_sections(g):
            교수명 = _clean(s.get("교수"), "미정")
            if 교수 and 교수 not in 교수명:
                continue
            slots = [[str(d), int(a), int(b)] for d, a, b in s["slots"]]
            if 요일 and not any(d == 요일 for d, _a, _b in slots):
                continue
            if (lo is not None or hi is not None) and slots:
                if not all((lo is None or a >= lo) and (hi is None or b <= hi)
                           for _d, a, b in slots):
                    continue
            out.append({
                "학수번호": str(r0["학수번호"]), "교과목명": str(r0["교과목명"]),
                "이수구분": str(r0["이수구분"]), "개설학과": str(r0["개설학과전공"]),
                "학년": str(_py(r0[_YCOL])), "학점": float(r0["학점"]),
                "분반": str(_py(s["분반"])), "교수": 교수명,
                "시간": _clean(s.get("시간"), ""), "강의실": _clean(s.get("강의실"), "미정"),
                "사이버": bool(s.get("사이버")), "이러닝": s.get("이러닝") or "",
                "slots": slots,
            })
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    return {"결과": out, "잘림": len(out) >= limit}


import random


@app.get("/api/timetable/capsule")
def tt_capsule(학과: str = "", 구분: str = "", 세부: str = "", 학점: str = "",
               사이버: str = "", 영어: str = "", 제외: str = ""):
    """교양 캡슐 뽑기 — 조건에 맞는 개설 과목 중 하나를 무작위로. 빈 값(선택 안 함)은 필터 없음.
    제외: 이미 이수한 과목명 목록(쉼표 구분) — 뽑기 후보에서 뺀다."""
    sub = _DF
    if 제외:
        names = {s.strip() for s in 제외.split(",") if s.strip()}
        for n in list(names):                # 동일과목표 반영: 다른 이름으로 개설된 같은 과목도 제외
            names |= set(_EQMAP.get(n, []))
        sub = sub[~sub["교과목명"].astype(str).isin(names)]
    if 학과:
        sub = sub[sub["개설학과전공"].astype(str) == 학과]
    if 구분 in ("교양", "전공"):
        sub = sub[sub["이수구분"].astype(str).str.contains(구분, na=False)]
    if 세부 == "필수":                       # 학문기초·전공기초 등 '기초'도 필수 계열로 포함
        sub = sub[sub["이수구분"].astype(str).str.contains("필수|기초", na=False, regex=True)]
    elif 세부 == "선택":
        sub = sub[sub["이수구분"].astype(str).str.contains("선택", na=False)]
    if 학점:
        try:
            sub = sub[sub["학점"].astype(float) == float(학점)]
        except ValueError:
            pass
    if 사이버 == "있음":
        sub = sub[T._is_cyber(sub)]
    elif 사이버 == "없음":
        sub = sub[~T._is_cyber(sub)]
    if 영어 == "있음":
        sub = sub[sub["강의언어"].astype(str).str.contains("영어", na=False)]
    elif 영어 == "없음":
        sub = sub[~sub["강의언어"].astype(str).str.contains("영어", na=False)]
    if sub.empty:
        return {"없음": True}
    name = random.choice(sub["교과목명"].astype(str).unique().tolist())
    g = sub[sub["교과목명"].astype(str) == name]
    r = g.iloc[0]
    return {
        "교과목명": name, "이수구분": str(r["이수구분"]), "학점": float(r["학점"]),
        "개설학과": str(r["개설학과전공"]), "학수번호": str(r["학수번호"]),
        "사이버": bool(T._is_cyber(g).any()),
        "영어": bool(g["강의언어"].astype(str).str.contains("영어", na=False).any()),
    }


def _solve_once(profile, 목표학점, 진단, fixed=None):
    """프로필 1개 → (직렬화된 결과 dict, 원본 chosen 리스트). 진단은 재사용(제외과목과 무관).
    fixed: pin으로 고정한 과목(chosen 구조) — 모든 추천안에 항상 포함."""
    교양후보, limits = advisor_agent._교양_후보(_DF, 진단, profile, _EQMAP)
    if profile.get("채움구분") and profile.get("채움상한"):
        # 말로 조정 '균형필수로 대체해줘': 그 구분이 무한정 늘지 않게 기존 개수만큼 상한
        limits = dict(limits or {})
        limits[profile["채움구분"]] = int(profile["채움상한"])
    rec = T.recommend_for_profile(profile, CUR_XLSX, OLD_XLSX, RENAME_JSON,
                                  target_credits=목표학점, equiv_map=_EQMAP,
                                  extra_courses=교양후보, group_limits=limits,
                                  df=_DF, fixed_courses=fixed,  # 기동 시 로드한 df 재사용(엑셀 재파싱 방지)
                                  node_budget=NODE_BUDGET)
    chosen = rec["추천시간표"]
    충돌 = sum(1 for i in range(len(chosen)) for j in range(i + 1, len(chosen))
             if T.sections_conflict(chosen[i]["sec"], chosen[j]["sec"]))

    묶음 = {}
    for w in rec.get("선수과목경고", []):
        g = 묶음.setdefault(w["과목"], {"선수": [], "필수": False})
        if w["선수과목"] not in g["선수"]:
            g["선수"].append(w["선수과목"])
        if not w["권장"]:
            g["필수"] = True
    선수경고 = [{"과목": k, "선수": v["선수"], "필수": v["필수"]} for k, v in 묶음.items()]

    # 희망과목(하드 요청)을 현재 설정과 어긋나게 넣었을 때 이유를 알려준다.
    경고 = []
    사이버포함 = bool(profile.get("사이버강좌"))
    동선최적화 = bool(profile.get("동선최적화"))
    희망이름 = {c["교과목명"] for c in chosen if c.get("트랙") == "희망"}
    for c in chosen:
        if c.get("트랙") != "희망":
            continue
        if not 사이버포함 and c["sec"].get("사이버"):
            경고.append(f"'{c['교과목명']}'은(는) 사이버강좌예요. '사이버강좌 포함'을 켜지 않았지만 "
                       f"희망하신 과목이라 시간표에 넣었어요.")
    if 동선최적화:                                   # 동선 최적화 중인데 희망과목이 촉박한 건물이동에 걸림
        for w in rec.get("이동동선", []):
            if w.get("ok"):
                continue
            앞, 뒤 = w.get("이전"), w.get("다음")
            대상 = 앞 if 앞 in 희망이름 else (뒤 if 뒤 in 희망이름 else None)
            if not 대상:
                continue
            상대 = 뒤 if 대상 == 앞 else 앞
            경고.append(f"'{대상}'은(는) '{상대}'와 강의실 이동이 촉박해요"
                       f"(도보 {w.get('이동분')}분 / 여유 {w.get('여유분')}분). "
                       f"'건물 이동 최소화'를 켰지만 희망하셔서 넣었어요.")
    # 희망과목(하드)을 못 넣었으면 조용히 빠지지 말고 이유를 안내한다.
    chosen_names = {c["교과목명"] for c in chosen}
    개설이름 = set(_DF["교과목명"].astype(str))
    for w in profile.get("희망과목", []):
        cand_names = {w} | set(_EQMAP.get(w, []))
        if cand_names & chosen_names:
            continue
        if cand_names & 개설이름:
            경고.append(f"'{w}'은(는) 기존 과목·다른 희망과목과 시간이 겹쳐 이번 시간표에 "
                       f"넣지 못했어요. 안 들을 과목·차단시간이나 다른 희망을 조정해 보세요.")
        else:
            경고.append(f"'{w}'은(는) 이번 학기에 개설되지 않아 넣지 못했어요.")

    result = {
        "metrics": {
            "총학점": float(sum(c["credits"] for c in chosen)), "목표": 목표학점,
            "과목수": len(chosen), "충돌": int(충돌),
            "남은필수": len(rec["아직_안들은_전공필수기초"]),
        },
        "timetable": [_course_json(c) for c in chosen],
        "선수경고": 선수경고,
        "경고": 경고,
        "이동동선": [{k: _py(v) for k, v in w.items()} for w in rec.get("이동동선", [])],
        "조건제외": rec.get("조건제외", []),
        "이수제외text": (advisor_agent._fmt_exclusions(rec["이수인식_제외후보"])
                     if rec["이수인식_제외후보"] else ""),
    }
    return result, chosen


def _ban_candidate(chosen, protected):
    """대안 생성용: 시간표에서 '가장 덜 중요한' 과목명 1개 선택(희망과목·보호 목록은 제외)."""
    pool = [c for c in chosen
            if str(c.get("트랙", "")) != "희망" and c["교과목명"] not in protected]
    if not pool:
        return None
    pool.sort(key=lambda c: (-c["priority"], c["credits"]))   # priority 숫자 큰(덜 중요한) 것 먼저
    return pool[0]["교과목명"]


def _struct_sig(timetable):
    """시간표의 '구조 지문' — 대면 수업이 점유하는 (요일,시작,종료) 블록 집합.
    온라인/사이버는 물리적 시간 점유가 아니라 제외한다. 지문이 같으면 '같은 구조'로 보고,
    과목만 다른 쌍둥이 안은 별도 추천안 대신 교체대안으로 합친다."""
    blocks = set()
    for c in timetable:
        if c.get("사이버") or c.get("이러닝"):
            continue
        for d, s, e in c.get("slots", []):
            blocks.add((str(d), int(s), int(e)))
    return frozenset(blocks)


def _lunch_blocked(blocks):
    """사용자가 차단시간으로 점심(12:00~13:00)을 이미 비워 뒀는지 — 해설이 '점심 챙기기 좋다'를
    사용자 스스로 만든 공백에 대해 생색내지 않도록 판정."""
    for b in blocks:
        for _d, s, e in T.parse_times(b):
            if s < 13 * 60 and 12 * 60 < e:
                return True
    return False


def _swap_note(base_tt, alt_tt):
    """구조가 같은 두 안의 과목 차이 → '이 자리엔 A 대신 B(같은 시간·같은 구분)' 사실 노트.
    차이가 없으면 None."""
    b = {c["교과목명"] for c in base_tt}
    a = {c["교과목명"] for c in alt_tt}
    뺀, 넣은 = sorted(b - a), sorted(a - b)
    if not 뺀 and not 넣은:
        return None
    return {"뺀": 뺀, "넣은": 넣은}


def _recommend_alts(p: TimetableProfile, n_alts=3):
    """추천안을 만든다. 1안=최적해. 2·3안은 직전 안에서 덜 중요한 과목 하나를 제외과목으로
    돌려 재구성하되, **구조(대면 시간 배치)가 실제로 다른 안만** 별도 추천안으로 노출한다.
    구조가 같고 과목만 바뀐 안은 '이 자리엔 X 대신 Y' 교체대안으로 합친다(쌍둥이 안 방지).
    마지막에 (선택) Solar가 각 안을 1~2줄로 해설한다 — TT_EXPLAIN 으로 끌 수 있다."""
    profile = _to_profile(p)
    진단 = requirements.diagnose_any(profile, _EQMAP)
    if "질문" in 진단 or "오류" in 진단:
        return {"error": 진단.get("질문") or 진단.get("오류")}

    # pin: 고정한 과목을 chosen 구조로 복원 → 모든 추천안에 seed. 대안 생성 시 제외 대상에서도 보호.
    fixed = _rebuild_chosen(p.고정과목, p.선호) if p.고정과목 else []
    protected = set(p.희망과목) | {c["교과목명"] for c in fixed}
    alts, banned = [], []
    sig_index = {}   # 구조 지문 → alts 인덱스 (같은 구조면 새 안 대신 교체대안으로 합침)
    shown_bans = 0   # 마지막으로 보여준 안까지 반영된 banned 개수 → 안마다 '증분'만 표기
    for i in range(n_alts + 2):   # 구조 dedup으로 안이 줄 수 있어 몇 번 더 시도
        prof_i = dict(profile)
        if banned:
            prof_i["제외과목"] = list(profile.get("제외과목", [])) + banned
        result, chosen = _solve_once(prof_i, p.목표학점, 진단, fixed=fixed)
        if not chosen:
            break
        sig = _struct_sig(result["timetable"])
        if sig in sig_index:                      # 구조 동일 → 과목만 다른 쌍둥이
            base = alts[sig_index[sig]]
            note = _swap_note(base["timetable"], result["timetable"])
            if note and note not in base.setdefault("교체대안", []):
                base["교체대안"].append(note)
        else:
            sig_index[sig] = len(alts)
            alts.append({"label": f"추천안 {len(alts) + 1}",
                         "다른점": banned[shown_bans:], **result})  # 직전 안 이후 새로 뺀 과목만
            shown_bans = len(banned)
            if len(alts) >= n_alts:               # 구조가 다른 안을 목표 개수만큼 확보
                break
        ban = _ban_candidate(chosen, protected)
        if not ban:
            break
        banned.append(ban)

    if TT_EXPLAIN:            # (선택) 각 안에 Solar 1~2줄 해설('summary' 키) 부착 — 끌 수 있음
        timetable_explain.explain(
            alts,
            요청공강=set(profile.get("공강요일", [])),           # 사용자가 일부러 비운 요일
            점심차단=_lunch_blocked(profile.get("차단시간", [])),  # 점심을 차단시간으로 이미 비웠나
        )
    if not alts:          # 후보 과목이 하나도 없으면(예: 해당 학년 개설 없음) 500 대신 안내
        return {"error": f"{profile['학과']} {profile.get('학년')}학년에 넣을 수 있는 과목을 못 찾았어요."}
    resp = {k: v for k, v in alts[0].items() if k not in ("label", "다른점")}
    resp["진단"] = _diag_json(진단)
    resp["alts"] = alts
    resp["이수확장"] = _taken_expanded(profile)
    return resp


def _taken_expanded(profile):
    """이수과목명 + 공식 동일과목명 — 프런트 재수강 경고가 동일과목까지 잡도록."""
    names = {str(c.get("과목", "")) for c in profile.get("이수과목", [])} - {""}
    out = set(names)
    for n in names:
        out |= set(_EQMAP.get(n, []))
    return sorted(out)


@app.post("/api/timetable/recommend")
def tt_recommend(p: TimetableProfile):
    return _recommend_alts(p)


@app.post("/api/timetable/parse_grades")
def tt_parse_grades(file: UploadFile = File(...)):
    """학사정보시스템 '기이수성적조회' 엑셀 업로드 → 이수과목(학점·성적 포함) 추출.
    F/NP/W 등 미이수는 제외되어 재수강 후보로 남는다."""
    import io
    try:
        taken = T.parse_grade_excel(io.BytesIO(file.file.read()))
    except Exception as e:
        return {"error": f"엑셀을 읽지 못했습니다: {e}"}
    if not taken:
        return {"error": "엑셀에서 '교과목명' 헤더를 찾지 못했습니다. 기이수성적조회 파일이 맞는지 확인해주세요."}
    return {"과목들": [t["과목"] for t in taken], "상세": taken,
            "총학점": sum(t["학점"] for t in taken)}


def _rebuild_chosen(items, prefer):
    """프런트가 보낸 [{학수번호, 분반, 시간}] → solve 결과와 동일한 chosen 구조로 복원.
    자연어 '직접 편집' 모드에서 현재 시간표를 그대로 고정하기 위해 사용.
    ※ 교차개설 과목은 같은 학수번호·분반이 여러 행(학과)으로 존재해 시간이 다를 수
    있으므로, '시간' 문자열까지 맞는 행을 찾는다 (분반 번호만으로는 오복원 위험)."""
    chosen = []
    for it in items:
        code, sec_no = str(it.get("학수번호", "")), str(it.get("분반", ""))
        want_time = str(it.get("시간", "") or "")
        g = _DF[_DF["학수번호"].astype(str) == code]
        if g.empty:
            continue
        secs = T._make_sections(g)
        idx = next((i for i, s in enumerate(secs)
                    if str(s["분반"]) == sec_no
                    and (not want_time or str(s["시간"]) == want_time)), None)
        if idx is None:   # 시간까지 일치하는 행이 없으면 분반만으로 폴백
            idx = next((i for i, s in enumerate(secs) if str(s["분반"]) == sec_no), None)
        if idx is None:
            continue
        sec, r0 = secs[idx], g.iloc[idx]   # 과목 정보도 매칭된 행에서 (개설학과 정확히)
        chosen.append({"학수번호": code, "교과목명": str(r0["교과목명"]),
                       "이수구분": str(r0["이수구분"]), "개설학과": str(r0["개설학과전공"]),
                       "학년": r0[_YCOL], "학점": float(r0["학점"]), "credits": float(r0["학점"]),
                       "priority": T.PRIORITY.get(str(r0["이수구분"]), 9),
                       "sec": sec, "pen": T.pref_penalty(sec, prefer)})
    return chosen


def _edit_timetable(p: TimetableProfile, adds, removes, current_items):
    """자연어 과목 추가/제거를 '재계산' 대신 현재 시간표에 대한 직접 편집으로 처리.
    나머지 과목은 절대 건드리지 않고, 편집 결과에 무결성 검사(학점·선호 위반·충돌)를
    돌려 경고 문구로 알려준다. 충돌 시에는 다른 분반·동일과목(타학과 포함)을 시도한다."""
    profile = _to_profile(p)
    chosen = _rebuild_chosen(current_items, p.선호)
    warnings = []
    syl = T.load_syllabus_map()
    off_days = set(profile.get("공강요일", []))
    blocks = []
    for s in profile.get("차단시간", []):
        blocks += T.parse_times(s)

    # ── 제거 (공식 동일과목 이름까지 인정) ──
    for name in removes:
        targets = {name} | set(_EQMAP.get(name, []))
        before = len(chosen)
        chosen = [c for c in chosen if c["교과목명"] not in targets]
        if len(chosen) == before:
            warnings.append(f"'{name}'은(는) 현재 시간표에 없어서 뺄 것이 없었어요.")

    # ── 추가: 동일과목·타학과 분반까지 후보로, 고정된 나머지와 충돌 없는 분반 선택 ──
    for name in adds:
        names = {name} | set(_EQMAP.get(name, []))
        if any(c["교과목명"] in names for c in chosen):
            warnings.append(f"'{name}'은(는) 이미 시간표에 있어요.")
            continue
        cands = T.build_courses_by_names(_DF, names,
                                         include_cyber=bool(profile.get("사이버강좌")))
        if not cands:
            warnings.append(f"'{name}' 과목을 이번 학기 개설강좌에서 찾지 못했어요.")
            continue
        best = None   # (정렬키, course, sec, 충돌과목들, 위반조건들)
        for course in cands:
            same_dept = (course["개설학과"] == p.학과)
            for sec in course["sections"]:
                conf = sorted({c["교과목명"] for c in chosen
                               if T.sections_conflict(sec, c["sec"])})
                viol = []
                if any(d in off_days for d, _s, _e in sec["slots"]):
                    viol.append("공강 요일")
                if any(T.slots_overlap(a, b) for a in sec["slots"] for b in blocks):
                    viol.append("차단 시간")
                if profile.get("영어강의제외") and "영어" in str(sec.get("언어") or ""):
                    viol.append("영어강의 제외")
                key = (len(conf) > 0, len(viol), 0 if same_dept else 1,
                       T.pref_penalty(sec, p.선호))
                if best is None or key < best[0]:
                    best = (key, course, sec, conf, viol)
        _k, course, sec, conf, viol = best
        if conf:   # 모든 분반이 기존 과목과 충돌 → 충돌 0 원칙상 추가하지 않고 알림
            warnings.append(f"'{course['교과목명']}'은(는) 모든 분반이 기존 과목({', '.join(conf)})과 "
                            f"겹쳐서 넣지 못했어요. 겹치는 과목을 빼달라고 하면 넣을 수 있어요.")
            continue
        chosen.append({**{k2: course[k2] for k2 in
                          ("학수번호", "교과목명", "이수구분", "개설학과", "학년", "학점", "priority")},
                       "credits": course["학점"], "sec": sec,
                       "pen": T.pref_penalty(sec, p.선호)})
        if course["개설학과"] != p.학과:
            warnings.append(f"'{course['교과목명']}'은(는) 내 학과 분반이 맞지 않아 "
                            f"{course['개설학과']} 개설 분반으로 넣었어요.")
        for v in viol:
            warnings.append(f"'{course['교과목명']}' 분반이 설정한 조건({v})과 어긋나요 — "
                            f"직접 요청하신 과목이라 그대로 넣고 알려드려요.")
        if T.pref_penalty(sec, p.선호) > 0:
            warnings.append(f"'{course['교과목명']}' 시간이 {p.선호} 선호와 달라요.")
        s_info = syl.get(course["교과목명"], {})
        if profile.get("팀플제외") and s_info.get("팀플"):
            warnings.append(f"'{course['교과목명']}'에는 팀 프로젝트가 있어요 (팀플 제외 설정과 충돌).")
        if profile.get("PNP제외") and s_info.get("PNP"):
            warnings.append(f"'{course['교과목명']}'은(는) P/NP 성적이에요 (P/NP 제외 설정과 충돌).")

    # ── 무결성 검사: 학점 초과/부족 ──
    total = sum(c["credits"] for c in chosen)
    if total > p.목표학점 + 0.5:
        warnings.append(f"총 {total:g}학점 — 목표 {p.목표학점}학점을 초과했어요.")
    elif total < p.목표학점 - 2.5:
        warnings.append(f"총 {total:g}학점 — 목표 {p.목표학점}학점보다 부족해요. "
                        f"과목을 더 넣어달라고 요청해 보세요.")

    # ── 결과 직렬화 (recommend와 동일 형태 + 경고) ──
    T.annotate_syllabus(chosen, syl)
    충돌 = sum(1 for i in range(len(chosen)) for j in range(i + 1, len(chosen))
             if T.sections_conflict(chosen[i]["sec"], chosen[j]["sec"]))
    passed = [c for c in profile.get("이수과목", []) if c.get("성적") not in T.GRADE_FAIL]
    묶음 = {}
    for w in T.prereq_warnings(chosen, taken_names=[c["과목"] for c in passed],
                               prereq_map=syl, equiv_map=_EQMAP):
        g = 묶음.setdefault(w["과목"], {"선수": [], "필수": False})
        if w["선수과목"] not in g["선수"]:
            g["선수"].append(w["선수과목"])
        if not w["권장"]:
            g["필수"] = True
    선수경고 = [{"과목": k, "선수": v["선수"], "필수": v["필수"]} for k, v in 묶음.items()]
    진단 = requirements.diagnose_any(profile, _EQMAP)
    must = T.build_candidates(_DF, p.학과, 이수구분=("전공필수", "전공기초"),
                              target_years=tuple(range(1, p.학년 + 1)))
    남은필수, _ = T.filter_taken(must, taken_names=[c["과목"] for c in passed],
                              equiv_map=_EQMAP)

    result = {
        "metrics": {"총학점": float(total), "목표": p.목표학점, "과목수": len(chosen),
                    "충돌": int(충돌), "남은필수": len(남은필수)},
        "timetable": [_course_json(c) for c in chosen],
        "선수경고": 선수경고,
        "이동동선": [{k: _py(v) for k, v in w.items()} for w in T.movement_report(chosen)],
        "조건제외": [], "이수제외text": "",
        "진단": _diag_json(진단) if "오류" not in 진단 and "질문" not in 진단 else {},
        "경고": warnings,
        "이수확장": _taken_expanded(profile),
    }
    result["alts"] = [{"label": "편집된 시간표", "다른점": [], **{k: result[k] for k in
                       ("metrics", "timetable", "선수경고", "이동동선")}}]
    return result


class TTNLRequest(BaseModel):
    text: str                          # 자연어 요청 ("금요일 비워주고 확통은 빼줘")
    profile: TimetableProfile          # 현재 폼 상태 — 여기에 델타를 얹어 재생성
    현재과목: list[str] = []            # 현재 시간표 과목명 (약칭 해석의 근거)
    현재시간표: list[dict] = []          # [{학수번호, 분반}] — 직접 편집 모드에서 고정할 시간표


_NL_SCHEMA = {
    "type": "object",
    "properties": {
        "공강요일추가": {"type": "array", "items": {"type": "string", "enum": ["월", "화", "수", "목", "금"]},
                    "description": "'금공강'·'금요일 비워줘' 등 요일을 통째로 비우라는 요청. 해당 없으면 []"},
        "공강요일제거": {"type": "array", "items": {"type": "string", "enum": ["월", "화", "수", "목", "금"]},
                    "description": "비웠던 요일을 다시 쓰라는 요청. 해당 없으면 []"},
        "차단시간추가": {"type": "array", "items": {"type": "string"},
                    "description": "알바·학원 등 특정 시간대를 피하라는 요청. '월 09:00~10:30' 형식, "
                                   "여러 요일이면 '월 수 09:00~11:00'. 해당 없으면 []"},
        "제외과목추가": {"type": "array", "items": {"type": "string"},
                    "description": "빼달라는 과목. 해당 없으면 []"},
        "희망과목추가": {"type": "array", "items": {"type": "string"},
                    "description": "넣어달라는 과목. 해당 없으면 []"},
        "고정과목추가": {"type": "array", "items": {"type": "string"},
                    "description": "바꾸지 말고 그대로 두라는 과목('고정해줘/유지해줘/건들지 마/그대로 둬'). 해당 없으면 []"},
        "고정과목해제": {"type": "array", "items": {"type": "string"},
                    "description": "고정을 풀어달라는 과목('고정 풀어줘/해제해줘'). 해당 없으면 []"},
        "대체과목": {"type": "array", "items": {"type": "string"},
                 "description": "'다른 과목으로 바꿔/대체해/교체해 달라'는 과목 — 빼고 그 자리를 다른 과목으로 채운다. 해당 없으면 []"},
        "채움구분": {"type": "string",
                 "enum": ["", "공통교양필수", "학문기초교양필수", "균형교양필수", "교양선택",
                         "전공필수", "전공기초", "전공선택"],
                 "description": "빈자리를 채울 과목의 이수구분을 지정한 경우('균형필수 과목으로 대체/채워줘'). 언급 없으면 빈 문자열"},
        "요건우선재계산": {"type": "string", "enum": ["켬", ""],
                    "description": "'내 졸업요건 기준으로/남은 필수 위주로 채워줘·다시 짜줘' 요청이면 켬"},
        "분반지정": {"type": "array",
                 "items": {"type": "object",
                           "properties": {"과목": {"type": "string"}, "분반": {"type": "string"},
                                          "교수": {"type": "string"}},
                           "required": ["과목", "분반", "교수"]},
                 "description": "특정 분반이나 교수로 바꿔달라는 요청('확통 2분반으로/김OO 교수님 걸로'). 모르는 값은 빈 문자열. 없으면 []"},
        "선호": {"type": "string", "enum": ["오전", "오후", ""],
               "description": "시간대 선호 변경. 언급 없으면 빈 문자열"},
        "목표학점": {"type": "integer", "description": "목표학점 변경. 언급 없으면 0"},
        "공강처리": {"type": "string", "enum": ["연강", "큰공강", ""],
                 "description": "'수업 붙여줘'=연강, '긴 공강 피해줘'=큰공강. 언급 없으면 빈 문자열"},
        "영어강의제외": {"type": "string", "enum": ["켬", "끔", ""], "description": "언급 없으면 빈 문자열"},
        "팀플제외": {"type": "string", "enum": ["켬", "끔", ""], "description": "언급 없으면 빈 문자열"},
        "PNP제외": {"type": "string", "enum": ["켬", "끔", ""], "description": "언급 없으면 빈 문자열"},
        "사이버강좌": {"type": "string", "enum": ["켬", "끔", ""], "description": "사이버강좌 포함 여부. 언급 없으면 빈 문자열"},
        "동선최적화": {"type": "string", "enum": ["켬", "끔", ""], "description": "언급 없으면 빈 문자열"},
        "요약": {"type": "string", "description": "이해한 요청을 한국어 한 문장으로"},
    },
    "required": ["공강요일추가", "공강요일제거", "차단시간추가", "제외과목추가", "희망과목추가",
                 "고정과목추가", "고정과목해제", "대체과목", "채움구분", "요건우선재계산", "분반지정",
                 "선호", "목표학점", "공강처리", "영어강의제외", "팀플제외", "PNP제외",
                 "사이버강좌", "동선최적화", "요약"],
}


def _nl_resolve_courses(names, current):
    """LLM이 출력한 과목명을 실제 과목명으로 확정. 현재 시간표 → 전체 개설과목 순으로
    정확일치 → 부분일치 매칭(결정론적). 실제 과목으로 해석 안 되는 표현('팀플' 등)은 버린다."""
    out = []
    for n in names or []:
        n = str(n).strip()
        if not n:
            continue
        if n in current or n in _NAMES:
            out.append(n)
            continue
        cand = ([c for c in current if n in c or c in n]
                or [c for c in _NAMES if n in c])
        if cand:
            out.append(cand[0])
    return out


@app.post("/api/timetable/nl_adjust")
def tt_nl_adjust(req: TTNLRequest):
    """자연어 요청 → (Solar) 구조화 조건 델타 → 폼 상태에 병합 → 결정론적 재생성.
    LLM은 언어 이해만 담당 — 시간표 계산·충돌 판정은 전부 규칙 기반 코드가 한다."""
    from openai import OpenAI
    from chatbot.pipeline import UPSTAGE_API_KEY, CHAT_BASE_URL
    import json as _json

    client = OpenAI(api_key=UPSTAGE_API_KEY, base_url=CHAT_BASE_URL)
    cur = ", ".join(req.현재과목) or "(없음)"
    resp = client.chat.completions.create(
        model="solar-pro3",
        messages=[
            {"role": "system", "content": (
                "너는 시간표 조건 파서다. 사용자의 자연어 요청을 JSON의 해당 필드로 빠짐없이 변환해라. "
                "시간표를 직접 짜지 말고 조건만 추출해라. 모든 필드를 출력하되 언급 안 된 것은 기본값([]·''·0)으로 둬라.\n"
                "변환 규칙(반드시 지켜라):\n"
                "- 요일을 비우라는 요청('금공강', '금요일 비워줘', '월요일엔 수업 없게') → 반드시 공강요일추가에 그 요일을 담아라.\n"
                "- 특정 시간대를 피하라는 요청(알바·학원·병원, '아침 9시부터 11시까지 안 돼') → 반드시 차단시간추가에 "
                "'월 09:00~11:00' 형식으로 담아라. 여러 요일이면 '월 수 09:00~11:00'. 시각은 HH:MM 24시간제.\n"
                "- '1교시 싫어/아침 수업 싫어' → 차단시간추가:['월 화 수 목 금 09:00~10:30']\n"
                "- 'OO 빼줘/듣기 싫어' → 제외과목추가. 현재 시간표 과목을 지칭하면(줄임말 포함) 그 정식 명칭으로 써라. "
                "예: 현재 과목에 '확률및통계'가 있는데 '확통 빼줘'라 하면 '확률및통계'.\n"
                "- 'OO 넣어줘/듣고 싶어' → 희망과목추가\n"
                "- 'OO은 고정해줘/유지해줘/그대로 둬/건들지 마' → 고정과목추가 / '고정 풀어줘' → 고정과목해제\n"
                "- 'OO를 다른 과목으로 대체/교체/바꿔줘' → 대체과목에 OO. "
                "제외과목추가에는 넣지 마라. 어떤 과목으로 채울지도 네가 정하지 마라 (재계산이 채운다).\n"
                "- '균형필수 과목으로 대체해줘/학문기초로 채워줘'처럼 채울 과목의 종류를 지정하면 → "
                "채움구분에 그 이수구분('균형필수'는 '균형교양필수', '학문기초'는 '학문기초교양필수').\n"
                "- '졸업요건 기준으로 채워줘/남은 필수 위주로 다시 짜줘' → 요건우선재계산:'켬'\n"
                "- 'OO를 2분반으로 바꿔줘/김OO 교수님 걸로 옮겨줘' → 분반지정에 {과목,분반,교수} (모르는 값은 빈 문자열). "
                "이건 과목을 빼는 게 아니므로 제외과목추가에 넣지 마라.\n"
                "- '오후 수업 위주로/늦게 시작하고 싶어' → 선호:'오후', 반대는 '오전'\n"
                "- '수업 붙여줘/공강 싫어' → 공강처리:'연강' / '긴 공강(우주공강)만 피해줘' → '큰공강'\n"
                "- '영어강의 빼줘'→영어강의제외:'켬', '팀플 싫어'→팀플제외:'켬', 'P/NP 빼줘'→PNP제외:'켬', "
                "'사이버강좌도 넣어줘'→사이버강좌:'켬', '건물 이동 줄여줘'→동선최적화:'켬' (반대 요청은 '끔')\n"
                "- 팀플·영어강의·P/NP처럼 과목의 '속성'을 빼달라는 요청은 제외과목추가에 넣지 말고 위 스위치만 켜라. "
                "제외과목추가에는 구체적인 과목 이름만 담아라.\n"
                f"현재 시간표 과목: {cur}"
            )},
            {"role": "user", "content": req.text},
        ],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "tt_delta", "schema": _NL_SCHEMA}},
    )
    try:
        delta = _json.loads(resp.choices[0].message.content)
    except Exception:
        return {"error": "요청을 이해하지 못했어요. 다르게 표현해 주시겠어요?"}

    # ── 모드 판정: 과목 추가/제거"만" 요청 + 현재 시간표 있음 → 직접 편집(나머지 과목 불변).
    #    다른 조건(공강·차단·선호 등) 변경이 섞이면 → 조건 병합 후 전체 재계산. ──
    adds = _nl_resolve_courses(delta.get("희망과목추가"), req.현재과목)
    removes = _nl_resolve_courses(delta.get("제외과목추가"), req.현재과목)
    pins = _nl_resolve_courses(delta.get("고정과목추가"), req.현재과목)
    unpins = _nl_resolve_courses(delta.get("고정과목해제"), req.현재과목)
    replaces = _nl_resolve_courses(delta.get("대체과목"), req.현재과목)
    sec_specs = delta.get("분반지정") or []
    fill = str(delta.get("채움구분") or "")
    req_first = delta.get("요건우선재계산") == "켬"
    other_change = bool(delta.get("공강요일추가") or delta.get("공강요일제거")
                        or delta.get("차단시간추가")
                        or delta.get("선호") in ("오전", "오후")
                        or delta.get("목표학점")
                        or delta.get("공강처리") in ("연강", "큰공강")
                        # 고정·대체·채움·분반지정·요건우선은 솔버를 다시 돌려야 반영됨 → 재계산 모드
                        or pins or unpins or replaces or sec_specs or fill or req_first
                        or any(delta.get(k) in ("켬", "끔") for k in
                               ("영어강의제외", "팀플제외", "PNP제외", "사이버강좌", "동선최적화")))
    if (adds or removes) and not other_change and req.현재시간표:
        result = _edit_timetable(req.profile, adds, removes, req.현재시간표)
        result["적용"] = {"요약": delta.get("요약", ""), "모드": "직접편집"}
        if adds:
            result["적용"]["희망과목추가"] = adds
        if removes:
            result["적용"]["제외과목추가"] = removes
        return result

    # 델타를 프로필(폼 상태)에 병합 — 과목명은 실제 개설명으로 확정
    p = req.profile.model_copy(deep=True)
    적용 = {"요약": delta.get("요약", ""), "모드": "재계산"}
    if delta.get("공강요일추가") or delta.get("공강요일제거"):
        days = [d for d in p.공강요일 if d not in (delta.get("공강요일제거") or [])]
        days += [d for d in (delta.get("공강요일추가") or []) if d not in days]
        p.공강요일 = days
        적용["공강요일"] = days
    if delta.get("차단시간추가"):
        p.차단시간 = p.차단시간 + [s for s in delta["차단시간추가"] if s not in p.차단시간]
        적용["차단시간추가"] = delta["차단시간추가"]
    if removes:
        p.제외과목 = p.제외과목 + [n for n in removes if n not in p.제외과목]
        적용["제외과목추가"] = removes
    if replaces:
        # 대체: 제외과목으로 돌려서 재계산이 그 자리를 다른 과목으로 채우게 한다
        p.제외과목 = p.제외과목 + [n for n in replaces if n not in p.제외과목]
        적용["대체과목"] = replaces
    if fill:
        # 채움구분: 재계산에서 이 이수구분 후보를 최우선으로 끌어올린다 (솔버가 처리).
        # 상한 = 현재 시간표에 있던 그 구분 개수 (대체 시 개수 유지, 새로 채우면 1개)
        p.채움구분 = fill
        적용["채움구분"] = fill
        if req.현재시간표:
            codes = {str(it.get("학수번호")) for it in req.현재시간표}
            cur_rows = _DF[_DF["학수번호"].astype(str).isin(codes)]
            cnt = int(cur_rows[cur_rows["이수구분"].astype(str) == fill]["학수번호"].nunique())
            p.채움상한 = max(cnt, 1)
    if req_first:
        # 요건우선: 시간표 생성은 원래 졸업요건 진단 기반 — 조건 변경 없이 재계산만 태운다
        적용["요건우선재계산"] = True
    if adds:
        p.희망과목 = p.희망과목 + [n for n in adds if n not in p.희망과목]
        적용["희망과목추가"] = adds
    if pins and req.현재시간표:
        # 과목명 → 현재시간표의 학수번호·분반·시간(현재과목과 같은 순서)으로 pin 추가
        for n in pins:
            if n in req.현재과목:
                i = req.현재과목.index(n)
                if i < len(req.현재시간표):
                    item = req.현재시간표[i]
                    if not any(str(g.get("학수번호")) == str(item.get("학수번호"))
                               and str(g.get("분반")) == str(item.get("분반"))
                               for g in p.고정과목):
                        p.고정과목 = p.고정과목 + [item]
        적용["고정과목추가"] = pins
    if unpins and p.고정과목:
        codes = set()
        for n in unpins:
            if n in req.현재과목:
                i = req.현재과목.index(n)
                if i < len(req.현재시간표):
                    codes.add(str(req.현재시간표[i].get("학수번호")))
        p.고정과목 = [g for g in p.고정과목 if str(g.get("학수번호")) not in codes]
        적용["고정과목해제"] = unpins
    if sec_specs:
        resolved = []
        for s in sec_specs:
            names_r = _nl_resolve_courses([s.get("과목")], req.현재과목)
            if not names_r:
                continue
            n = names_r[0]
            spec = dict(p.희망상세.get(n, {}))
            if s.get("분반"):
                spec["분반"] = str(s["분반"]).replace("분반", "").strip()
            if s.get("교수"):
                spec["교수"] = str(s["교수"]).strip()
            p.희망상세 = {**p.희망상세, n: spec}
            if n not in p.희망과목:
                p.희망과목 = p.희망과목 + [n]
            resolved.append({"과목": n, "분반": spec.get("분반", ""), "교수": spec.get("교수", "")})
        if resolved:
            적용["분반지정"] = resolved
    if delta.get("선호") in ("오전", "오후"):
        p.선호 = delta["선호"]; 적용["선호"] = delta["선호"]
    if delta.get("목표학점"):
        p.목표학점 = int(delta["목표학점"]); 적용["목표학점"] = p.목표학점
    if delta.get("공강처리") in ("연강", "큰공강"):
        p.공강처리 = delta["공강처리"]; 적용["공강처리"] = delta["공강처리"]
    for k in ("영어강의제외", "팀플제외", "PNP제외", "사이버강좌", "동선최적화"):
        if delta.get(k) in ("켬", "끔"):
            v = delta[k] == "켬"
            setattr(p, k, v); 적용[k] = v

    result = _recommend_alts(p)
    if "error" in result:
        return result
    result["적용"] = 적용
    return result


# ────────────────────────────────────────────────────────────────
# 프론트엔드 정적 파일 서빙
# ────────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=os.path.join(_ROOT, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(_ROOT, "static", "index.html"))