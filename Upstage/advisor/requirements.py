# -*- coding: utf-8 -*-
"""
졸업요건 진단 (결정론적) — 이수과목 vs 학과·입학년도별 요건을 코드로 정확히 대조한다.
요건은 LLM이 추측하면 틀리므로(예: 균형교양 6/9학점 혼동, 채플 환각) 여기서 규칙으로 계산하고,
설명만 Solar가 한다. 출처: 2026 수강편람 "2022학년도 입학자 교과과정"(p.51-53).

핵심 예: 균형교양필수에 '경제학'(경제와사회 영역)을 이수했으면 자동 반영된다.

[리뷰 노트 — 팀원용]  진입 함수는 diagnose_any(profile, eqmap).
반환: {공통필수, 균형교양필수, 학문기초교양필수, 졸업학점, 졸업인증} 각 항목의 이수/미이수.
요건 데이터는 requirements_db.load()(→ poc_cache/requirements_db.json)에서 온다.
검증: 이수과목을 바꿔 넣어 미이수 목록이 규칙대로 줄어드는지 확인.
"""

from difflib import get_close_matches
import equiv_courses   # 학교 공식 '동일과목조회' 데이터 (추측 아님)

FAIL = {"F", "NP", "W", "U", "재수강"}
# 참고: 공식 데이터 확인 결과 '통계학개론'과 '확률및통계'는 동일과목이 아님(서로 다른 그룹).

# (학과, 입학년도) → 요건. 지금은 2022 인공지능데이터사이언스(구 데이터사이언스학) 기준.
REQUIREMENTS = {
    ("인공지능데이터사이언스학과", 2022): {
        "졸업학점": 130,
        "공통필수": ["신입생세미나A", "신입생세미나B", "창업과기업가정신1",
                  "문제해결을위한글쓰기와발표", "서양철학:쟁점과토론",
                  "취창업과진로설계", "대학영어", "우주자연인간"],
        # ※ 균형교양 인정 과목은 '입학년도 편람'에 실린 목록만 인정됨(학교 유선 확인).
        #   아래는 2026 편람의 "2022학년도 입학자" 섹션 기준이며, 사용자 확인으로
        #   '현대예술의이해'는 2022년 당시 목록에 없어 제외함. 2022년도 수강편람 확보 시 목록 교체 필요.
        "균형교양필수": {
            "필요영역수": 2, "필요학점": 6,
            "제외영역": ["자연과과학"],           # DS 계열은 자연과과학 영역 인정 안 됨
            "영역별과목": {
                "역사와사상": ["동서양의사상과윤리", "성서와기독교", "세계사", "한국현대사"],
                "경제와사회": ["경영학", "경제학", "미디어빅뱅과방송", "현대사회와법"],
                "문화와예술": ["융합예술의이해", "컴퓨터게임과메타버스", "한국의문화와한류"],
            },
        },
        # ※ 2022 당시 학과명은 '인공지능학과'(이후 인공지능데이터사이언스학과로 통합).
        #   출처: 수강편람 p.54 학문기초 표의 '인공지능학' 열(18학점) — 통계학개론 없음.
        #   (p.53 '데이터사이언스학' 열(21학점, 통계학개론 포함)과 다름 — 이전 버전의 오류 수정)
        "학문기초교양필수": {
            "필요학점": 18,
            "과목": ["고급프로그래밍활용", "인공지능과빅데이터", "고급인공지능활용",
                   "기초미적분학", "공업수학1", "일반물리학1"],
        },
        # ※ 2022 입학자 졸업인증 = 영어 + 고전독서 (2026 편람 p.50-51의 2022 섹션에도 이 둘만 있음).
        #   '소프트웨어코딩 포함 3개 중 2개'는 2026학년도 규칙 — 이전 버전에서 잘못 복사했던 것 수정.
        "졸업인증": {"목록": ["영어졸업인증", "고전독서인증"],
                  "필요개수": 2},
    },
}


