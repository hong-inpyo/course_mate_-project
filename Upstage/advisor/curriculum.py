# -*- coding: utf-8 -*-
"""학과·입학년도별 졸업요건을 '교과과정표 엑셀'(data/curriculum_excels)에서 읽는다.

수강편람 PDF 추출(requirements_db)보다 깨끗하고, 학교가 직접 만든 표라 전 학과를 커버한다.
파일명 규칙: '학과명_연도.xlsx'. 컬럼: 순번|학년|개설년도|개설학기|교과목명|이수구분|학점정보.
이수구분 코드: 공필(공통필수)·균필(균형교양필수)·기필(학문기초교양필수)·전기(전공기초)·전필(전공필수)·전선(전공선택).

핵심: 균필 목록은 이미 학과별로 다르다(예: 경영학부 균필엔 자연과학 과목이 있고 AI데사엔 없음).
즉 '제외영역' 규칙이 목록 자체에 반영돼 있어, 학과별 균형교양 인정 풀로 그대로 쓸 수 있다.
"""

import os
import re
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 프로젝트 루트
EXCEL_DIR = os.path.join(_ROOT, "data", "curriculum_excels")

# 엑셀의 이수구분 코드 → 진단 카테고리 이름
_CODE = {
    "공필": "공통필수", "균필": "균형교양필수", "기필": "학문기초교양필수",
    "전기": "전공기초", "전필": "전공필수", "전선": "전공선택",
}

# 교과과정표 엑셀에 균필(균형교양) 목록이 빠진 학과 보정.
# ※ 융합전공 등 대부분의 빈 풀은 '균형교양 없음'이 맞아 여기 넣지 않는다.
#   아래는 '균형교양을 이수해야 하는데 표에서 목록이 누락된' 학과만(수강편람 확인).
_GE_POOL_OVERRIDE = {
    # 회화과(미대 계열) — 역사와사상·자연과과학·경제와사회 3영역에서 9학점.
    "회화과": ["동서양의사상과윤리", "성서와기독교", "세계사", "한국현대사",
             "생명과학의이해", "수의세계", "지구환경과기후변화", "현대과학으로의초대",
             "경영학", "경제학", "미디어빅뱅과방송", "현대사회와법"],
}


def graduation_credits(dept, year):
    """졸업 이수학점. 표준 130이며, 학과·입학년도별 예외만 반영한다.

    출처: 수강편람 '단일전공 이수 시 학과별 전공 이수학점' 표의 졸업학점 열.
    (requirements_db는 2024·2026 건축학과 행이 PDF에서 옆 행과 병합돼 누락됐어서,
     확실한 값을 여기 명시한다.)
    """
    d = str(dept).replace(" ", "")
    y = int(year)
    if d in ("건축학과", "건축학전공"):                 # 건축(5년제)
        return 168 if y <= 2023 else 163
    if "사이버국방" in d:                              # 사이버국방학과: 2025학년도 신설
        return 140 if y >= 2025 else 130
    소융140 = {"컴퓨터공학과", "정보보호학과", "소프트웨어학과",
              "데이터사이언스학과", "만화애니메이션텍전공"}
    if y <= 2020 and d in 소융140:                    # 2019~2020 입학자 소프트웨어융합대학 계열
        return 140
    if y == 2019 and d in ("디자인이노베이션전공", "항공시스템공학과", "항공시스템공학전공"):
        return 140
    return 130


def available(excel_dir=EXCEL_DIR):
    """{학과: [연도 내림차순]} — 폴더에 있는 교과과정표 목록."""
    out = {}
    if not os.path.isdir(excel_dir):
        return out
    for f in os.listdir(excel_dir):
        m = re.match(r"(.+)_(\d{4})\.xlsx$", f)
        if m:
            out.setdefault(m.group(1), []).append(int(m.group(2)))
    for d in out:
        out[d].sort(reverse=True)
    return out


# 개명된 학과 — 시간표엔 옛 이름이 남아 있는데 교과과정 파일은 새 이름이다.
# 옛/새 파일이 둘 다 있을 수 있으므로(2025는 옛 이름, 2026은 새 이름)
# 최종 선택은 _resolve가 '요청 연도가 있는 쪽'으로 한다.
_RENAMED = {"일어일문학전공": "국제일본학전공"}    # 2026학년도 개명


