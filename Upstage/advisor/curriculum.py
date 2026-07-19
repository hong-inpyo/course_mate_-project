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


def _match_dept(dept, av):
    """학과명을 폴더의 파일명과 매칭. 정확 일치 우선, 없으면 부분일치
    (예: '데이터사이언스학과' → '인공지능데이터사이언스학과')."""
    if dept in av:
        return dept
    cand = [d for d in av if dept in d or d in dept]
    return cand[0] if cand else None


def _resolve(dept, year):
    """(학과, 연도) → (파일경로, 실제학과명, 실제연도, 폴백여부) 또는 None.
    정확한 연도 파일이 없으면 입학년도 이하 중 가장 가까운 연도(없으면 최소 연도)로 폴백."""
    av = available()
    dept_hit = _match_dept(dept, av)
    if not dept_hit:
        return None
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

    return {
        "학과": dept_hit, "연도": y, "폴백": fb,
        "공통필수": buckets["공통필수"],
        "균형교양_pool": buckets["균형교양필수"],
        "학문기초": buckets["학문기초교양필수"],
        "전공기초": buckets["전공기초"],
        "전공필수": buckets["전공필수"],
        "전공선택_pool": buckets["전공선택"],
        "학점": credit,
    }