def _taken_names(profile):
    return {c["과목"] for c in profile.get("이수과목", []) if c.get("성적") not in FAIL}


def validate_courses(profile, known_names):
    """입력한 이수과목명을 전체 과목 DB(known_names)에서 먼저 찾고, 없으면 비슷한 이름을 제안.

    사용자 원칙: 오타/옛이름이어도 조용히 넘기지 말고 '이거 맞나요?' 하고 물어본다.
    반환 예: [{"입력": "창업과기업가정신", "제안": ["창업과기업가정신1"]}]
    """
    known = set(known_names)
    미확인 = []
    for c in profile.get("이수과목", []):
        name = c["과목"]
        if name in known:
            continue
        제안 = get_close_matches(name, known, n=3, cutoff=0.6)
        미확인.append({"입력": name, "제안": 제안})
    return 미확인


def _covered(course, taken, eqmap):
    """직접 이수했으면 과목명, 공식 동일과목을 이수했으면 그 이름을 반환. 아니면 None."""
    if course in taken:
        return course
    for e in eqmap.get(course, []):
        if e in taken:
            return e
    return None


def diagnose(profile, eqmap=None):
    """이수과목을 요건과 대조해 카테고리별 진행상황을 반환(정확·결정론적).

    공식 동일과목 데이터로 '옛 이름으로 이수한 요건과목'도 인정한다
    (예: '취업역량개발론' 이수 → 공통필수 '취창업과진로설계' 충족).
    """
    req = REQUIREMENTS.get((profile["학과"], profile["학번"]))
    if not req:
        return {"오류": f"{profile['학과']} {profile['학번']}학번 요건 미등록"}
    taken = _taken_names(profile)
    eqmap = eqmap if eqmap is not None else equiv_courses.load()
    out = {}

    def mark(c):
        """이수 표기: 동일과목으로 인정된 경우 '요건과목(=이수한이름)' 형태."""
        got = _covered(c, taken, eqmap)
        return None if got is None else (c if got == c else f"{c}(동일과목 '{got}' 이수)")

    # 1) 공통필수: 정확히 이 과목들을 다 들어야 함 (동일과목 인정 포함)
    done = [m for c in req["공통필수"] if (m := mark(c))]
    out["공통필수"] = {"이수": done,
                   "미이수": [c for c in req["공통필수"] if mark(c) is None]}

    # 2) 균형교양필수: 제외영역 빼고, 서로 다른 영역에서 학점 채우기 (경제학 등 자동 반영)
    b = req["균형교양필수"]
    이수영역 = {}
    for area, courses in b["영역별과목"].items():
        if area in b["제외영역"]:
            continue
        got = [m for c in courses if (m := mark(c))]
        if got:
            이수영역[area] = got
    이수학점 = sum(len(v) for v in 이수영역.values()) * 3
    # 아직 안 채운 영역의 미이수 과목 = 균형교양으로 더 들을 수 있는 후보
    후보풀 = []
    for area, courses in b["영역별과목"].items():
        if area in b["제외영역"] or area in 이수영역:
            continue
        후보풀 += [c for c in courses if mark(c) is None]
    out["균형교양필수"] = {
        "필요": f"{b['필요영역수']}개 영역 {b['필요학점']}학점(계열 제외영역: {', '.join(b['제외영역'])})",
        "이수영역": 이수영역,
        "이수학점": min(이수학점, b["필요학점"]),
        "남은학점": max(0, b["필요학점"] - 이수학점),
        "후보풀": 후보풀,
        "완료": 이수학점 >= b["필요학점"] and len(이수영역) >= b["필요영역수"],
    }

    # 3) 학문기초교양필수: 지정 과목들 (동일과목 인정 포함)
    a = req["학문기초교양필수"]
    a_done = [m for c in a["과목"] if (m := mark(c))]
    a_miss = [c for c in a["과목"] if mark(c) is None]
    out["학문기초교양필수"] = {"필요학점": a["필요학점"], "이수": a_done, "미이수": a_miss,
                        "이수학점": len(a_done) * 3}

    # 4) 졸업학점
    out["졸업학점"] = {"필요": req["졸업학점"], "이수": profile.get("총이수학점", 0),
                  "남은": max(0, req["졸업학점"] - profile.get("총이수학점", 0))}

    # 5) 졸업인증 (권수/통과여부는 사용자 입력 필요 — 사이트 점검중)
    out["졸업인증"] = {"필요": f"{req['졸업인증']['목록']} 중 {req['졸업인증']['필요개수']}개 통과",
                  "입력필요": "각 인증 통과 여부/고전독서 권수 (홈페이지 점검중)"}
    return out


