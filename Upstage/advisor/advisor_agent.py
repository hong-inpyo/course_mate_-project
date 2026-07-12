# -*- coding: utf-8 -*-
"""
수강 상담 에이전트 — 흩어진 자료(지식 베이스) + 결정론적 추천을 합쳐
Solar가 자연어로 개인 맞춤 조언을 하도록 연결한다.

흐름: 프로필 → [결정론적] 현재학년 판정·이수필터·시간표 solver → [Solar] 설명·조언
       (계산은 코드가, 설명·종합은 LLM이 — 정확성과 자연스러움 둘 다)

[리뷰 노트 — 팀원용]  server.py 가 실제로 쓰는 함수는 _교양_후보()·_fmt_exclusions() 두 개다.
  · _교양_후보(df, 진단, profile, eqmap) → (남은 교양 후보 과목, 이수구분별 상한) — solver 에 넘김
  · _fmt_exclusions(removed)            → '이수로 판정돼 제외된 과목' 사람이 읽는 문자열
advise()(Solar 자연어 조언)는 서버 경로에서 호출하지 않으므로 챗봇/RAG 의존성과 무관하다.
"""
import os
import json
import timetable_solver as T
from knowledge_base import CUR_XLSX, OLD_XLSX, RENAME_JSON
import requirements   # 결정론적 졸업요건 진단(균형교양·학문기초 등 정확 대조)
import equiv_courses  # 학교 공식 '동일과목조회' 데이터 — 옛 이름 이수 인정의 근거

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 프로젝트 루트
# 참고: 수강편람 자유질문(군휴학·장학 등)은 sugang_rag.RAG가 담당. 여기 졸업요건은
#       LLM 검색보다 정확해야 해서 requirements.diagnose(코드 규칙)로 계산한다.


