# -*- coding: utf-8 -*-
"""수강자격(수강대상·유의사항) 해석 — 자유서술 → 표준 제한 스키마 → 결정론적 판정.

강의시간표 '수강대상및유의사항' 칸에는 누가 들을 수 있는지가 서술로 적혀 있다.
  '자유전공학부1'  '공과계열1'  '인문과학대학 제외'  '2~4학년 전체'  '17~21학번 대상'
이걸 표준 제한 스키마로 정규화하고, '이 학생이 들을 수 있나'를 규칙으로 판정한다.
**전 과정 결정론적 — LLM/API를 쓰지 않는다.** (세종대 양식은 패턴이 규칙적이라 규칙으로 충분)

표준 제한 스키마:
  {대상학과: [名], 대상계열: [名], 제외조직: [名], 대상학년: [int],
   학번범위: [시작,끝] 또는 [], 외국인전용: bool, 내국인전용: bool}

**보수적 원칙:** 이 필터는 과목을 '제거'한다. 잘못 제거하면 들을 수 있는 강의를 놓치므로,
확신할 때만 막고 애매하면 통과시킨다:
  - 계열 지정(공과계열 등)은 계열↔학과 대응표가 없으므로 막지 않는다.
  - 학년은 학과 지정이 없을 때만 적용한다(내 학과 강좌의 학년은 권장 성격이라 하위학년 수강을 막지 않음).
  - 인식 못 한 문구('창의학기제 승인 대상강좌' 등 자격과 무관한 안내)는 제한 없음으로 본다.
"""
import re

_EMPTY = {"대상학과": [], "대상계열": [], "제외조직": [], "대상학년": [],
          "학번범위": [], "외국인전용": False, "내국인전용": False, "타전공불가": False}

# 자격 제한이 아니라 강의 운영 안내인 문구 — 여기에 걸리면 제한 없음으로 본다.
_NOT_A_LIMIT = ("창의학기제", "영어강의", "재수강", "팀티칭", "속강", "e러닝", "이러닝",
                "교직이수", "전필인정", "졸업인증", "교환교류", "사이버대")

_ORG = r"[가-힣A-Za-z]+(?:학과|학부|전공|대학|계열|과)"


def parse_rule(text, known_orgs=None):
    """수강대상 문구 1개 → 표준 제한(결정론적 규칙). 인식 못 하면 제한 없음.

    known_orgs: 실제 존재하는 학과·대학명의 정규화 집합. 주면 여기 없는 이름은 조직으로 안 본다
      — '2학년 수강과목'의 '수강과', '대상과목'의 '대상과'처럼 '과'로 끝나는 일반 단어를
      학과명으로 오인해 모든 학생을 차단하는 오판을 막는다(가장 위험한 오류).
    """
    lim = {k: (list(v) if isinstance(v, list) else v) for k, v in _EMPTY.items()}
    s = str(text or "").strip()
    if not s or s == "nan":
        return lim

    if "외국인" in s or "교환학생" in s:
        lim["외국인전용"] = True
    if "내국인" in s:
        lim["내국인전용"] = True

    # 학번 범위: '17~21학번 대상'(두 자리) / '2022~2025학번 재수강대상자'(네 자리)
    m = re.search(r"(\d{2}|\d{4})\s*~\s*(\d{2}|\d{4})\s*학번", s)
    if m:
        lim["학번범위"] = [int(m.group(1)) % 100, int(m.group(2)) % 100]   # 2022 → 22

    # 학년: '2~4학년' / '3학년' / 조직명 뒤 꼬리 숫자('자유전공학부1')
    years = set()
    for a, b in re.findall(r"(\d)\s*~\s*(\d)\s*학년", s):
        years.update(range(int(a), int(b) + 1))
    if not years:
        for y in re.findall(r"(?<!\d)([1-5])\s*학년", s):
            years.add(int(y))

    # 조직명 수집 — '제외'가 붙으면 제외조직, 아니면 대상(계열은 따로)
    is_exclude = "제외" in s
    for m in re.finditer(_ORG + r"\s*(\d)?", s):
        name = re.sub(r"\d+$", "", m.group(0)).strip()
        tail = m.group(1)
        if not name or name in ("학년",):
            continue
        if tail:                      # 조직명 뒤 꼬리 숫자 = 대상 학년
            years.add(int(tail))
        if known_orgs is not None and not _known_hit(name, known_orgs):
            continue                  # 실제 학과·대학이 아닌 말('수강과','대상과') → 조직으로 보지 않음
        if is_exclude:
            lim["제외조직"].append(name)
        elif name.endswith("계열"):
            lim["대상계열"].append(name)
        elif name.endswith("대학"):
            pass                      # '~대학'만 단독으로 온 대상 지정은 범위가 넓어 막지 않음
        else:
            lim["대상학과"].append(name)

    # '컴퓨터공학대상', 'AI융합전자공학대상'처럼 접미사(학과/학부) 없이 '대상'만 붙는 형태.
    # 실존 조직명과 일치할 때만 인정하므로 '외국인대상'·'3~5학년 대상' 같은 건 자동으로 걸러진다.
    if known_orgs is not None and not is_exclude:
        for m in re.finditer(r"([가-힣A-Za-z]+?)\s*대상", s):
            name = m.group(1).strip()
            if _known_hit(name, known_orgs) and name not in lim["대상학과"]:
                lim["대상학과"].append(name)

    lim["대상학년"] = sorted(years)

    # 자격과 무관한 운영 안내뿐이면(조직·학번 정보가 전혀 없음) 제한 없음으로 되돌린다.
    if any(k in s for k in _NOT_A_LIMIT) and not (lim["대상학과"] or lim["제외조직"]
                                                  or lim["대상계열"] or lim["학번범위"]):
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _EMPTY.items()}
    return lim


