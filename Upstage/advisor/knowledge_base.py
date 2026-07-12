# -*- coding: utf-8 -*-
"""
지식 베이스 빌더 — 흩어진 자료를 하나로 합쳐 Solar가 참고할 JSON을 만든다.

합치는 소스:
  1. 강의시간표 xlsx(2026-1)      → 학과 커리큘럼(학년×이수구분), 개설강좌 요약
  2. 작년 강의시간표(2025-2)      → 과목명 변경 자동 감지
  3. 수강편람 교양 변경표          → poc_cache/course_renames.json
  4. 수강편람 졸업요건(입학년도별)  → 아래 GRAD_REQ (수기 정리, 출처 표기)
  5. 강의계획서 선수과목           → (sjpt 사이트 점검중, 나중에 채움)

[리뷰 노트 — 팀원용]  server.py 가 이 파일에서 쓰는 건 '경로 상수'뿐이다:
  CUR_XLSX(이번 학기 강의시간표) · OLD_XLSX(직전 학기) · RENAME_JSON(교양 변경표) · DIR.
DIR 은 이 파일 위치 기준(os.path.dirname)이라 폴더째 옮겨도 동작한다.
아래 지식베이스 빌더 함수들은 오프라인 도구로, 서버 실행에는 호출되지 않는다.
"""
import os
import json
import re
import pandas as pd
import timetable_solver as T

# 수강편람 교양 변경표를 거칠게 뽑을 때 섞인 노이즈 제거용
_JUNK_NAMES = {"교과목명", "이수구분", "구분", "영역", "해당없음", "학문기초교양필수", "비고"}


def _plausible_course(name):
    if not name or len(name) < 2:
        return False
    if name in _JUNK_NAMES or name.isdigit():
        return False
    if re.search(r"\d\s*(학점|개\s*영역|영역)", name):   # "9학점", "3개 영역" 등
        return False
    return True


def _sanitize_renames(rmap):
    out = {}
    for new, olds in rmap.items():
        if not _plausible_course(new):
            continue
        goods = [o for o in olds if _plausible_course(o)]
        if goods:
            out[new] = goods
    return out

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DIR)

SCHED_DIR = os.path.join(ROOT, "data", "강의시간표")

CUR_XLSX = os.path.join(
    SCHED_DIR,
    "2026-1학기 강의시간표(한국어)_20260212.xlsx"
)

OLD_XLSX = os.path.join(
    SCHED_DIR,
    "2025-2 강의시간표 (한국어)_20250831.xlsx"
)

RENAME_JSON = os.path.join(
    ROOT,
    "cache",
    "poc_cache",
    "course_renames.json"
)
# 수강편람 "입학년도별 교과과정"에서 정리 (출처: 2026-1 수강편람 p.34/p.51)
GRAD_REQ = {
    "2022": {
        "졸업학점": 130,
        "교양_공통필수": ["신입생세미나A", "신입생세미나B", "창업과기업가정신1",
                     "문제해결을위한글쓰기와발표", "서양철학:쟁점과토론",
                     "취창업과진로설계", "대학영어", "우주자연인간"],
        "균형교양": "자신의 소속 계열과 다른 2개 영역에서 6학점 선택 이수",
        "영어졸업인증": "TOEIC 700 / IBT 80 / TEPS 556 / OPIc IL 이상",
        "전공_세부요건": "학과별 상이(수강편람 6항) — 강의계획서/학과 확인 필요(TODO)",
    },
    "2026": {
        "졸업학점": 130,
        "교양_공통필수": ["세종인을위한진로설계", "세종인을위한전공탐색", "대학영어",
                     "창업과기업가정신", "비판적사고와창의적글쓰기", "서양철학:쟁점과토론",
                     "취창업과진로역량개발"],
        "균형교양": "자신의 소속 계열과 다른 3개 영역에서 9학점 선택 이수",
    },
}


def build_kb(dept, out_path=None):
    df = T.load_courses(CUR_XLSX)
    ycol = T._year_col(df)
    sub = df[df["개설학과전공"] == dept]

    # 1) 학과 커리큘럼: 학년 × 이수구분 → 과목명
    curriculum = {}
    전공 = sub[sub["이수구분"].astype(str).str.contains("전공")].drop_duplicates("학수번호")
    for _, r in 전공.iterrows():
        y = str(r[ycol]).strip()
        curriculum.setdefault(y, {}).setdefault(r["이수구분"], []).append(r["교과목명"])

    # 2) 이번 학기 개설강좌 요약(과목 단위): Solar가 "무엇이 열리는지" 알도록
    offerings = []
    for hakbun, g in sub.groupby("학수번호"):
        r0 = g.iloc[0]
        offerings.append({
            "학수번호": str(hakbun), "교과목명": r0["교과목명"],
            "이수구분": r0["이수구분"], "학년": str(r0[ycol]).strip(),
            "학점": float(r0["학점"]), "분반수": int(len(g)),
        })

    # 3) 과목명 변경 맵: 수강편람 교양 + 작년 시간표 자동 감지(전공 포함)
    rename = T.load_rename_map(RENAME_JSON)
    auto = T.detect_renames(OLD_XLSX, CUR_XLSX, dept)
    for new, olds in auto.items():
        rename.setdefault(new, [])
        for o in olds:
            if o not in rename[new]:
                rename[new].append(o)
    rename = _sanitize_renames(rename)   # 교양 추출 노이즈 제거

    kb = {
        "메타": {"학기": "2026-1", "학과": dept,
               "설명": "여러 공개 자료를 합친 수강 추천용 지식 베이스"},
        "졸업요건": GRAD_REQ,
        "커리큘럼": curriculum,
        "개설강좌_이번학기": offerings,
        "과목명변경": rename,
        "선수과목": {"_상태": "sjpt 강의계획서 사이트 점검중 — 확보 후 채움"},
    }
    if out_path:
        json.dump(kb, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return kb


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    DEPT = "인공지능데이터사이언스학과"
    out = os.path.join(ROOT, "cache", "poc_cache", "knowledge_base.json")
    kb = build_kb(DEPT, out)
    print("지식 베이스 생성:", out)
    print("\n[커리큘럼] 학년별 과목:")
    for y in sorted(kb["커리큘럼"]):
        for gu, names in kb["커리큘럼"][y].items():
            print(f"  {y}학년 {gu}: {names}")
    print("\n[졸업요건 2022] 졸업학점:", kb["졸업요건"]["2022"]["졸업학점"],
          "| 교양필수", len(kb["졸업요건"]["2022"]["교양_공통필수"]), "과목")
    print("[과목명변경] 자동감지 포함:", {k: v for k, v in kb["과목명변경"].items() if "컴퓨터" in k})
    print("[개설강좌] 이번학기 DS 과목 수:", len(kb["개설강좌_이번학기"]))
