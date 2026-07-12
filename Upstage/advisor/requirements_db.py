# -*- coding: utf-8 -*-
"""
[리뷰 노트 — 팀원용]  런타임에는 load()가 poc_cache/requirements_db.json 만 읽으면 된다.
아래 빌더(build_db 등)는 수강편람 파싱본(parsed.json)에서 json 을 만드는 오프라인 도구라
서버 실행에는 필요 없다(이미 만들어진 json 을 함께 배포).

졸업요건 DB (일반화) — 수강편람 파싱본(parsed.json)에서 입학년도별×학과별 요건을
자동 추출해 모든 학과·학번을 포괄하는 DB를 만든다. (하드코딩 requirements.py를 대체/보완)

추출 대상 (입학년도 섹션 "N학년도 입학자 교과과정" 안에서):
  1. 학과별 요약표: 단과대학|학과명|공통·균형·학문기초 교양|전공필수|전공선택|졸업학점
  2. 공통필수 과목 목록 (핵심역량 표)
  3. 균형교양 영역별 과목 (+과목별 제외계열)
  4. 학문기초교양필수: 학과(열)별 지정 과목·이수시기

주의: PDF 표 인식이라 셀 병합 노이즈("72 60"처럼 두 행이 합쳐짐)가 있음 —
      숫자 검증으로 걸러내고, 이상 행은 "_이상행"에 기록해 사람이 검토할 수 있게 한다.
"""
import json
import os
import re

DIR = os.path.dirname(os.path.abspath(__file__))   # 이 파일(advisor/) 위치
ROOT = os.path.dirname(DIR)                          # 프로젝트 루트
PARSED = os.path.join(ROOT, "cache", "poc_cache", "parsed.json")
DB_OUT = os.path.join(ROOT, "cache", "poc_cache", "requirements_db.json")

YEAR_RE = re.compile(r"(\d{4})학년도 입학자 교과과정")
TIME_RE = re.compile(r"^\d-\d")          # 이수시기 "1-1", "2-2(A)" 등


def _txt(e):
    c = e.get("content", {})
    return (c.get("markdown") or c.get("text") or "").strip()


def _rows(md):
    """마크다운 표 → 행 리스트(셀 리스트). 구분선(---) 제거."""
    out = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r"-*:?-+:?", c or "-") for c in cells):
            continue
        out.append(cells)
    return out


def _int(s):
    """숫자 하나면 int, 아니면 None ("72 60" 같은 병합 노이즈 걸러냄)"""
    s = str(s).strip()
    return int(s) if re.fullmatch(r"\d{1,3}", s) else None


def _extract_summary(md, db_year):
    """학과별 요약표: 학과명 → 학점 요건들. 병합/노이즈 행은 _이상행에."""
    rows = _rows(md)
    if not rows:
        return
    header = rows[0]
    # 열 인덱스 찾기 (연도별로 열 구성이 약간 다름: 2020-21은 '교양필수' 통합)
    def col(*keys):
        for i, h in enumerate(header):
            hn = h.replace(" ", "")
            if any(k in hn for k in keys):
                return i
        return None
    i_dept = col("학과명")
    i_grad = col("졸업학점")
    i_a = col("전공필수")
    i_b = col("전공선택")
    i_ab = col("전공학점계")
    i_기초 = col("학문기초")
    i_균형 = col("균형")
    if i_dept is None or i_grad is None:
        return
    for r in rows[1:]:
        if len(r) <= max(i_dept, i_grad):
            continue
        name = r[i_dept].replace(" ", "")
        vals = {
            "전공필수": _int(r[i_a]) if i_a is not None and i_a < len(r) else None,
            "전공선택": _int(r[i_b]) if i_b is not None and i_b < len(r) else None,
            "전공학점계": _int(r[i_ab]) if i_ab is not None and i_ab < len(r) else None,
            "학문기초": _int(r[i_기초]) if i_기초 is not None and i_기초 < len(r) else None,
            "균형교양": _int(r[i_균형]) if i_균형 is not None and i_균형 < len(r) else None,
            "졸업학점": _int(r[i_grad]) if i_grad < len(r) else None,
        }
        if not name or name == "학과명":
            continue
        # 병합행 감지: 값 셀 어디든 숫자가 2개 이상("72 60") 들어있으면 두 행이 합쳐진 것
        col_idx = {"전공필수": i_a, "전공선택": i_b, "전공학점계": i_ab,
                   "학문기초": i_기초, "균형교양": i_균형, "졸업학점": i_grad}
        merged = any(i is not None and i < len(r) and len(re.findall(r"\d{1,3}", r[i])) >= 2
                     for i in col_idx.values())
        if merged or vals["졸업학점"] is None:
            first = _recover_merged(r, i_dept, col_idx)   # 첫 학과 값만 복원
            if first:
                dept1, vals1 = first
                db_year.setdefault("요약", {})[dept1] = vals1
            db_year.setdefault("_이상행", []).append(r)   # 원본은 검토용 보관
            continue
        db_year.setdefault("요약", {})[name] = {k: v for k, v in vals.items() if v is not None}