def build_limits(texts, known_orgs=None):
    """수강대상 문구들 → {원문: 표준제한}. 고유값만 처리(API 불필요, 즉시).

    known_orgs: 실존 학과·대학명 집합(정규화 전 원문 가능). orgs_from_df()로 만들어 넘기면
    '과'로 끝나는 일반 단어를 학과로 오인하는 오판이 사라진다.
    """
    known = {_norm(o) for o in (known_orgs or ())} if known_orgs is not None else None
    out = {}
    for t in texts:
        s = str(t or "").strip()
        if s and s != "nan" and s not in out:
            out[s] = parse_rule(s, known)
    return out


def orgs_from_df(df):
    """강의시간표 df → 실존 학과·대학명 집합(개설학과전공 + 개설대학)."""
    orgs = set()
    for col in ("개설학과전공", "개설대학", "주관학과"):
        if col in df.columns:
            orgs.update(str(v).strip() for v in df[col].dropna().unique() if str(v).strip())
    return orgs


def _norm(s):
    """학과명 비교용 정규화 — 공백·중점·마침표 제거, 접미사(학과/학부/전공/과) 제거."""
    s = re.sub(r"[\s·.]", "", str(s))
    return re.sub(r"(학과|학부|전공|과)$", "", s)


def _all_abbrev(names, known_depts=None):
    """지정이 전부 '어느 학과인지 확정할 수 없는 약칭'인가 → 그러면 차단하지 않는다(보수적).

    known_depts(실존 학과명)를 주면 데이터 기준으로 판단한다 — 실존 학과와 이어지지 않는
    이름('공대','한음','사대')은 약칭으로 보고 막지 않는다. 이게 없으면 접미사로 어림한다.
    (이 가드가 없으면 한국음악과 학생이 '한음1' 분반에서, 컴공 학생이 '공대1' 분반에서 잘린다)
    """
    if not names:
        return False
    if known_depts is not None:
        known = {_norm(d) for d in known_depts if str(d).strip()}
        return not any(_known_hit(re.sub(r"\d+$", "", str(n)), known) for n in names)
    out = []
    for n in names:
        s = re.sub(r"\d+$", "", re.sub(r"[\s·.]", "", str(n)))
        out.append(bool(re.search(r"(대|대학|계열)$", s)) and not s.endswith("학과"))
    return all(out)


def _known_hit(name, known):
    """정규화 이름이 실존 조직과 부분일치하나. 접미사 처리 차이('컴퓨터공학'/'컴퓨터공학과')를 흡수."""
    n = _norm(name)
    return bool(n) and any(n in k or k in n for k in known if k)


