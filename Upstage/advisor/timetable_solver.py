# -*- coding: utf-8 -*-
"""
세종대 수강편람 자동화 — 시간표 솔버 (Phase 1)

강의시간표 엑셀(개설강좌)을 정형화하고, 학과+이수구분 기준으로
'들어야 할 과목' 후보를 뽑아, 시간 충돌 없는 시간표를 만든다.
오전/오후 선호를 반영한다. (건물 동선 비용은 이후 단계에서 추가)

무거운 연산/외부 API 없음 — 순수 결정론적 로직.

────────────────────────────────────────────────────────────────
[리뷰 노트 — 팀원용]  이 파일이 시간표 파트의 핵심이다. 읽는 순서:
  1) parse_times / parse_rooms  : 엑셀 '요일·시간'·'강의실' 텍스트 → (요일,시작분,종료분)·(건물,층)
  2) build_candidates           : 학과·이수구분·학년으로 후보 과목 생성(과목마다 여러 분반)
  3) solve                      : 백트래킹 제약충족 → 시간 안 겹치는 조합(충돌 0 보장).
                                  목표=우선순위 가중학점 최대, 선호·동선 벌점 최소
  4) movement_report            : 연강(붙은 수업) 사이 건물 이동시간 vs 쉬는시간(보수적 10분) 비교
  5) recommend_for_profile      : 위를 묶어 최종 추천 JSON 생성(server.py 가 호출하는 진입 함수)
검증: solve 결과를 sections_conflict 로 재검사하면 항상 충돌 0.
데이터: knowledge_base.CUR_XLSX(강의시간표) + poc_cache/{buildings,syllabus}.json
"""
import os
import re
import json
import math
import pandas as pd
from difflib import SequenceMatcher

DAYS = ["월", "화", "수", "목", "금", "토", "일"]
TIME_RE = re.compile(r"([월화수목금토일])\s*(\d{1,2}):(\d{2})\s*~\s*(\d{1,2}):(\d{2})")
ROOM_RE = re.compile(r"^([가-힣]+)\s*([A-Za-z]?)(\d+)?")


# ---------- 파싱 ----------
def parse_times(s):
    """요일별 시간 슬롯 파싱 → [(요일, 시작분, 종료분), ...]

    두 형식 모두 처리:
      '화 09:00~10:30, 화 18:00~19:00'  (요일마다 개별 시간)
      '화 목 15:00~16:30'               (여러 요일이 한 시간 공유)
    콤마로 나눈 각 파트 = 요일 1~2개 + 시간 1개.
    """
    if not isinstance(s, str):
        return []
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        head = re.match(r"^([월화수목금토일\s]+)", part)
        days = re.findall(r"[월화수목금토일]", head.group(1)) if head else []
        tm = re.search(r"(\d{1,2}):(\d{2})\s*~\s*(\d{1,2}):(\d{2})", part)
        if not days or not tm:
            continue
        h1, m1, h2, m2 = map(int, tm.groups())
        start, end = h1 * 60 + m1, h2 * 60 + m2
        for d in days:
            out.append((d, start, end))
    return out


def parse_rooms(s):
    """'집408, 학대공연장' → [(건물, 층), ...]  층=호수 첫자리(없으면 None)"""
    if not isinstance(s, str):
        return []
    out = []
    for token in s.split(","):
        token = token.strip()
        if not token:
            continue
        m = ROOM_RE.match(token)
        if not m:
            out.append((token, None)); continue
        bldg, wing, num = m.groups()               # wing='B' 이면 지하
        if not num:
            out.append((bldg, None)); continue
        floor = int(num[0])                          # 호수 앞자리 = 층 (408→4층)
        if (wing or "").upper() == "B":              # 'B' 접두 = 지하 → 층을 음수로 (센B201→지하2층)
            floor = -(floor if len(num) >= 3 else 1) # 3자리는 앞자리가 지하층, 07 같은 2자리는 지하1층
        out.append((bldg, floor))
    return out


def slots_overlap(a, b):
    """두 슬롯 (요일,시작,종료)이 같은 요일에 시간 겹치면 True"""
    if a[0] != b[0]:
        return False
    return a[1] < b[2] and b[1] < a[2]


def sections_conflict(sec_a, sec_b):
    """두 분반(섹션)의 슬롯 중 하나라도 겹치면 True"""
    for sa in sec_a["slots"]:
        for sb in sec_b["slots"]:
            if slots_overlap(sa, sb):
                return True
    return False


# ---------- 데이터 로드 ----------
def load_courses(xlsx_path, sheet="개설강좌"):
    """엑셀 → 정형 DataFrame (slots/rooms 컬럼 추가)"""
    df = pd.read_excel(xlsx_path, sheet_name=sheet)
    df["slots"] = df["요일 및 강의시간"].apply(parse_times)
    df["rooms"] = df["강의실"].apply(parse_rooms)
    return df


_GRADE_FAIL_MARKS = {"F", "NP", "W", "U", "R", "I", "재수강"}   # 미이수 등급 → '이미 들음'에서 제외


def parse_grade_excel(path_or_buf):
    """학사정보시스템 '기이수성적조회' 엑셀 → 이수한 과목 [{"과목","학점","성적"}] 리스트.

    - 잡음 행이 위에 있어 '교과목명'이 든 헤더 행을 자동 탐지한다.
    - 미이수(F·NP·W 등)는 제외 → 그 과목은 재수강 후보로 남는다.
    - 같은 과목이 여러 번(재수강)이면 마지막(최신) 기록을 남긴다.
    반환은 recommend_for_profile 의 profile["이수과목"] 형식과 동일하다.
    """
    raw = pd.read_excel(path_or_buf, sheet_name=0, header=None)
    hdr = next((i for i in range(min(12, len(raw)))
                if raw.iloc[i].astype(str).str.contains("교과목명").any()), None)
    if hdr is None:
        return []
    df = pd.read_excel(path_or_buf, sheet_name=0, header=hdr)
    col = lambda key: next((c for c in df.columns if key in str(c)), None)
    nm, cr, gr = col("교과목명"), col("학점"), col("등급")
    if nm is None:
        return []
    by = {}
    for _, r in df.iterrows():
        name = str(r.get(nm, "")).strip()
        if not name or name in ("nan", "교과목명"):
            continue
        grade = str(r.get(gr, "")).strip()
        if grade in _GRADE_FAIL_MARKS:
            continue
        try:
            credit = float(r.get(cr))
        except (TypeError, ValueError):
            credit = 3.0
        by[name] = {"과목": name, "학점": credit, "성적": grade or "P"}
    return list(by.values())