def _교양_후보(df, 진단, profile, eqmap, force_auto=False):
    """졸업요건 진단이 알려준 '남은 교양'을 이번 학기 개설강좌에서 찾아 시간표 후보로 만든다.

    - 미이수 공통필수/학문기초: 옛 요건명이 현재 다른 이름으로 개설될 수 있어
      공식 동일과목명까지 포함해 찾는다 (예: 취창업과진로설계 → 취창업과진로역량개발).
    - 균형교양: 남은 학점이 있으면 '아직 안 채운 영역'의 과목들을 후보로. 3학점(1과목)만
      남았으면 group_limits로 1과목만 담게 제한.
    """
    names = set()
    for n in 진단["공통필수"]["미이수"] + 진단["학문기초교양필수"]["미이수"]:
        names.add(n)
        names.update(eqmap.get(n, []))
    limits = {}
    b = 진단["균형교양필수"]
    if b["남은학점"] > 0:
        if b.get("후보풀") is not None:        # 교과과정표 엑셀 진단이 학과별 인정 풀을 직접 제공
            names.update(b["후보풀"])
        else:
            # 영역별 과목 목록: 하드코딩(검증됨) 우선, 없으면 자동추출 DB(모든 학과·학번 커버)
            key = (profile["학과"], profile["학번"])
            if key in requirements.REQUIREMENTS and not force_auto:
                req = requirements.REQUIREMENTS[key]["균형교양필수"]
                영역별 = {a: list(v) for a, v in req["영역별과목"].items() if a not in req["제외영역"]}
            else:
                import requirements_db as RDB
                영역별 = {a: list(v) for a, v in
                       RDB.load().get(str(profile["학번"]), {}).get("균형교양", {}).items()}
            for area, courses in 영역별.items():
                if area in b["이수영역"]:
                    continue                  # 이미 채운 영역과 '다른' 영역에서 골라야 함
                names.update(courses)
        limits["균형교양필수"] = max(1, b["남은학점"] // 3)
    return T.build_courses_by_names(df, names), limits


def _fmt_timetable(chosen):
    lines = []
    for c in chosen:
        lines.append(f"- [{c['이수구분']} {c['학년']}학년] {c['교과목명']} "
                     f"{c['credits']:.0f}학점, {c['sec']['시간']} @{c['sec']['강의실']}")
    return "\n".join(lines)


def _fmt_exclusions(removed):
    """제외후보를 확실/확인필요로 나눠 표시 (바로 빼지 않고 사용자에게 제시)."""
    확실 = [r for r in removed if not r["확인필요"]]
    확인 = [r for r in removed if r["확인필요"]]
    out = []
    if 확실:
        out.append("확실(입력한 이수과목과 일치): " +
                   ", ".join(f"{r['교과목명']}" for r in 확실))
    if 확인:
        out.append("⚠️ 확인 필요(이름변경 자동감지, 100% 아님): " +
                   ", ".join(f"{r['교과목명']} ← {r['매칭']}" for r in 확인))
    return "\n".join(out) if out else "없음"


def _fmt_diagnosis(d):
    """결정론적 졸업요건 진단을 사람이 읽는 줄글로."""
    if "오류" in d:
        return d["오류"]
    cf, b, a, g = d["공통필수"], d["균형교양필수"], d["학문기초교양필수"], d["졸업학점"]
    영역 = "; ".join(f"{ar}({', '.join(v)})" for ar, v in b["이수영역"].items()) or "아직 없음"
    학문기초확인 = "; ".join(x["질문"] for x in a.get("확인필요", []))
    return "\n".join(filter(None, [
        f"- 공통필수: 이수 {cf['이수']} / 미이수 {cf['미이수']}",
        f"- 균형교양필수({b['필요']}): 이수 {b['이수학점']}학점 [{영역}], 남은 {b['남은학점']}학점 → {'완료' if b['완료'] else '미완료'}",
        f"- 학문기초교양필수(필요 {a['필요학점']}학점): 이수 {a['이수']} / 미이수 {a['미이수']}",
        (f"- 학문기초 확인필요: {학문기초확인}" if 학문기초확인 else ""),
        f"- 졸업학점: {g['이수']}/{g['필요']} (남은 {g['남은']}학점)",
        f"- 졸업인증: {d['졸업인증']['필요']} ({d['졸업인증']['입력필요']})",
    ]))


def _fmt_unmatched(미확인):
    """과목명 DB 미일치 항목 → '이거 맞나요?' 질문거리."""
    if not 미확인:
        return "모든 입력 과목명이 과목 DB와 일치"
    return "\n".join(
        f"- 입력 '{u['입력']}' → 과목 DB에 없음. 비슷한 과목: {', '.join(u['제안']) or '(유사 없음)'}"
        for u in 미확인)


_KNOWN_NAMES = None


def _known_course_names():
    """과목명 검증용 '전체 과목 DB' — 올해+작년 강의시간표의 교과목명 + 요건표 과목명."""
    global _KNOWN_NAMES
    if _KNOWN_NAMES is None:
        import pandas as pd
        names = set()
        for path in (CUR_XLSX, OLD_XLSX):
            names |= set(pd.read_excel(path)["교과목명"].astype(str).str.strip())
        for req in requirements.REQUIREMENTS.values():
            names |= set(req["공통필수"])
            for v in req["균형교양필수"]["영역별과목"].values():
                names |= set(v)
            names |= set(req["학문기초교양필수"]["과목"])
        # 동일과목조회의 과목명(과거 이름 포함 4천여 개)도 포함 — 최근 학기에 개설 안 된
        # 정식 과목(예: 기초미적분학)을 '없는 과목'으로 오판하지 않게.
        eq = equiv_courses.load()
        names |= set(eq)
        for v in eq.values():
            names |= set(v)
        _KNOWN_NAMES = names
    return _KNOWN_NAMES


def build_context(profile, rec, 진단, 미확인):
    """Solar에게 넘길 근거. 졸업요건은 결정론적 진단(정확), 시간표는 solver 결과."""
    이수 = ", ".join(f"{c['과목']}({c.get('성적','?')})" for c in profile.get("이수과목", []))
    목표학점 = profile.get("목표학점", 15)
    시간표학점 = sum(c["credits"] for c in rec["추천시간표"])
    return f"""[학생 정보]
학과: {profile['학과']} / 학번: {profile['학번']} / 성별: {profile.get('성별','-')}
현재 {rec['현재학년']}학년(입력) / 총 이수학점: {rec['총이수학점']}
선호: {profile.get('선호','오전')} 시간대 / 목표학점: {목표학점}
이수한 과목: {이수}

[입력 과목명 확인 — 과목 DB에서 먼저 찾은 결과. 없는 이름은 사용자에게 물어볼 것]
{_fmt_unmatched(미확인)}

[졸업요건 진단 — 코드가 이수과목과 대조해 정확히 계산한 결과. 이 수치를 그대로 사용]
{_fmt_diagnosis(진단)}

[시간표에서 제외한 과목 — 이수 판정 근거]
{_fmt_exclusions(rec['이수인식_제외후보'])}

[이번 학기 잠정 추천 시간표 — 안 들은 전공 + 남은 교양, 시간충돌 0, 총 {시간표학점:.0f}학점]
아직 안 들은 전공필수/기초: {', '.join(rec['아직_안들은_전공필수기초']) or '없음'}
{_fmt_timetable(rec['추천시간표'])}
※ 이 시간표는 확정 결과다. 과목을 빼거나 더하지 말고 {len(rec['추천시간표'])}과목 {시간표학점:.0f}학점 그대로 전달할 것.

[유의]
선수과목: 강의계획서(sjpt) 점검중 — 확답 불가
"""


SYSTEM = (
    "너는 세종대학교 수강신청 상담 챗봇이다. 아래 [학생 정보]·[졸업요건 진단]·[잠정 추천 시간표]"
    "만 근거로 한국어로 답한다. 정보에 없으면 지어내지 말고 '확인 필요'라고 말한다.\n"
    "★[졸업요건 진단]은 코드가 정확히 계산한 값이다. 학점·이수/미이수·완료여부를 **그대로** 전달하고, "
    "네 임의로 요건을 추가·변형하지 마라(예: 채플·영어글쓰기 같은 항목을 만들지 마라).\n"
    "★과목명이 비슷하다고 **동일 과목으로 추측하지 마라**(예: '창업과기업가정신'과 '취창업과진로설계'는 다른 과목이다). "
    "진단에 나온 정확한 과목명 기준으로만 이수/미이수를 말하라.\n"
    "★[잠정 추천 시간표]는 solver가 계산한 **확정 결과**다. 네가 과목을 빼거나(예: 오후라서 제외) "
    "추가하지 마라. 명시된 과목 수·총학점 그대로 전달하고, 아쉬운 점이 있으면 '참고'로만 덧붙여라.\n"
    "설명 순서: (1) [입력 과목명 확인]에 DB에 없는 이름이 있으면 **가장 먼저** '혹시 ~를 말씀하신 건가요?'라고 확인 질문, "
    "(2) 졸업요건 현황(수치 그대로, '확인필요' 항목은 확인 질문으로), "
    "(3) 이번 학기 추천 시간표 전체와 이유, (4) 선수과목은 확인 불가 안내."
)


def advise(profile, verbose=True, force_auto=False):
    """force_auto=True: 하드코딩(검증층)을 무시하고 수강편람 자동추출 DB만으로 진단
    (일반화 경로 점검용 — 모든 학과·학번이 이 경로를 탄다)."""
    eqmap = equiv_courses.load()                  # 공식 동일과목 (2026-1 동일과목조회)
    if force_auto:
        진단 = requirements.diagnose_auto(profile, eqmap)
    else:
        진단 = requirements.diagnose_any(profile, eqmap)  # 하드코딩(검증) 우선, 없으면 자동
    if "질문" in 진단 or "오류" in 진단:              # 트랙 미지정 등 — 진행 불가, 사용자에게 반환
        msg = 진단.get("질문") or 진단.get("오류")
        print("[진단 보류]", msg)
        return msg, "", None
    df = T.load_courses(CUR_XLSX)
    교양후보, limits = _교양_후보(df, 진단, profile, eqmap, force_auto)  # 남은 교양도 시간표에 포함
    rec = T.recommend_for_profile(profile, CUR_XLSX, OLD_XLSX, RENAME_JSON,
                                  target_credits=profile.get("목표학점", 15),
                                  equiv_map=eqmap, extra_courses=교양후보,
                                  group_limits=limits)
    미확인 = requirements.validate_courses(profile, _known_course_names())  # 과목명 먼저 DB 대조
    context = build_context(profile, rec, 진단, 미확인)

    # Solar 호출 (secrets.json 키)
    key = json.load(open(os.path.join(_ROOT, "secrets.json"), encoding="utf-8"))["UPSTAGE_API_KEY"]
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url="https://api.upstage.ai/v1")
    r = client.chat.completions.create(
        model="solar-pro2", temperature=0.3,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": context}])
    answer = r.choices[0].message.content
    if verbose:
        print("========== Solar에게 넘긴 근거 ==========")
        print(context)
        print("========== Solar 상담 답변 ==========")
        print(answer)
    return answer, context, rec


# todo
# 우주공강 방지 질문
# 금공강처럼 특정 요일 비우기 질문
# 기피하는 시간대 정확히 입력(ex. 1교시 09:00 시간대) 질문
# 연강위주 체크 질문
# 원하는 과목간 우선순위 질문
# P/NP, 원어민 강의 필터 질문
# 원하는 교수 질문


# 추가 기능:
# 장바구니 튕김 대비 대체 시간표->2안 3안까지 추가로 제공해줌
# 시간표 설명 서비스->추천하는 시간표가 많아지면 이걸 왜 추천하는지 헷갈릴 수도 있음, 간단하고 직관적인 단어 위주로 추천(ex. 부족한 전공 기초 학점위주 & 목요일에 연강 대신 금요일 공강 )
# 캠퍼스간 이동거리 계산->건물 간 거리를 계산해서 최적의 경로로 시간표 제공(선택 가능)
# 졸업요건을 대시보드로 시각화-> 가장 최우선의 과목을 전단에 배치
# 선수과목 미이수 경고->기이수한 과목 내에서 필요한 선수과목이 없을 경우 해당 과목에 대한 경고 알림 *강의계획서 필요*
# 강의계획서를 통해 팀플이 있는지, 과제는 몇 개 정도가 나오는지, 검색 후 제공 *강의계획서 필요*
# 재수강이 필요한 과목의 대체과목 자동 탐색 기능
# 진로와 연관된 강의 추천(ex. 인공지능학과이지만 마케팅에 관심이 있다-> 마케팅학과의 수업 추천)
# 시간표 내보내기->내보낼 때 강의계획서에 있는 시험시간이나 과제 제출 마감일을 같이 등록
# 고정 블록 설정->아르바이트나 학원 등의 개인 일정을 먼저 등록 후 해당 시간대를 피해가는 기능
# 국가장학금/학자금대출 조건 체크 기능(ex. 최소 학점 체크)
# 이 기능들을 버튼 대신 자연어 프롬프트 자체로 입력-> 내가 필요한 과목, 개인 시간표 등을 자연어로 등록. LLM으로 입력을 받으면 출력 또한 LLM으로 할 수 있음(ex. 학생이 무리한 요구(월,화,수,목,금 공강)를 했을 때 친절하게 가이드 해줄 수 있음)
# 입학년도에 전필이었던 과목이 시간이 지나면서 이름이 바뀌거나, 전선으로 바뀐 경우 해당 연도 입학자들은 그 과목을 찾아서 무조건 들어야 하므로, 해당 과목을 시간표에 포함시키고 명시
# 입학년도 교과과정 표를 기준으로 해당 사용자가 들어야 하는 과목들을 표시, 이름이나 선택/필수/폐지가 바뀌었다면 표시



if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    profile = { #웹 구현시 버튼 다운 형식으로 학과, 학번, 성별, 선호 시간대 등을 고를 수 있게 한다.
        "학과": "정보보호학과", "학번": 2022, "학년": 3, "성별": "남",
        #"트랙": "인공지능학과",      # 2022 입학 당시 학과(통합 전) — 자동추출 DB의 요건 기준
        "계열": "소프트웨어융합",     # 균형교양 제외영역 판정용(2022 당시 단과대 계열)
        "희망과목": ["컴퓨터비전"],   # 꼭 넣고 싶은 강의 — 시간표에 최우선 배치
        "선호": "오후", "목표학점": 21, "총이수학점": 66,
        "이수과목": [
            {"과목": "확률및통계", "학점": 3, "성적": "A0"},
            {"과목": "문제해결을위한글쓰기와발표", "학점": 3, "성적": "C+"},
            {"과목": "우주자연인간", "학점": 1, "성적": "B+"},
            {"과목": "일반물리학1", "학점": 3, "성적": "B0"},
            {"과목": "기초미적분학", "학점": 3, "성적": "A0"},
            {"과목": "신입생세미나A", "학점": 1, "성적": "P"},
            {"과목": "C프로그래밍및실습", "학점": 3, "성적": "B+"},
            {"과목": "고급C프로그래밍및실습", "학점": 3, "성적": "A0"},
            {"과목": "고급프로그래밍활용", "학점": 3, "성적": "A+"},
            {"과목": "서양철학:쟁점과토론", "학점": 3, "성적": "B+"},
            {"과목": "대학영어", "학점": 2, "성적": "A+"},
            {"과목": "신입생세미나B", "학점": 1, "성적": "C+"},
            {"과목": "C프로그래밍및실습", "학점": 3, "성적": "B0"},
            {"과목": "공학설계기초(산학프로젝트입문)", "학점": 3, "성적": "c+"},
            {"과목": "이산수학및프로그래밍", "학점": 3, "성적": "A+"},
            {"과목": "공업수학1", "학점": 3, "성적": "C+"},
            {"과목": "K-MOOC:코딩과스토리텔링", "학점": 1, "성적": "P"},
            {"과목": "현대예술의이해", "학점": 3, "성적": "B+"},
            {"과목": "채플1", "학점": 0.5, "성적": "P"},
            {"과목": "서양고전강독3", "학점": 1, "성적": "P"},
            {"과목": "수요집현강좌", "학점": 1, "성적": "P"},
            {"과목": "확률및통계", "학점": 3, "성적": "A+"},
            {"과목": "자료구조및실습", "학점": 3, "성적": "B+"},
            {"과목": "기계학습개론", "학점": 3, "성적": "A+"},
            {"과목": "인공지능과빅데이터", "학점": 3, "성적": "A+"},
            {"과목": "선형대수", "학점": 3, "성적": "A+"},
            {"과목": "창업과기업가정신1", "학점": 3, "성적": "P"},
            {"과목": "고급인공지능활용", "학점": 3, "성적": "A+"},
            {"과목": "경제학", "학점": 3, "성적": "A+"},
            {"과목": "컴퓨터구조", "학점": 3, "성적": "A0"},
            {"과목": "알고리즘및실습", "학점": 3, "성적": "A+"},
            {"과목": "기계학습실습", "학점": 3, "성적": "A+"},
            {"과목": "인공지능수학", "학점": 3, "성적": "B+"},
        ],
    }
    # force_auto=True: 하드코딩(검증층) 없이 수강편람 자동추출 DB만으로 진단
    # (다른 모든 학과·학번이 타는 일반화 경로를 내 프로필로 점검)
    advise(profile, force_auto=True)