def _recover_merged(r, i_dept, col_idx):
    """두 행이 합쳐진 요약행에서 '첫 번째 학과' 값만 복원.

    각 값 셀이 "72 60"처럼 숫자 2개(이상)면 첫 숫자가 첫 학과의 값이다.
    학과명 셀은 공백으로 나뉜 첫 토큰(…학과/…전공으로 끝나는)을 취한다.
    """
    raw_name = r[i_dept] if i_dept < len(r) else ""
    tokens = raw_name.split()
    if len(tokens) < 2:
        return None
    dept1 = tokens[0].replace(" ", "")
    if not re.search(r"(학과|전공|학부)$", dept1):
        return None
    vals = {}
    for key, i in col_idx.items():
        if i is None or i >= len(r):
            continue
        nums = re.findall(r"\d{1,3}", r[i])
        if len(nums) >= 2:                    # 병합 확인: 숫자 2개 이상
            vals[key] = int(nums[0])
        elif len(nums) == 1:
            vals[key] = int(nums[0])
    return (dept1, vals) if vals.get("졸업학점") else None


def _extract_balance(md, db_year):
    """균형교양 표: 영역|과목명|학점|제외 계열|이수시기 → 영역별 {과목: 제외계열}

    주의: 학문기초 표도 '영역'으로 시작하므로, 균형교양에만 있는 '제외 계열' 헤더로 구분.
    """
    rows = _rows(md)
    if not rows or "영역" not in rows[0][0]:
        return
    if not any("제외" in h for h in rows[0]):     # 균형교양 표가 아님(학문기초 등)
        return
    area = None
    for r in rows[1:]:
        if len(r) < 4 or "합계" in r[0] + r[1]:
            continue
        if r[0]:
            area = r[0].replace(" ", "")
        if not area or not r[1]:
            continue
        db_year.setdefault("균형교양", {}).setdefault(area, {})[r[1].replace(" ", "")] = r[3]


def _extract_common(md, db_year):
    """공통필수(핵심역량) 표 → 과목명 리스트"""
    rows = _rows(md)
    if not rows:
        return
    header0 = rows[0][0].replace(" ", "")
    if "핵심역량" not in header0 and "핵심대역량" not in header0:
        return
    for r in rows[1:]:
        if len(r) < 2 or "합계" in r[0] + r[1]:
            continue
        name = r[1].replace(" ", "")
        if name and name != "과목명":
            db_year.setdefault("공통필수", [])
            if name not in db_year["공통필수"]:
                db_year["공통필수"].append(name)