def diagnose_auto(profile, eqmap=None):
    """일반화 진단 — 수강편람에서 자동 추출한 DB(requirements_db)로 모든 학과·학번 커버.

    하드코딩(REQUIREMENTS)에 없는 (학과, 학번)용. 자동 추출이라 '검증 필요' 표시를 남긴다.
    통합 학과(예: 인공지능데이터사이언스)는 입학 당시 트랙이 여러 개라
    profile["트랙"]으로 지정하지 않으면 후보를 돌려주며 질문한다.
    """
    import requirements_db as RDB
    db = RDB.load()
    y = str(profile["학번"])
    if y not in db:
        return {"오류": f"{y}학년도 요건이 수강편람에서 추출되지 않음"}
    ydb = db[y]
    cands = RDB.resolve_dept(profile.get("트랙") or profile["학과"], ydb)
    summary_names = [c for c in cands if c in ydb.get("요약", {})]
    if not summary_names:
        return {"오류": f"'{profile['학과']}'를 {y}년 요건표에서 못 찾음 (후보: {cands})"}
    if len(summary_names) > 1 and not profile.get("트랙"):
        return {"질문": f"{profile['학과']}는 {y}년 당시 트랙이 여러 개입니다. "
                      f"입학 당시 학과를 profile['트랙']으로 지정하세요: {summary_names}"}
    name = summary_names[0]
    요약 = ydb["요약"][name]
    # 학문기초 표의 열 이름은 '~과'가 빠지는 등 요약표와 다를 수 있어 부분일치로 찾는다
    기초키들 = ydb.get("학문기초", {})
    학문기초열 = next((c for c in cands if c in 기초키들), None)
    if 학문기초열 is None:
        base = name.replace("학과", "").replace("전공", "")
        학문기초열 = next((k for k in 기초키들 if k in name or (base and base in k)), None)

    taken = _taken_names(profile)
    eqmap = eqmap if eqmap is not None else equiv_courses.load()

    def mark(c):
        got = _covered(c, taken, eqmap)
        return None if got is None else (c if got == c else f"{c}(동일과목 '{got}' 이수)")

    out = {"_출처": f"수강편람 {y}학년도 교과과정 자동추출(트랙: {name}) — 학과 공지와 대조 권장"}

    # 공통필수 (자동추출 표가 불완전할 수 있음 — 개수만 다르면 표시됨)
    공통 = ydb.get("공통필수", [])
    out["공통필수"] = {"이수": [m for c in 공통 if (m := mark(c))],
                   "미이수": [c for c in 공통 if mark(c) is None]}

    # 균형교양: 학생 계열이 제외계열에 적힌 과목은 인정 제외
    계열 = (profile.get("계열") or "").replace(" ", "")
    필요학점 = 요약.get("균형교양", 6)
    이수영역 = {}
    for area, courses in ydb.get("균형교양", {}).items():
        got = []
        for c, 제외 in courses.items():
            if 계열 and 계열 in 제외.replace(" ", ""):
                continue
            if (m := mark(c)):
                got.append(m)
        if got:
            이수영역[area] = got
    이수학점 = min(sum(len(v) for v in 이수영역.values()) * 3, 필요학점)
    후보풀 = []
    for area, courses in ydb.get("균형교양", {}).items():
        if area in 이수영역:
            continue
        for c, 제외 in courses.items():
            if 계열 and 계열 in 제외.replace(" ", ""):
                continue
            if mark(c) is None and c not in 후보풀:
                후보풀.append(c)
    out["균형교양필수"] = {
        "필요": f"서로 다른 영역 {필요학점}학점" + ("" if 계열 else " (계열 미입력 — 제외영역 미적용)"),
        "이수영역": 이수영역, "이수학점": 이수학점,
        "남은학점": max(0, 필요학점 - 이수학점),
        "후보풀": 후보풀,
        "완료": 이수학점 >= 필요학점 and len(이수영역) >= 필요학점 // 3,
    }

    # 학문기초교양필수
    과목들 = list(ydb.get("학문기초", {}).get(학문기초열, {})) if 학문기초열 else []
    out["학문기초교양필수"] = {
        "필요학점": 요약.get("학문기초", len(과목들) * 3),
        "이수": [m for c in 과목들 if (m := mark(c))],
        "미이수": [c for c in 과목들 if mark(c) is None],
        "이수학점": sum(3 for c in 과목들 if mark(c)),
    }

    # 전공 학점 (이수과목에 "구분" 필드가 있으면 집계)
    전공이수 = {"전공필수": 0.0, "전공선택": 0.0}
    구분있음 = False
    for c in profile.get("이수과목", []):
        gu = str(c.get("구분", ""))
        if c.get("성적") in FAIL:
            continue
        if gu:
            구분있음 = True
        if "전필" in gu or gu == "전공필수":
            전공이수["전공필수"] += c.get("학점", 3)
        elif "전선" in gu or gu == "전공선택" or "전공" in gu:
            전공이수["전공선택"] += c.get("학점", 3)
    out["전공"] = {
        "필요": {k: 요약.get(k) for k in ("전공필수", "전공선택", "전공학점계")},
        "이수": 전공이수 if 구분있음 else "이수과목에 '구분'(전필/전선) 입력 시 집계됨",
    }

    out["졸업학점"] = {"필요": 요약.get("졸업학점", 130),
                  "이수": profile.get("총이수학점", 0),
                  "남은": max(0, 요약.get("졸업학점", 130) - profile.get("총이수학점", 0))}
    out["졸업인증"] = {"필요": "입학년도별 졸업인증 규정 확인(수강편람)", "입력필요": "인증 통과 여부"}
    return out


