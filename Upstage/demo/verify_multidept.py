# -*- coding: utf-8 -*-
"""다학과 검증 — 여러 학과×입학년도×학년에 대해 서버와 '동일한 경로'로
   ① 졸업요건 진단(게이트) ② 교양 후보 주입 ③ 시간표 생성 을 돌려 하나하나 print한다.

서버 _recommend_alts()가 하는 일과 같은 순서:
   진단 = requirements.diagnose_any(...)   # 오류/질문이면 서버는 추천을 거부함(게이트)
   교양후보, limits = advisor_agent._교양_후보(...)
   rec = timetable_solver.recommend_for_profile(..., extra_courses=교양후보, group_limits=limits)

실행:  conda activate sugang;  python demo/verify_multidept.py
"""
import os
import sys
import warnings
warnings.filterwarnings("ignore")               # openpyxl 기본스타일 경고 숨김(출력 정리용)

# 서버와 동일한 import 경로 확보 (bare import: equiv_courses, requirements_db, curriculum ...)
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)                       # from advisor import ...
sys.path.insert(0, os.path.join(_ROOT, "advisor"))
sys.stdout.reconfigure(encoding="utf-8")

from advisor import timetable_solver as T
from advisor import requirements, advisor_agent, curriculum
from advisor.knowledge_base import CUR_XLSX, OLD_XLSX, RENAME_JSON
import equiv_courses

_DF = T.load_courses(CUR_XLSX)
_EQMAP = equiv_courses.load()
_OFFERED = set(_DF["개설학과전공"].astype(str).unique())   # 이번 학기 개설이 있는 학과

# (학과, 입학년도, 현재학년) — 단과대별 골고루
CASES = [
    ("인공지능데이터사이언스학과", 2024, 2),
    ("인공지능데이터사이언스학과", 2026, 1),
    ("인공지능학과", 2022, 3),          # 통합 전 학과명 코호트
    ("컴퓨터공학과", 2025, 2),
    ("경영학부", 2025, 2),
    ("경제학과", 2026, 1),
    ("기계공학과", 2024, 3),
    ("법학과", 2024, 2),
    ("무용과", 2025, 2),
    ("화학과", 2024, 2),
    ("행정학과", 2025, 2),
    ("건축학과", 2024, 3),
]


def _offered_hit(dept):
    """강의시간표(개설강좌)에서 이 학과와 매칭되는 개설학과명(있으면)."""
    hits = [d for d in _OFFERED if dept in d or d in dept]
    return hits


def run_case(dept, 학번, 학년):
    print("=" * 78)
    print(f"■ {dept} | {학번}학번 | {학년}학년")

    # 0) 교과과정표 로드 확인
    req = curriculum.load(dept, 학번)
    if not req:
        print("  ✗ 교과과정표 엑셀 없음 → 이 학과는 커리큘럼 소스로 진단 불가")
    else:
        폴백 = f" (⚠️{학번} 파일 없어 {req['연도']}년 표 사용)" if req["폴백"] else ""
        print(f"  · 교과과정표: {req['학과']}_{req['연도']}{폴백} | "
              f"공필 {len(req['공통필수'])} 균필 {len(req['균형교양_pool'])} "
              f"기필 {len(req['학문기초'])} 전필 {len(req['전공필수'])} "
              f"전기 {len(req['전공기초'])} 전선 {len(req['전공선택_pool'])}")

    # 프로필: 아직 아무 것도 안 들은 신규 상태(미이수 목록이 전부 나오게)
    prof = {"학과": dept, "학번": 학번, "학년": 학년, "선호": "오전",
            "총이수학점": 0, "이수과목": []}

    # 1) 진단 게이트 (서버는 오류/질문이면 추천 거부)
    진단 = requirements.diagnose_any(prof, _EQMAP)
    if "오류" in 진단 or "질문" in 진단:
        print(f"  ✗ 진단 게이트 실패 → 서버라면 추천 거부: {진단.get('오류') or 진단.get('질문')}")
        return {"학과": dept, "학번": 학번, "진단": "실패", "학점": 0, "충돌": "-", "과목수": 0}
    print(f"  · 진단 출처: {진단.get('_출처', '하드코딩(검증본)')}")
    print(f"    - 공통필수 미이수 {len(진단['공통필수']['미이수'])}개, "
          f"학문기초 미이수 {len(진단['학문기초교양필수']['미이수'])}개, "
          f"균형교양 남은 {진단['균형교양필수']['남은학점']}학점")
    if 진단.get("전공"):
        print(f"    - 전공필수 미이수 {len(진단['전공'].get('전공필수_미이수', []))}개 "
              f"예: {진단['전공'].get('전공필수_미이수', [])[:4]}")

    # 2) 교양 후보 주입 (진단 결과 기반)
    교양후보, limits = advisor_agent._교양_후보(_DF, 진단, prof, _EQMAP)
    print(f"  · 교양 후보 {len(교양후보)}개 주입 (limits={limits})")

    # 3) 시간표 생성
    rec = T.recommend_for_profile(prof, CUR_XLSX, OLD_XLSX, RENAME_JSON,
                                  target_credits=15, equiv_map=_EQMAP,
                                  extra_courses=교양후보, group_limits=limits, df=_DF)
    chosen = rec["추천시간표"]
    학점 = sum(c["credits"] for c in chosen)
    충돌 = sum(1 for i in range(len(chosen)) for j in range(i + 1, len(chosen))
             if T.sections_conflict(chosen[i]["sec"], chosen[j]["sec"]))
    구분수 = {}
    for c in chosen:
        k = "교양" if any(g in str(c["이수구분"]) for g in ("공필", "균필", "기필", "공통", "균형", "학문", "교양")) else "전공"
        구분수[k] = 구분수.get(k, 0) + 1
    print(f"  ▶ 시간표: {len(chosen)}과목 / {학점:.0f}학점 / 충돌 {충돌} / 구성 {구분수}")
    for c in chosen:
        print(f"      [{c['이수구분']} {c['학년']}년] {c['교과목명']} "
              f"({c['credits']:.0f}학점) {c['sec']['시간']}")
    return {"학과": dept, "학번": 학번, "진단": "OK", "학점": round(학점),
            "충돌": 충돌, "과목수": len(chosen)}


def main():
    print(f"강의시간표 개설학과 {len(_OFFERED)}개 | 교과과정표 학과 {len(curriculum.available())}개\n")
    rows = []
    for dept, y, g in CASES:
        try:
            rows.append(run_case(dept, y, g))
        except Exception as e:
            import traceback
            print(f"  ✗ 예외: {e}\n{traceback.format_exc()}")
            rows.append({"학과": dept, "학번": y, "진단": "예외", "학점": 0, "충돌": "-", "과목수": 0})

    print("\n" + "=" * 78)
    print("■ 요약")
    print(f"{'학과':<22}{'학번':>6}{'진단':>6}{'과목':>5}{'학점':>5}{'충돌':>5}")
    ok = 0
    for r in rows:
        print(f"{r['학과']:<22}{r['학번']:>6}{r['진단']:>6}{r['과목수']:>5}{r['학점']:>5}{str(r['충돌']):>5}")
        if r["진단"] == "OK" and r["충돌"] == 0 and r["과목수"] > 0:
            ok += 1
    print(f"\n통과(진단OK·충돌0·과목>0): {ok}/{len(rows)}")


if __name__ == "__main__":
    main()