def _candidates(dept, av):
    """학과명 → 교과과정 파일명 후보들(정확일치 → 띄어쓰기 무시 → 개명 → 부분일치)."""
    out = []

    def add(x):
        if x in av and x not in out:
            out.append(x)

    add(dept)
    # 시간표는 '럭셔리 브랜드 디자인 융합전공', 파일명은 '럭셔리브랜드디자인 융합전공' —
    # 같은 학과인데 띄어쓰기만 다르다.
    nospace = dept.replace(" ", "")
    for d in av:
        if d.replace(" ", "") == nospace:
            add(d)
    for old, new in _RENAMED.items():
        if old in dept:
            add(new)
    # 학부 접두어 떼기: '호텔관광외식경영학부 외식경영학전공' → '외식경영학전공'.
    # 반드시 공백 경계로만 자른다. 글자로만 뒤를 맞추면 '호텔관광외식경영학부'가
    # '경영학부'로, '콘텐츠소프트웨어학과'가 '소프트웨어학과'로 잘못 잡힌다.
    # 반대 방향(질의가 파일명 안에 든 경우)도 없어진 학과를 후신에 붙이므로 쓰지 않는다
    # — 데이터사이언스학과→인공지능데이터사이언스학과.
    tokens = dept.split()
    for i in range(1, len(tokens)):
        tail = " ".join(tokens[i:])
        add(tail)
        for d in av:
            if d.replace(" ", "") == tail.replace(" ", ""):
                add(d)
    return out


def _resolve(dept, year):
    """(학과, 연도) → (파일경로, 실제학과명, 실제연도, 폴백여부) 또는 None.
    정확한 연도 파일이 없으면 입학년도 이하 중 가장 가까운 연도(없으면 최소 연도)로 폴백."""
    av = available()
    cands = _candidates(dept, av)
    if not cands:
        return None
    # 개명 전후 파일이 둘 다 있으면(일어일문학전공 2025 / 국제일본학전공 2026)
    # 요청한 입학년도를 가진 쪽을 고른다.
    dept_hit = next((c for c in cands if year in av[c]), cands[0])
    years = av[dept_hit]
    if year in years:
        y, fb = year, False
    else:
        le = [x for x in years if x <= year]
        y, fb = (max(le) if le else min(years)), True
    return os.path.join(EXCEL_DIR, f"{dept_hit}_{y}.xlsx"), dept_hit, y, fb


def load(dept, year):
    """(학과, 연도) → 요건 dict. 파일이 없거나 못 읽으면 None(상위에서 다른 소스로 폴백).

    반환: {학과, 연도, 폴백, 공통필수:[名], 균형교양_pool:[名], 학문기초:[名],
           전공기초:[名], 전공필수:[名], 전공선택_pool:[名], 학점:{名:학점}}
    """
    r = _resolve(dept, int(year))
    if not r:
        return None
    path, dept_hit, y, fb = r
    try:
        df = pd.read_excel(path, skiprows=1)          # roadmap_logic와 동일: 1행(제목) 건너뜀
        df.columns = ["순번", "학년", "개설년도", "개설학기", "교과목명", "이수구분", "학점정보"]
        df = df.iloc[1:]                              # 헤더 다음 첫 행도 제거
    except Exception:
        return None

    buckets = {v: [] for v in _CODE.values()}
    credit = {}
    for _, row in df.iterrows():
        name = str(row["교과목명"]).strip()
        cat = _CODE.get(str(row["이수구분"]).strip())
        if not cat or not name or name == "nan":
            continue
        if name not in buckets[cat]:
            buckets[cat].append(name)
        try:
            credit[name] = float(str(row["학점정보"]).split("/")[0])
        except (ValueError, IndexError):
            credit[name] = 3.0

    # 표에 균필 목록이 아예 없으면(회화과 등 누락 학과) 보정 풀로 채운다.
    ge_pool = buckets["균형교양필수"] or list(_GE_POOL_OVERRIDE.get(dept_hit, []))

    return {
        "학과": dept_hit, "연도": y, "폴백": fb,
        "공통필수": buckets["공통필수"],
        "균형교양_pool": ge_pool,
        "학문기초": buckets["학문기초교양필수"],
        "전공기초": buckets["전공기초"],
        "전공필수": buckets["전공필수"],
        "전공선택_pool": buckets["전공선택"],
        "학점": credit,
    }