PRIORITY = {"전공필수": 1, "전공기초": 2, "공통교양필수": 3, "학문기초교양필수": 3,
            "균형교양필수": 4, "전공선택": 5}


def _year_col(df):
    return next(c for c in df.columns if "학년" in c)


def _is_cyber(sub):
    """사이버강좌(e-러닝/K-MOOC) 행 여부 — 시간이 없어도 수강 가능(충돌 없음)."""
    if "사이버강좌" not in sub.columns:
        return pd.Series(False, index=sub.index)
    return sub["사이버강좌"].notna() & (sub["사이버강좌"].astype(str).str.strip() != "")


def _col(row, key):
    """컬럼명 부분일치로 값 조회 (엑셀 헤더에 줄바꿈 포함: '메인\\n교수명' 등)."""
    for c in row.index:
        if key in str(c):
            return row[c]
    return None


def _make_sections(g):
    """분반 행들 → 섹션 리스트. 시간 없는 사이버강좌는 '시간 지정 없음'으로 표기."""
    sections = []
    for _, row in g.iterrows():
        no_time = len(row["slots"]) == 0
        raw_cyber = _col(row, "사이버")                       # '사이버강좌' 칸 값
        elearn = "" if pd.isna(raw_cyber) else str(raw_cyber).strip()  # '본교 e-러닝 강의' 등
        sections.append({
            "분반": row["분반"],
            "slots": row["slots"],
            "rooms": row["rooms"],
            "강의실": row["강의실"] if not no_time else "온라인",
            "시간": row["요일 및 강의시간"] if not no_time else "사이버(시간 지정 없음)",
            "사이버": no_time,               # 시간 무관(비점유) 여부 — 그리드 분리·별도표시용
            "이러닝": elearn or None,          # e-러닝/K-MOOC 표기(시간 있어도) — 라벨용
            "교수": _col(row, "교수명"),
            "언어": _col(row, "강의언어"),
        })
    return sections


def build_candidates(df, dept, 이수구분=("전공필수", "전공기초"), target_years=None,
                     include_cyber=False):
    """학과+이수구분 기준으로 '과목 후보' 생성. 과목(학수번호)마다 여러 분반(섹션).

    target_years: 예 (3,) 또는 (1,2,3) — 해당 학년 권장 과목만. None이면 전체.
    include_cyber: True면 시간 없는 사이버강좌(e-러닝/K-MOOC)도 후보에 포함
                   (시간 충돌 없이 학점을 채울 수 있음).
    """
    ycol = _year_col(df)
    sub = df[(df["개설학과전공"] == dept) & (df["이수구분"].isin(이수구분))].copy()
    has_time = sub["slots"].apply(len) > 0
    sub = sub[has_time | _is_cyber(sub)] if include_cyber else sub[has_time]
    if target_years is not None:
        sub = sub[pd.to_numeric(sub[ycol], errors="coerce").isin(target_years)]
    courses = []
    for hakbun, g in sub.groupby("학수번호"):
        r0 = g.iloc[0]
        courses.append({
            "학수번호": hakbun,
            "교과목명": r0["교과목명"],
            "이수구분": r0["이수구분"],
            "개설학과": r0["개설학과전공"],
            "학년": r0[ycol],
            "학점": float(r0["학점"]),
            "priority": PRIORITY.get(r0["이수구분"], 9),
            "sections": _make_sections(g),
        })
    # 우선순위(전공필수 먼저) → 학점 큰 것 먼저
    courses.sort(key=lambda c: (c["priority"], -c["학점"]))
    return courses


def build_courses_by_names(df, names, include_cyber=False):
    """과목명으로 전체 개설강좌에서 후보 생성 (학과 불문 — 교양·타학과 개설 포함).

    용도: 졸업요건 진단이 알려준 '남은 교양'(예: 취창업과진로역량개발, 세계사)을
          이번 학기 개설분에서 찾아 시간표 후보로 만든다.
    """
    ycol = _year_col(df)
    sub = df[df["교과목명"].isin(set(names))].copy()
    has_time = sub["slots"].apply(len) > 0
    sub = sub[has_time | _is_cyber(sub)] if include_cyber else sub[has_time]
    courses = []
    for hakbun, g in sub.groupby("학수번호"):
        r0 = g.iloc[0]
        courses.append({
            "학수번호": hakbun, "교과목명": r0["교과목명"], "이수구분": r0["이수구분"],
            "개설학과": r0["개설학과전공"],
            "학년": r0[ycol], "학점": float(r0["학점"]),
            "priority": PRIORITY.get(r0["이수구분"], 9), "sections": _make_sections(g),
        })
    courses.sort(key=lambda c: (c["priority"], -c["학점"]))
    return courses


def explore_offerings(df, course_name, eqmap=None, prefer="오전"):
    """타학과 수업 탐색: 한 과목(공식 동일과목 포함)이 개설된 **모든 학과** 분반을
    선호 시간대 순으로 나열한다.

    용도: "내 학과 분반은 시간이 안 맞는데, 같은(동일 인정) 과목을 다른 학과에서
          더 좋은 시간대에 들을 수 없나?" — 복수전공·전과생의 타학과 탐색도 동일.
    반환 예: [{"교과목명":"확률및통계","개설학과":"AI로봇학과","분반":2,
              "시간":"월 수 09:00~10:30","강의실":"충B103","선호벌점":0}, ...]
    """
    names = {course_name} | set((eqmap or {}).get(course_name, []))
    rows = []
    seen = set()                                  # 교차개설(같은 분반이 여러 학과 행) 중복 제거
    for c in build_courses_by_names(df, names):
        for s in c["sections"]:
            key = (c["교과목명"], str(s["분반"]), s["시간"])
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "교과목명": c["교과목명"], "개설학과": c["개설학과"],
                "이수구분": c["이수구분"], "학점": c["학점"],
                "분반": s["분반"], "시간": s["시간"], "강의실": s["강의실"],
                "선호벌점": pref_penalty(s, prefer),
                "동일과목": c["교과목명"] != course_name,   # 다른 이름(동일 인정)이면 표시
            })
    rows.sort(key=lambda r: (r["선호벌점"], r["교과목명"]))
    return rows