def diagnose_curriculum(profile, eqmap=None):
    """교과과정표 엑셀(data/curriculum_excels) 기반 진단 — 전 학과·입학년도를 깨끗하게 커버.

    학교가 만든 표라 이수구분(공필·균필·기필·전기·전필·전선)이 정확하다.
    균필 목록은 학과별로 이미 다르므로(자연계열은 자연과학 제외 등) 그대로 균형교양 인정 풀로 쓴다.
    이 소스로 못 하면(파일 없음 등) None을 반환해 상위(diagnose_any)가 다음 폴백을 쓰게 한다.
    """
    try:
        import curriculum as C
    except ImportError:
        from advisor import curriculum as C
    req = C.load(profile["학과"], profile["학번"])
    if not req:
        return None

    taken = _taken_names(profile)
    eqmap = eqmap if eqmap is not None else equiv_courses.load()
    cr = req["학점"]

    def mark(c):
        got = _covered(c, taken, eqmap)
        return None if got is None else (c if got == c else f"{c}(동일과목 '{got}' 이수)")

    폴백주 = f"·{profile['학번']}년 파일이 없어 {req['연도']}년 표로 근사" if req["폴백"] else ""
    out = {"_출처": f"교과과정표 엑셀({req['학과']} {req['연도']}학년도{폴백주}) — 학과 공지와 대조 권장"}

    # 1) 공통필수 (동일과목 인정 포함)
    공통 = req["공통필수"]
    out["공통필수"] = {"이수": [m for c in 공통 if (m := mark(c))],
                   "미이수": [c for c in 공통 if mark(c) is None]}

    # 2) 학문기초교양필수
    기초 = req["학문기초"]
    out["학문기초교양필수"] = {
        "필요학점": sum(cr.get(c, 3) for c in 기초),
        "이수": [m for c in 기초 if (m := mark(c))],
        "미이수": [c for c in 기초 if mark(c) is None],
        "이수학점": sum(cr.get(c, 3) for c in 기초 if mark(c)),
    }

    # 3) 균형교양필수 — 엑셀의 균필 목록이 곧 학과별 인정 풀.
    #    필요 학점은 입학년도 규정: 2023학번까지 6학점, 2024학번부터 9학점.
    pool = req["균형교양_pool"]
    필요학점 = 6 if int(profile["학번"]) <= 2023 else 9
    이수 = [m for c in pool if (m := mark(c))]
    이수학점 = min(len(이수) * 3, 필요학점)
    out["균형교양필수"] = {
        "필요": f"균형교양 {필요학점}학점(학과 인정 과목 {len(pool)}개 중)",
        "이수영역": {"균형교양": 이수} if 이수 else {},
        "이수학점": 이수학점,
        "남은학점": max(0, 필요학점 - 이수학점),
        "후보풀": [c for c in pool if mark(c) is None],   # _교양_후보가 시간표 후보로 사용
        "완료": 이수학점 >= 필요학점,
    }

    # 4) 전공 (전공필수/기초 미이수 목록 + 이수과목 '구분' 있으면 학점 집계)
    전필, 전기 = req["전공필수"], req["전공기초"]
    전공이수 = {"전공필수": 0.0, "전공선택": 0.0}
    구분있음 = False
    for c in profile.get("이수과목", []):
        if c.get("성적") in FAIL:
            continue
        gu = str(c.get("구분", ""))
        if gu:
            구분있음 = True
        if "전필" in gu or gu == "전공필수":
            전공이수["전공필수"] += c.get("학점", 3)
        elif "전선" in gu or gu == "전공선택" or "전공" in gu:
            전공이수["전공선택"] += c.get("학점", 3)
    out["전공"] = {
        "전공필수_미이수": [c for c in 전필 if mark(c) is None],
        "전공기초_미이수": [c for c in 전기 if mark(c) is None],
        "이수": 전공이수 if 구분있음 else "이수과목에 '구분'(전필/전선) 입력 시 집계됨",
    }

    # 5) 졸업학점 (표준 130, 학과·입학년도별 예외는 curriculum.graduation_credits)
    졸업 = C.graduation_credits(profile["학과"], profile["학번"])
    out["졸업학점"] = {"필요": 졸업, "이수": profile.get("총이수학점", 0),
                  "남은": max(0, 졸업 - profile.get("총이수학점", 0))}
    out["졸업인증"] = {"필요": "입학년도별 졸업인증 규정 확인(수강편람)", "입력필요": "인증 통과 여부"}
    return out


def diagnose_any(profile, eqmap=None):
    """하드코딩(검증됨) → 교과과정표 엑셀 → 수강편람 자동추출 순으로 폴백한다.

    AI데사 2022는 하드코딩(정밀 검증본)을 쓰고, 나머지 학과·학번은 교과과정표 엑셀로 커버한다.
    엑셀도 없으면 수강편람 PDF 자동추출(diagnose_auto)을 마지막 수단으로 쓴다.
    """
    if (profile["학과"], profile["학번"]) in REQUIREMENTS:
        return diagnose(profile, eqmap)
    cur = diagnose_curriculum(profile, eqmap)
    if cur is not None:
        return cur
    return diagnose_auto(profile, eqmap)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    profile = {
        "학과": "데이터사이언스학과", "학번": 2022, "총이수학점": 66,
        "이수과목": [{"과목": n, "성적": "A0"} for n in
                 ["경제학", "현대예술의이해", "일반물리학1", "고급인공지능활용",
                  "인공지능과빅데이터", "대학영어", "서양철학:쟁점과토론"]],
    }
    import json
    print(json.dumps(diagnose(profile), ensure_ascii=False, indent=2))