def is_eligible(sec, profile, limits=None, known_depts=None):
    """이 분반을 이 학생이 들을 수 있나 → (가능?, 사유). 애매하면 True(보수적).

    sec: _make_sections가 만든 섹션 — '수강대상'·'외국인전용'·'내국인전용' 키를 본다.
    profile: '학과'·'학년'·'학번', 선택적으로 '외국인'(기본 False=내국인).
    limits: {원문: 표준제한} 캐시.
    known_depts: 실존 학과명 집합 — 약칭('공대','한음')을 학과로 오인해 차단하지 않게 한다.
    """
    외국인 = bool(profile.get("외국인"))
    # 1) 학교가 컬럼으로 명시한 전용 플래그 — 가장 확실(파싱 불필요)
    if str(sec.get("외국인전용") or "").strip().upper() == "Y" and not 외국인:
        return False, "외국인 전용 분반"
    if str(sec.get("내국인전용") or "").strip().upper() == "Y" and 외국인:
        return False, "내국인 전용 분반"

    text = str(sec.get("수강대상") or "").strip()
    if not text or text == "nan":
        return True, ""
    # limits에 없는 문구는 통과시킨다(보수적) — known_orgs 없이 즉석 파싱하면 오판 위험이 커서 안 한다.
    lim = (limits or {}).get(text)
    if not lim:
        return True, ""

    if lim["외국인전용"] and not 외국인:
        return False, f"외국인 대상 강좌({text})"
    if lim["내국인전용"] and 외국인:
        return False, f"내국인 대상 강좌({text})"

    내학과 = _norm(profile.get("학과", ""))
    # 1.5) '타전공생 수강불가' — 개설학과 전공생만. 단 대상학과가 따로 명시돼 있으면
    #      그쪽(아래 3번)이 진짜 기준이다. 예: 기독교와세계는 개설=기독교학과지만
    #      분반마다 '사회대1','공대1'처럼 수강 단과대가 지정돼 있다.
    if lim.get("타전공불가") and not lim["대상학과"]:
        개설 = _norm(sec.get("개설학과") or "")
        if 내학과 and 개설 and not (개설 in 내학과 or 내학과 in 개설):
            return False, f"{sec.get('개설학과')} 전공생만 수강 가능"
    # 2) 제외 지정 — 내 학과/대학이 제외 목록에 걸리면 못 들음
    for x in lim["제외조직"]:
        nx = _norm(x)
        if 내학과 and nx and (nx in 내학과 or 내학과 in nx):
            return False, f"{x} 제외 대상"
    # 3) 대상 학과 지정 — 계열이 함께 지정됐거나, 지정이 전부 단과대 약칭('공대','사회대')이면
    #    약칭↔학과 대응표가 없어 내 학과가 거기 속하는지 알 수 없다 → 막지 않는다(보수적).
    #    (이 가드가 없으면 컴퓨터공학과 학생이 '공대1' 분반까지 못 듣게 되는 과도 차단이 난다)
    if lim["대상학과"] and not lim["대상계열"] and not _all_abbrev(lim["대상학과"], known_depts):
        # 양방향 부분일치 — 학과명이 바뀐 경우(데이터사이언스학과 → 인공지능데이터사이언스학과)를
        # 다른 학과로 오인해 차단하지 않기 위함.
        if 내학과 and not any(_norm(d) in 내학과 or 내학과 in _norm(d)
                            for d in lim["대상학과"] if _norm(d)):
            return False, f"{'·'.join(lim['대상학과'])} 대상 강좌"
    # 4) 학년 — 조직 지정이 전혀 없는 순수 학년 문구('2학년 수강과목')에만 적용한다.
    #    ('공과계열1'처럼 조직+꼬리숫자인 경우, 조직(계열)을 못 막는데 학년으로 대신 막으면 과도 차단)
    #    또한 '아직 학년이 안 된' 경우만 막는다 — 상위학년이 하위학년 과목을 듣는 catch-up은 정상.
    if lim["대상학년"] and not lim["대상학과"] and not lim["대상계열"]:
        try:
            내학년 = int(profile.get("학년", 0))
        except (TypeError, ValueError):
            내학년 = 0
        if 내학년 and 내학년 < min(lim["대상학년"]):
            return False, f"{min(lim['대상학년'])}학년부터 수강 가능"
    # 5) 학번 범위
    if lim["학번범위"]:
        try:
            내학번 = int(str(profile.get("학번", 0))[-2:])   # 2022 → 22
        except (TypeError, ValueError):
            내학번 = 0
        a, b = lim["학번범위"]
        if 내학번 and not (a <= 내학번 <= b):
            return False, f"{a}~{b}학번 대상 강좌"
    return True, ""