# ---------- 이수 필터 (이미 들은 과목 제외) ----------
def load_rename_map(path):
    """수강편람에서 추출한 과목명 변경 맵 {현재명: [변경전명,...]} 로드. 없으면 빈 dict."""
    if path and os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {}


_MARKERS = ("고급", "기초", "심화", "초급", "중급")


def detect_renames(old_xlsx, cur_xlsx, dept, thr=0.75):
    """작년 vs 올해 강의시간표를 비교해 이름 바뀐 과목 자동 감지 → {현재명: [옛이름,...]}.

    세종대는 개편 시 학수번호도 새로 발급 → 코드 매칭 불가. 그래서 '같은 학과 + 이름 유사도'.
    오탐 방지: 후속편(끝자리 숫자 차이)·고급/기초 접두어 차이는 rename 아님으로 제외.
    이름만 매칭이라 100%는 아님 → 사용자 확인 권장.
    """
    def dept_names(path):
        df = pd.read_excel(path, sheet_name=0)
        sub = df[df["개설학과전공"] == dept]
        return set(sub["교과목명"].astype(str).str.strip())

    def strip_seq(s):
        return re.sub(r"\d+$", "", s).strip()

    cur_names, old_names = dept_names(cur_xlsx), dept_names(old_xlsx)
    renames = {}
    for o in old_names:
        if o in cur_names:                         # 올해도 그대로 있으면 rename 아님
            continue
        best, best_s = None, 0.0
        for c in cur_names:
            if c in old_names:                     # 새 이름이 작년에도 있었으면 제외
                continue
            if strip_seq(o) == strip_seq(c) and o != c:        # 후속편(1/2)
                continue
            if any(o == m + c or c == m + o for m in _MARKERS):  # 고급/기초 접두어 차이
                continue
            s = SequenceMatcher(None, o, c).ratio()
            if o in c or c in o:                   # 부분문자열 → 강한 신호
                s = max(s, 0.85)
            if s > best_s:
                best, best_s = c, s
        if best and best_s >= thr:
            renames.setdefault(best, []).append(o)
    return renames


def filter_taken(courses, taken_names=(), taken_codes=(), rename_map=None, equiv_map=None):
    """이미 이수한 것으로 판정되는 과목을 가려낸다.

    확실(확인필요=False): 과목명/학수번호 일치, **공식 동일과목**(equiv_map, 학교 동일과목조회 데이터).
    추측(확인필요=True): 이름 유사도 자동감지(rename_map) — 사용자 확인 후 적용 권장.
    반환: (남긴 후보, 제외후보[제외사유·확인필요 포함])
    """
    taken_names = set(taken_names)
    taken_codes = {str(c) for c in taken_codes}
    rename_map = rename_map or {}
    equiv_map = equiv_map or {}
    kept, removed = [], []
    for c in courses:
        name, code = c["교과목명"], str(c["학수번호"])
        matched_equiv = set(equiv_map.get(name, [])) & taken_names   # 공식 동일과목
        matched_old = set(rename_map.get(name, [])) & taken_names    # 이름 유사도(추측)
        if name in taken_names:
            removed.append({**c, "제외사유": "직접 이수", "확인필요": False, "매칭": name})
        elif code in taken_codes:
            removed.append({**c, "제외사유": "학수번호 이수", "확인필요": False, "매칭": code})
        elif matched_equiv:
            old = sorted(matched_equiv)[0]
            removed.append({**c, "제외사유": f"공식 동일과목({old}={name})",
                            "확인필요": False, "매칭": old})
        elif matched_old:
            old = sorted(matched_old)[0]
            removed.append({**c, "제외사유": f"이름변경 자동감지({old}→{name})",
                            "확인필요": True, "매칭": old})
        else:
            kept.append(c)
    return kept, removed


# ---------- 선호 점수 ----------
def pref_penalty(section, prefer):
    """오전선호면 오후/저녁 슬롯에 벌점, 오후선호면 오전 슬롯에 벌점. 낮을수록 좋음."""
    pen = 0
    for _day, start, _end in section["slots"]:
        if prefer == "오전" and start >= 12 * 60:
            pen += 1
        elif prefer == "오후" and start < 12 * 60:
            pen += 1
    return pen


def apply_section_filters(courses, profile):
    """프로필의 하드 조건에 맞는 분반만 남긴다. 조건에 맞는 분반이 하나도 없는
    과목은 제외하되, 왜 빠졌는지 목록으로 돌려준다(조용히 빼지 않음 — 사용자 확인용).

    프로필 키:
    - "공강요일": ["금"] — 그 요일 수업 전부 제외 (금공강 등)
    - "차단시간": ["월 09:00~10:30", "화 18:00~21:00"] — 알바·학원 등 고정 일정,
                  기피 시간대(1교시 등)도 같은 방식으로 입력. 겹치는 분반 제외.
    - "제외과목": ["대학물리1", ...] — 안 들을 과목. 이름이 일치하는 과목은 통째로 제외.
    - "영어강의제외": True — 강의언어에 '영어' 포함 분반 제외
      (P/NP 여부는 강의시간표에 없음 — 강의계획서 수집 후 지원 예정)
    """
    off_days = set(profile.get("공강요일", []))
    blocks = []
    for s in profile.get("차단시간", []):
        blocks += parse_times(s)
    exclude = {n.strip() for n in profile.get("제외과목", []) if n.strip()}
    no_eng = bool(profile.get("영어강의제외"))
    if not (off_days or blocks or exclude or no_eng):
        return courses, []
    kept, dropped = [], []
    for c in courses:
        if str(c["교과목명"]).strip() in exclude:          # 사용자가 안 들겠다고 지정한 과목 → 통째 제외
            dropped.append({"교과목명": c["교과목명"], "이수구분": c["이수구분"],
                            "사유": "사용자가 제외한 과목"})
            continue
        secs = []
        for s in c["sections"]:
            if any(d in off_days for d, _s, _e in s["slots"]):
                continue
            if any(slots_overlap(a, b) for a in s["slots"] for b in blocks):
                continue
            if no_eng and "영어" in str(s.get("언어") or ""):
                continue
            secs.append(s)
        if secs:
            kept.append({**c, "sections": secs})
        else:
            dropped.append({"교과목명": c["교과목명"], "이수구분": c["이수구분"],
                            "사유": "공강요일·차단시간·언어 조건에 맞는 분반 없음"})
    return kept, dropped


