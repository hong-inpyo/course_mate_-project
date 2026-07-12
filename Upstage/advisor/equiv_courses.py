# -*- coding: utf-8 -*-
"""
동일과목 조회 — 학교 공식 '동일과목조회' 엑셀(2026-1 기준)을 정규화해서
"이 과목 = 저 과목(개편 전 이름)" 판정의 공식 근거로 쓴다.

원본 구조: 같은 '그룹번호' = 서로 동일과목으로 인정되는 묶음 (7,589행 / 2,521그룹).
정규화: 과목명 → 동일과목명 리스트 (poc_cache/equiv_courses.json 캐시).

[리뷰 노트 — 팀원용]  진입 함수 load() → {과목명: [동일 인정 과목들]} 딕셔너리(캐시 json에서 로드).
용도: 과목명이 개편 때 바뀌어도(예: 컴퓨터구조 = 컴퓨터구조및운영체제) 이수로 인정하기 위한 근거.
캐시가 없을 때만 원본 엑셀(동일과목조회_*.xlsx)에서 재생성한다.

이걸로 이전의 '이름 유사도 추측'(오탐 있었음)을 대체한다 — 공식 데이터라 확인질문 불필요.
단, 같은 과목명이 여러 그룹(학과)에 나올 수 있어 이름 기준 매핑은 합집합으로 처리.
"""
import os
import json
import warnings

DIR = os.path.dirname(os.path.abspath(__file__))   # 이 파일(advisor/) 위치
ROOT = os.path.dirname(DIR)                          # 프로젝트 루트
XLSX = os.path.join(ROOT, "data", "동일과목조회_2026-07-04.xlsx")
CACHE = os.path.join(ROOT, "cache", "poc_cache", "equiv_courses.json")


def build(xlsx=XLSX, out=CACHE):
    """엑셀 → {과목명: [동일과목명,...]} + 그룹 원본. JSON으로 저장."""
    import pandas as pd
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(xlsx, header=2).dropna(subset=["그룹번호"])
    groups = {}
    for g, grp in df.groupby("그룹번호"):
        names = sorted(set(grp["교과목명"].astype(str).str.strip()))
        if len(names) >= 2:                     # 이름이 하나뿐인 그룹은 매핑에 무의미
            groups[str(int(g))] = names
    name2equiv = {}
    for names in groups.values():
        for n in names:
            name2equiv.setdefault(n, set()).update(x for x in names if x != n)
    data = {"메타": {"출처": os.path.basename(xlsx), "기준": "2026-1학기"},
            "groups": groups,
            "name2equiv": {k: sorted(v) for k, v in name2equiv.items()}}
    json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return data


def load():
    """캐시가 있으면 로드, 없으면 빌드. 반환: {과목명: [동일과목명,...]}"""
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))["name2equiv"]
    return build()["name2equiv"]


def equivalents(name, eqmap=None):
    """한 과목의 공식 동일과목 리스트. 없으면 []"""
    return (eqmap or load()).get(name, [])


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    data = build()
    m = data["name2equiv"]
    print("동일과목 매핑:", len(m), "과목 /", len(data["groups"]), "그룹 저장 →", CACHE)
    for n in ["컴퓨터구조", "통계학개론", "취창업과진로설계", "확률및통계"]:
        print(f"  {n} = {m.get(n, '(동일과목 없음)')}")