def _extract_foundation(md, db_year):
    """학문기초 표(학과가 열): 각 학과열의 비어있지 않은 셀 = 지정 과목(+이수시기)"""
    rows = _rows(md)
    if len(rows) < 3:
        return
    header = rows[0]
    hn = [h.replace(" ", "") for h in header]
    if hn[0] != "영역" or ("과목" not in hn[1] and "과목명" not in hn[1]):
        return
    # 헤더가 2행(계열/학과)인 경우: 2행째가 학과명이면 그걸 사용
    depts = hn[3:]
    body_start = 1
    if rows[1] and rows[1][0].replace(" ", "") == "영역":   # 2중 헤더
        depts = [c.replace(" ", "") for c in rows[1][3:]]
        body_start = 2
    for r in rows[body_start:]:
        if len(r) < 4 or "합계" in (r[0] + r[1]).replace(" ", ""):
            continue
        course = r[1].replace(" ", "")
        if not course:
            continue
        for k, dept in enumerate(depts):
            i = 3 + k
            if not dept or i >= len(r):
                continue
            cell = r[i].strip()
            if cell and (TIME_RE.match(cell) or cell in ("*", "**", "***")):
                db_year.setdefault("학문기초", {}).setdefault(dept, {})[course] = cell


def build(parsed_path=PARSED, out=DB_OUT):
    parsed = json.load(open(parsed_path, encoding="utf-8"))
    db = {}
    year = None
    for e in parsed["elements"]:
        t = _txt(e)
        if not t:
            continue
        m = YEAR_RE.search(t)
        if m and e.get("category") != "table":
            y = m.group(1)
            year = y if 2019 <= int(y) <= 2026 else None   # 본문 언급(2014 등) 오인 방지
            if year:
                db.setdefault(year, {})
            continue
        if year and e.get("category") == "table":
            _extract_summary(t, db[year])
            _extract_balance(t, db[year])
            _extract_common(t, db[year])
            _extract_foundation(t, db[year])
    json.dump(db, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return db


def load():
    if os.path.exists(DB_OUT):
        return json.load(open(DB_OUT, encoding="utf-8"))
    return build()


# 통합/개명된 학과의 과거 이름 — 통합 학과는 후보가 여러 개라 사용자에게 트랙 확인 필요
ALIASES = {
    "인공지능데이터사이언스학과": ["인공지능학과", "데이터사이언스학과", "인공지능학", "데이터사이언스학"],
}


def resolve_dept(dept, year_db):
    """학과명 → 요약표/학문기초의 이름 후보. 정확일치 → 별칭 → 부분일치.
    여러 개면 전부 반환 (통합 학과는 입학 당시 트랙을 사용자가 골라야 함)."""
    names = set(year_db.get("요약", {})) | set(year_db.get("학문기초", {}))
    d = dept.replace(" ", "")
    if d in names:
        return [d]
    alias_hits = [a for a in ALIASES.get(d, []) if a in names]
    if alias_hits:
        return alias_hits
    hits = sorted(n for n in names if n in d or d in n)
    if hits:
        return hits
    core = d.replace("학과", "").replace("전공", "")
    return sorted(n for n in names if core and core in n)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    db = build()
    print("추출된 입학년도:", sorted(db))
    for y in sorted(db):
        d = db[y]
        print(f"  {y}: 요약 {len(d.get('요약', {}))}개 학과 / 공통필수 {len(d.get('공통필수', []))}과목 / "
              f"균형 {len(d.get('균형교양', {}))}영역 / 학문기초 {len(d.get('학문기초', {}))}학과열 / "
              f"이상행 {len(d.get('_이상행', []))}")
    # 검증: 알고 있는 정답과 대조
    y22 = db.get("2022", {})
    print("\n[검증] 2022 인공지능학과 요약:", y22.get("요약", {}).get("인공지능학과"))
    print("[검증] 2022 데이터사이언스학과 요약:", y22.get("요약", {}).get("데이터사이언스학과"))
    print("[검증] 2022 학문기초 '인공지능학' 열:", y22.get("학문기초", {}).get("인공지능학"))
    print("[검증] resolve('인공지능데이터사이언스학과'):",
          resolve_dept("인공지능데이터사이언스학과", y22))