def prereq_warnings(chosen, taken_names=(), prereq_map=None, equiv_map=None):
    """추천 시간표 과목 중 '선수과목 미이수'를 경고 목록으로 돌려준다.

    prereq_map: syllabus_collector.collect()가 만든 {과목명: {"선수과목":[...], "권장":bool}}.
    taken_names: 이수 과목명(동일과목 포함 판정에 equiv_map 사용).
    반환: [{"과목":..., "선수과목":..., "권장":bool}] — 안 들은 선수과목만.
    """
    prereq_map = prereq_map or {}
    equiv_map = equiv_map or {}
    taken = set(taken_names)
    # 동일과목까지 이수로 인정
    for t in list(taken):
        taken.update(equiv_map.get(t, []))
    warns = []
    for c in chosen:
        info = prereq_map.get(c["교과목명"])
        if not info or not info.get("선수과목"):
            continue
        for pre in info["선수과목"]:
            names = {pre} | set(equiv_map.get(pre, []))
            if not (names & taken):
                warns.append({"과목": c["교과목명"], "선수과목": pre,
                              "권장": info.get("권장", False)})
    return warns


def load_syllabus_map(path=None):
    """수집된 강의계획서 JSON 로드 {과목명: {선수과목,평가방법,과제물,팀플,PNP,...}}.
    syllabus.json 우선, 없으면 옛 prereq.json. 없으면 빈 dict(계획서 기능 비활성)."""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "cache", "poc_cache", "syllabus")   # advisor/ → ROOT/cache/poc_cache
    for p in ([path] if path else [os.path.join(base, "syllabus.json"),
                                    os.path.join(base, "prereq.json")]):
        if p and os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    return {}


# 하위호환 별칭 (선수과목 경고에서 사용)
load_prereq_map = load_syllabus_map


def apply_syllabus_filters(courses, profile, syl_map):
    """강의계획서 기반 과목 제외. 조건에 걸린 과목은 목록으로 돌려준다(조용히 안 뺌).

    프로필 키: "팀플제외"(팀 프로젝트 있는 강의 제외), "PNP제외"(P/NP 성적 강의 제외).
    """
    if not syl_map or not (profile.get("팀플제외") or profile.get("PNP제외")):
        return courses, []
    kept, dropped = [], []
    for c in courses:
        s = syl_map.get(c["교과목명"], {})
        if profile.get("팀플제외") and s.get("팀플"):
            dropped.append({"교과목명": c["교과목명"], "사유": "팀 프로젝트 포함(계획서)"})
            continue
        if profile.get("PNP제외") and s.get("PNP"):
            dropped.append({"교과목명": c["교과목명"], "사유": "P/NP 성적(계획서)"})
            continue
        kept.append(c)
    return kept, dropped


def annotate_syllabus(chosen, syl_map):
    """추천 과목에 계획서 정보(평가방법·과제물·팀플·P/NP) 부착 — 표시용."""
    for c in chosen:
        s = syl_map.get(c["교과목명"])
        if s:
            c["계획서"] = {k: s[k] for k in ("평가방법", "과제물", "팀플", "PNP", "강의개선")
                        if k in s}
    return chosen


def _day_gaps(chosen):
    """확정된 조합의 요일별 공강 통계 → (총 공강 분, 3시간 이상 '우주공강' 개수)."""
    by_day = {}
    for c in chosen:
        for d, s, e in c["sec"]["slots"]:
            by_day.setdefault(d, []).append((s, e))
    total, big = 0, 0
    for iv in by_day.values():
        iv.sort()
        for (_s1, e1), (s2, _e2) in zip(iv, iv[1:]):
            gap = s2 - e1
            if gap > 0:
                total += gap
                if gap >= 180:
                    big += 1
    return total, big


# ---------- 건물 간 이동(동선) 비용 ----------
# 세종대 수업은 보통 마지막에 일찍 끝나지만(90분→15분, 연속강의→10분 등) 교수마다 편차가
# 커서(2시간30분 쭉 하고 30분 먼저 끝내는 경우도 있음), 이동 가능 시간을 **보수적으로 10분**
# 고정으로 잡는다. → 연속 수업 사이 이동 가능 시간 = (다음 시작 - 이전 종료) + 10분.
BREAK_BUFFER_MIN = 10       # 조기종료 버퍼(보수적 고정)
WALK_M_PER_MIN = 75.0       # 도보 속도 ≈ 4.5km/h (캠퍼스 혼잡 감안)
ASCENT_MIN_PER_M = 0.1      # Naismith 규칙: 오르막 10m당 +1분
FLOOR_MIN = 0.4             # 층 이동 1개층당(계단/엘리베이터 평균)

_BUILDINGS = None


def _buildings():
    """poc_cache/buildings.json 건물 좌표·지형고도 (1회 로드)."""
    global _BUILDINGS
    if _BUILDINGS is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "cache", "poc_cache", "buildings.json")   # advisor/ → ROOT/cache/poc_cache
        try:
            _BUILDINGS = json.load(open(path, encoding="utf-8"))["건물"]
        except Exception:
            _BUILDINGS = {}
    return _BUILDINGS


def _haversine_m(a, b):
    R = 6371000
    la1, lo1, la2, lo2 = map(math.radians, [a["lat"], a["lng"], b["lat"], b["lng"]])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _primary_room(sec):
    """섹션의 대표 강의실 (건물약칭, 층). 온라인/미배정이면 None."""
    for ab, fl in (sec.get("rooms") or []):
        if ab and ab != "nan":
            return ab, fl
    return None


def move_minutes(sec_a, sec_b):
    """두 분반 강의실 간 도보 이동시간(분). 수평(하버사인)+오르막(Naismith)+층 이동.
    좌표/건물 미상이거나 온라인이면 None(경고 대상에서 제외)."""
    ra, rb = _primary_room(sec_a), _primary_room(sec_b)
    if not ra or not rb:
        return None
    (ab_a, fl_a), (ab_b, fl_b) = ra, rb
    B = _buildings()
    ba, bb = B.get(ab_a), B.get(ab_b)
    if not ba or not bb or ba.get("lat") is None or bb.get("lat") is None:
        return None
    if ab_a == ab_b:                                   # 같은 건물 — 층 이동만
        return round(abs((fl_a or 1) - (fl_b or 1)) * FLOOR_MIN, 1)
    dist = _haversine_m(ba, bb)
    climb = max(0.0, (bb.get("지형고도_m") or 0) - (ba.get("지형고도_m") or 0))  # 오르막만
    floors = abs((fl_a or 1) - 1) + abs((fl_b or 1) - 1)   # 각 방을 1층 출입구까지 오르내리는 층수(지하는 음수→abs)
    return round(dist / WALK_M_PER_MIN + climb * ASCENT_MIN_PER_M + floors * FLOOR_MIN, 1)


def movement_report(chosen):
    """같은 날 연속 수업 사이의 '건물 이동'을 모두 보고한다(공강이 있어도 표시).
    이동 여유시간 = 두 수업 사이 공강 시간(바로 붙어 있으면 쉬는시간 버퍼 10분).
    ok=False면 도보시간 > 여유시간(촉박). 온라인(e-러닝/사이버)·같은 건물·좌표미상은 제외."""
    by_day = {}
    for c in chosen:
        if c["sec"].get("사이버") or c["sec"].get("이러닝"):   # 온라인 — 이동 없음
            continue
        for d, s, e in c["sec"]["slots"]:
            by_day.setdefault(d, []).append((s, e, c))
    rows = []
    for d, items in by_day.items():
        items.sort(key=lambda x: x[0])
        for (s1, e1, c1), (s2, _e2, c2) in zip(items, items[1:]):
            if c1 is c2:                               # 같은 과목의 다른 슬롯 — 이동 아님
                continue
            ra, rb = _primary_room(c1["sec"]), _primary_room(c2["sec"])
            if not ra or not rb or ra[0] == rb[0]:     # 온라인이거나 같은 건물 — 이동 없음
                continue
            mv = move_minutes(c1["sec"], c2["sec"])
            if mv is None:
                continue
            gap = s2 - e1
            avail = gap if gap > 0 else BREAK_BUFFER_MIN   # 공강 있으면 그만큼, 붙어있으면 버퍼
            rows.append({
                "요일": d, "이동분": mv, "여유분": avail,
                "ok": mv <= avail,
                "이전": c1["교과목명"], "이전강의실": c1["sec"].get("강의실"),
                "다음": c2["교과목명"], "다음강의실": c2["sec"].get("강의실"),
            })
    return rows


def movement_warnings(chosen):
    """이동이 촉박한(도보>쉬는시간) 전이만."""
    return [r for r in movement_report(chosen) if not r["ok"]]


def total_walk_minutes(chosen):
    """같은 날 연속 수업(공강 무관) 사이 건물 이동 도보시간 합(분). 동선 최적화 벌점용.
    붙은 수업뿐 아니라 하루 전체 이동을 줄이도록 유도(캠퍼스가 크고 높을수록 효과 큼)."""
    by_day = {}
    for c in chosen:
        if c["sec"].get("사이버") or c["sec"].get("이러닝"):   # 온라인 — 이동 없음(벌점 제외)
            continue
        for d, s, e in c["sec"]["slots"]:
            by_day.setdefault(d, []).append((s, e, c))
    total = 0.0
    for items in by_day.values():
        items.sort(key=lambda x: x[0])
        for (_s1, _e1, c1), (_s2, _e2, c2) in zip(items, items[1:]):
            if c1 is c2:
                continue
            mv = move_minutes(c1["sec"], c2["sec"])
            if mv:
                total += mv
    return total


# ---------- 솔버 (백트래킹) ----------
def solve(courses, target_credits=18, prefer="오전", max_courses=8, group_limits=None,
          prefs=None, fixed=None):
    """
    후보 과목들 중 시간 충돌 없는 조합을 고른다.
    목표: (1) 우선순위 가중 학점 최대  (2) 선호 벌점 최소.
    target_credits 근처까지, 과목 수 max_courses 이내.
    group_limits: 이수구분별 최대 과목 수. 예 {"균형교양필수": 1}
                  (균형교양은 3학점만 남았으면 한 과목이면 충분 — 후보가 많아도 1개만 담게)
                  대분류 키 "전공"/"교양"도 가능 — 이수구분에 그 단어가 포함되면 집계
                  (예 {"전공": 4, "교양": 2} → 전공 계열 4과목, 교양 계열 2과목까지).
    prefs: 소프트 선호(벌점에 반영, 학점 확보가 항상 우선).
      - "연강선호": True — 수업 사이 공강 30분당 벌점 1 (연강 위주로 붙임)
      - "우주공강방지": True — 같은 날 3시간 이상 공강 1개당 벌점 10
      - "선호교수": ["홍길동"] — 그 교수 분반을 같은 과목 내에서 최우선 선택
      - "동선최적화": True — 건물 이동 도보시간(분)을 벌점에 반영해 동선 좋은 조합 우선.
                    캠퍼스가 크고 높은 학교(상명대·서울대 등)에서 ON. 작은 캠퍼스는 OFF해
                    더 다양한 시간표 허용. (하드 조건 아님 — 학점 확보가 항상 우선)
      - "우선순위가중치": {"시간대": 4, "공강": 2, "동선": 1} — 소프트 조건별 상대 가중치.
                    사용자가 정한 우선순위(1순위=4배, 2순위=2배, 3순위=1배, 동순위 허용)로
                    벌점을 곱해, 조건끼리 충돌할 때 상위 순위가 우선 반영되게 한다. 없으면 전부 1.
    """
    best = {"score": (-1, -1, -1, 1), "chosen": []}   # score=(필수희망수, 선호희망수, 가중학점, -벌점)  클수록 좋음
    group_limits = group_limits or {}
    prefs = prefs or {}
    fixed = fixed or []                            # pin: 항상 포함할 고정 과목(미리 배치)
    like_prof = [p.strip() for p in prefs.get("선호교수", []) if p.strip()]
    rank_w = prefs.get("우선순위가중치") or {}
    w_time = rank_w.get("시간대", 1)
    w_gap = rank_w.get("공강", 1)
    w_walk = rank_w.get("동선", 1)

    def gcount(chosen, key):
        if key in ("전공", "교양"):                 # 대분류: 이수구분에 단어 포함
            return sum(1 for c in chosen if key in str(c["이수구분"]))
        return sum(1 for c in chosen if c["이수구분"] == key)

    def weighted(chosen):
        # 점수 비교 순서: (1) '꼭' 희망 수  (2) '되도록' 희망 수  (3) 우선순위 가중 학점  (4) 선호 벌점.
        # 희망과목을 최우선으로 둬서, 넣을 수만 있으면(충돌만 없으면) 학점 트레이드오프에
        # 밀려 조용히 빠지지 않게 한다. '꼭'으로 표시한 희망은 '되도록' 희망보다 먼저 지킨다
        # (둘이 충돌하면 '꼭'을 남긴다).
        must_hope = sum(1 for c in chosen if c.get("필수희망"))
        soft_hope = sum(1 for c in chosen if c.get("트랙") == "희망" and not c.get("필수희망"))
        wc = sum((10 - c["priority"]) * c["credits"] for c in chosen)  # 필수일수록 가중↑
        pen = w_time * sum(c["pen"] for c in chosen)
        if prefs.get("연강선호") or prefs.get("우주공강방지"):
            total_gap, big_gap = _day_gaps(chosen)
            if prefs.get("우주공강방지"):
                pen += w_gap * 10 * big_gap
            if prefs.get("연강선호"):
                pen += w_gap * (total_gap // 30)
        if prefs.get("동선최적화"):
            pen += w_walk * round(total_walk_minutes(chosen))    # 건물 이동 도보시간(분)만큼 벌점
        return (must_hope, soft_hope, round(wc, 1), -pen)

    def dfs(i, chosen, used_sections, credits):
        # 현재 조합 평가
        sc = weighted(chosen)
        if sc > best["score"]:
            best["score"] = sc
            best["chosen"] = list(chosen)
        if (i >= len(courses) or credits >= target_credits
                or len(chosen) >= max_courses):
            return
        for j in range(i, len(courses)):
            course = courses[j]
            if credits + course["학점"] > target_credits + 0.5:
                continue
            gu = str(course["이수구분"])
            over_limit = any(
                gcount(chosen, key) >= lim
                for key, lim in group_limits.items()
                if (key == gu) or (key in ("전공", "교양") and key in gu))
            if over_limit:
                continue
            # 이 과목의 각 분반 시도 — 선호교수 최우선, 그다음 (시간대 벌점 × 가중치 +
            # 이미 담은 과목과의 예상 도보시간 × 가중치)가 낮은 순. 우선순위 가중치에 따라
            # '선호 시간대'와 '동선' 중 무엇이 분반 선택을 주도할지 결정된다.
            def sec_key(s, _chosen=chosen):
                walk_pen = 0.0
                if prefs.get("동선최적화"):
                    days = {d for d, _s, _e in s["slots"]}
                    for c in _chosen:
                        if days & {d for d, _s, _e in c["sec"]["slots"]}:   # 같은 요일만
                            mv = move_minutes(s, c["sec"])
                            if mv:
                                walk_pen += mv
                return (0 if any(p in str(s.get("교수") or "") for p in like_prof) else 1,
                        w_time * pref_penalty(s, prefer) + w_walk * walk_pen)
            secs = sorted(course["sections"], key=sec_key)
            for sec in secs:
                if any(sections_conflict(sec, u) for u in used_sections):
                    continue
                chosen.append({**course, "credits": course["학점"],
                               "sec": sec, "pen": pref_penalty(sec, prefer)})
                dfs(j + 1, chosen, used_sections + [sec], credits + course["학점"])
                chosen.pop()
                break   # 한 과목당 충돌 없는 첫(=선호 최적) 분반만 — 탐색 폭 제한

    # 고정 과목을 미리 배치한 상태에서 탐색 시작 — 나머지가 그 시간을 피해 짜이고
    # best도 항상 고정 과목을 포함하게 된다(pin이 절대 빠지지 않음).
    dfs(0, list(fixed), [c["sec"] for c in fixed],
        sum(c["credits"] for c in fixed))
    return best["chosen"]


# ---------- 프로필 기반 추천 ----------
GRADE_FAIL = {"F", "NP", "W", "U", "재수강"}   # 미이수 → 다시 들어야 함


def recommend_for_profile(profile, cur_xlsx, old_xlsx, rename_json,
                          target_credits=15, use_rename=False,
                          equiv_map=None, extra_courses=None, group_limits=None,
                          df=None, fixed_courses=None):
    """프로필(학과·학년·이수과목·성적·선호)로 개인 맞춤 추천 시간표 생성.

    - 학년은 직접 입력받는다 (F 재수강 등으로 이수학점 기반 추정은 부정확하므로).
    - 성적이 F/W 등이면 미이수로 보고 다시 후보에 포함
    - equiv_map: 학교 공식 동일과목 데이터 — 옛 이름으로 이수한 과목을 확실하게 제외.
    - use_rename: 이름 유사도 자동감지(추측). 오탐이 있어 기본 OFF — 공식 equiv_map을 쓰라.
    - extra_courses: 전공 외 추가 후보(예: 졸업요건에서 나온 남은 교양). 함께 시간표에 배치.
    - group_limits: 이수구분별 최대 과목 수 (예: 균형교양필수 1개면 충분).
    - 이미 이수한 과목은 제외 / 현재 학년까지 전공필수·기초 catch-up + 현재 학년 전공선택

    프로필 추가 키(선택):
    - "희망과목": [과목명,...] — 반드시 넣고 싶은 강의. 최우선(priority 0)으로 배치하고
                  나머지를 그 주변에 짠다. 동일과목명·타학과 개설분도 자동 포함.
                  **리스트 순서 = 우선순위** (앞에 쓴 과목이 충돌 시 먼저 배치됨).
    - "복수전공": 학과명 — 그 학과의 전공필수/기초도 후보에 합류(복수전공 요건 채우기).
                  전과생은 "학과"를 새 학과로 쓰면 됨(이수과목은 그대로 인정 판정).
    - 하드 조건: "공강요일"·"차단시간"·"제외과목"·"영어강의제외" → apply_section_filters 참조.
    - 소프트 조건: "연강선호"·"우주공강방지"·"선호교수" → solve의 prefs 참조.
    - 계절학기는 정규 강의시간표 파일에 없음 — 계절 개설 엑셀 확보 시 같은 방식 적용.
    """
    dept = profile["학과"]
    현재학년 = profile["학년"]                     # 직접 입력 (이수학점으로 추정하지 않음)
    if df is None:                                # 호출측이 미리 로드한 df를 주면 재사용(대안 생성 시 반복 로드 방지)
        df = load_courses(cur_xlsx)

    passed = [c for c in profile.get("이수과목", []) if c.get("성적") not in GRADE_FAIL]
    taken_names = [c["과목"] for c in passed]
    총이수학점 = profile.get("총이수학점") or sum(c.get("학점", 0) for c in passed)  # 졸업 남은학점 표시용

    rename_map = {}
    if use_rename:                                  # 기본 OFF — 오탐(창업과기업가정신≠취창업과진로설계) 방지
        rename_map = load_rename_map(rename_json)
        for new, olds in detect_renames(old_xlsx, cur_xlsx, dept).items():
            rename_map.setdefault(new, []).extend(olds)

    include_cyber = bool(profile.get("사이버강좌"))    # 사이버강좌(시간무관) 포함 여부

    # 전공필수/기초: 1~현재학년(놓친 하위학년 필수 catch-up) / 전공선택: 현재학년만
    must = build_candidates(df, dept, 이수구분=("전공필수", "전공기초"),
                            target_years=tuple(range(1, 현재학년 + 1)),
                            include_cyber=include_cyber)
    elective = build_candidates(df, dept, 이수구분=("전공선택",),
                                target_years=(현재학년,), include_cyber=include_cyber)
    pool = must + elective + list(extra_courses or [])

    # 복수전공: 그 학과의 전공필수/기초를 후보에 합류
    if profile.get("복수전공"):
        dm = build_candidates(df, profile["복수전공"], 이수구분=("전공필수", "전공기초"),
                              target_years=tuple(range(1, 현재학년 + 1)),
                              include_cyber=include_cyber)
        for c in dm:
            c["트랙"] = "복수전공"
        pool += dm

    # 희망과목: 최우선(priority 0 근처)으로 배치. 리스트 순서가 우선순위.
    # 사용자가 입력한 '정확한 이름'이 이번 학기 개설돼 있으면 그것만 쓴다.
    # 정확한 이름이 개설 안 됐을 때만 공식 동일과목(다른 이름, 예: 취창업과진로설계→
    # 취창업과진로역량개발)으로 폴백한다 — 세계사를 넣었는데 World history가 딸려오는 중복 방지.
    희망상세 = profile.get("희망상세") or {}
    for rank, w in enumerate(profile.get("희망과목", [])):
        # 희망과목은 사용자가 이름을 콕 집은 것 → 사이버강좌라도 후보에 넣는다.
        # ('사이버강좌 포함' 토글은 학점 채우기용 자동 추가 여부일 뿐, 명시 요청까지 막지 않음)
        cands_w = build_courses_by_names(df, {w}, include_cyber=True)
        if not cands_w:                                     # 정확한 이름 미개설 → 동일과목 폴백
            names = {w} | set((equiv_map or {}).get(w, []))
            cands_w = build_courses_by_names(df, names, include_cyber=True)
        # 교수·분반 지정: 그 조건에 맞는 분반만 남긴다(빈 값=상관없음). 정확한 이름에만 적용.
        spec = 희망상세.get(w) or {}
        want_prof = str(spec.get("교수") or "").strip()
        want_sec = str(spec.get("분반") or "").strip()
        must = str(spec.get("중요도") or "") == "필수"     # '꼭 넣기' → 선호 희망보다 우선
        for c in cands_w:
            if (want_prof or want_sec) and c["교과목명"] == w:
                filt = [s for s in c["sections"]
                        if (not want_prof or str(s.get("교수") or "").strip() == want_prof)
                        and (not want_sec or str(s.get("분반")).strip() == want_sec)]
                if filt:                                    # 맞는 분반 있으면 그것만, 없으면 원래대로
                    c["sections"] = filt
            c["priority"] = rank * 0.05 + (0 if c["교과목명"] == w else 0.02)
            c["트랙"] = "희망"
            if must:
                c["필수희망"] = True
            pool.append(c)

    # 전공/교양 개수 상한 (예: 전공 4과목 + 교양 2과목)
    group_limits = dict(group_limits or {})
    if profile.get("전공개수"):
        group_limits["전공"] = int(profile["전공개수"])
    if profile.get("교양개수"):
        group_limits["교양"] = int(profile["교양개수"])

    # 소프트 선호(벌점 반영) — solve로 전달
    prefs = {"연강선호": profile.get("연강선호"),
             "우주공강방지": profile.get("우주공강방지"),
             "동선최적화": profile.get("동선최적화"),
             "선호교수": profile.get("선호교수", []),
             "우선순위가중치": profile.get("우선순위가중치")}   # 사용자 지정 소프트조건 우선순위

    syl_map = load_syllabus_map()

    # pin(고정 과목): 후보풀·이수판정에서 빼고 solve에 seed로 넘겨 항상 포함시킨다.
    fixed_courses = fixed_courses or []
    fixed_codes = {str(c["학수번호"]) for c in fixed_courses}

    def _dedup_solve(pool_):
        """같은 과목이 여러 경로로 들어오면 우선순위 높은 것만 남기고 풀이."""
        pool_, dropped_ = apply_section_filters(pool_, profile)   # 하드 조건 먼저
        pool_, dropped_syl = apply_syllabus_filters(pool_, profile, syl_map)  # 계획서 조건
        dropped_ = dropped_ + dropped_syl
        dedup = {}
        for c in pool_:
            k = str(c["학수번호"])
            if k in fixed_codes:                    # 고정 과목은 seed로 이미 들어감 → 중복 방지
                continue
            if k not in dedup or c["priority"] < dedup[k]["priority"]:
                dedup[k] = c
        # 채움구분(말로 조정: '균형필수로 채워줘'): 그 이수구분 후보를 최우선으로 끌어올림
        # (희망과목은 이미 0 근처라 그대로 둠)
        fill_ = str(profile.get("채움구분") or "")
        if fill_:
            for c in dedup.values():
                if str(c["이수구분"]) == fill_ and c.get("트랙") != "희망":
                    c["priority"] = min(c["priority"], 0.5)
        cands_ = sorted(dedup.values(), key=lambda c: (c["priority"], -c["학점"]))
        cands_, removed_ = filter_taken(cands_, taken_names=taken_names,
                                        rename_map=rename_map, equiv_map=equiv_map)
        chosen_ = solve(cands_, target_credits=target_credits,
                        prefer=profile.get("선호", "오전"), group_limits=group_limits,
                        prefs=prefs, fixed=fixed_courses)
        return cands_, removed_, chosen_, dropped_

    cands, removed, chosen, dropped = _dedup_solve(pool)

    # 목표학점에 크게 못 미치면(개설 적은 학과 등) 탐색 풀 확장: 전공선택을 전 학년으로
    if sum(c["credits"] for c in chosen) < target_credits - 2.5:
        elective_all = build_candidates(df, dept, 이수구분=("전공선택",),
                                        target_years=(1, 2, 3, 4),
                                        include_cyber=include_cyber)
        for c in elective_all:
            c.setdefault("트랙", "타학년")
        cands2, removed2, chosen2, dropped2 = _dedup_solve(pool + elective_all)
        if sum(c["credits"] for c in chosen2) > sum(c["credits"] for c in chosen):
            cands, removed, chosen, dropped = cands2, removed2, chosen2, dropped2
    남은필수 = [c["교과목명"] for c in cands
             if c["이수구분"] in ("전공필수", "전공기초")]
    # 선수과목 미이수 경고 + 계획서 정보(평가·과제·팀플) 부착 (수집분 있을 때만)
    선수경고 = prereq_warnings(chosen, taken_names=taken_names,
                           prereq_map=syl_map, equiv_map=equiv_map)
    annotate_syllabus(chosen, syl_map)
    return {
        "현재학년": 현재학년, "총이수학점": 총이수학점,
        "이수인식_제외후보": removed,   # 확정 아님 — 사용자 확인용(제외사유·확인필요 포함)
        "조건제외": dropped,            # 공강요일·차단시간·교수·언어 조건으로 빠진 과목
        "선수과목경고": 선수경고,        # 선수과목 미이수(권장/필수 표시)
        "이동동선": movement_report(chosen),   # 건물 이동 전이(정상 포함, ok=False면 촉박)
        "아직_안들은_전공필수기초": 남은필수,
        "추천시간표": chosen,
    }


# ---------- 출력 ----------
def print_timetable(chosen):
    if not chosen:
        print("가능한 조합을 찾지 못했습니다."); return
    total = sum(c["credits"] for c in chosen)
    pen = sum(c["pen"] for c in chosen)
    print(f"추천 시간표 — {len(chosen)}과목 / {total:.1f}학점 / 선호벌점 {pen}\n")
    for c in chosen:
        print(f"  [{c['이수구분']} {c['학년']}학년] {c['교과목명']} ({c['credits']:.0f}학점, "
              f"{c['학수번호']}-{c['sec']['분반']})  {c['sec']['시간']}  @{c['sec']['강의실']}")
    # 주간 그리드
    print("\n  == 주간표 ==")
    grid = {}
    for c in chosen:
        for day, s, e in c["sec"]["slots"]:
            grid.setdefault(day, []).append((s, e, c["교과목명"]))
    for day in DAYS:
        if day in grid:
            items = sorted(grid[day])
            line = ", ".join(f"{s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d} {n}"
                             for s, e, n in items)
            print(f"   {day}: {line}")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    XLSX = r"C:\Users\WIN10\Desktop\jihoon\수강편람 자동화 프로젝트\2026-1학기 강의시간표(한국어)_20260212.xlsx"
    DEPT = "인공지능데이터사이언스학과"

    TARGET_YEARS = (3,)   # 예: 3학년 학생 → 3학년 권장 과목만
    DIR = r"C:\Users\WIN10\Desktop\jihoon\수강편람 자동화 프로젝트"
    OLD_XLSX = DIR + r"\2025-2 강의시간표 (한국어)_20250831.xlsx"
    RENAME_JSON = DIR + r"\poc_cache\course_renames.json"

    df = load_courses(XLSX)
    cands = build_candidates(df, DEPT, 이수구분=("전공필수", "전공기초", "전공선택"),
                             target_years=TARGET_YEARS)
    print(f"[{DEPT}] {TARGET_YEARS}학년 전공 후보 과목: {len(cands)}개")

    # 과목명 변경 맵 = 수강편람 교양 변경표  +  작년 시간표 자동 감지(전공 포함)
    rename_map = load_rename_map(RENAME_JSON)
    auto = detect_renames(OLD_XLSX, XLSX, DEPT)
    for new, olds in auto.items():
        rename_map.setdefault(new, []).extend(olds)
    if auto:
        print("  자동 감지된 과목명 변경:", {k: v for k, v in auto.items()})

    # 이수한 과목 필터 — 학생 입력 예시 (작년 이름으로 입력해도 인식됨)
    이수한과목 = ["컴퓨터구조"]
    cands, removed = filter_taken(cands, taken_names=이수한과목, rename_map=rename_map)
    if removed:
        print("  이수 완료로 제외:", ", ".join(c["교과목명"] for c in removed))
    print(f"  → 필터 후 후보: {len(cands)}개")

    print("\n" + "=" * 60)
    print(f"데모: {TARGET_YEARS}학년 · 오전 선호 · 15학점 · 이수과목 제외")
    print("=" * 60)
    chosen = solve(cands, target_credits=15, prefer="오전")
    print_timetable(chosen)