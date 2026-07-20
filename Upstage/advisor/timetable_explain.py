# -*- coding: utf-8 -*-
"""추천 시간표 해설 — 선택 기능(server.TT_EXPLAIN 로 on/off, 웹에서 안 써도 무방).

설계: '무엇을 하기 좋은가'라는 의미는 시간표의 구조에서 결정론적으로 정해진다.
그래서 코드가 '의미 태그'를 뽑고(_tags), Solar는 그 태그를 자연스러운 한두 문장으로
다듬기만 한다(temperature 0). 같은 구조 → 같은 태그 → 같은 설명(안정성 보장).
Solar 미사용/실패 시엔 태그 문장을 그대로 이어 붙여 폴백한다(LLM 없이도 동작).

핵심 규칙:
 - 사이버/온라인(이러닝) 과목은 '그 시간에 학교에 있을 필요가 없는' 과목이라, 대면
   스케줄 집계에서 빼고 '유연 과목'으로만 표기한다(오후 사이버를 오후 부담으로 세지 않음).
 - 사용자가 고른 선호 시간대를 되풀이(오전 골랐으니 오전이 좋다)하지 않는다. 해설의 가치는
   '그 결과 생긴 구조가 무엇을 가능하게 하는가'다.
"""

_WEEKDAYS = ["월", "화", "수", "목", "금"]


def _is_online(c):
    """물리적 시간 점유가 없는 과목(사이버강좌·e-러닝)."""
    return bool(c.get("사이버") or c.get("이러닝"))


_LUNCH = (12 * 60, 13 * 60)     # 점심 시간대 [12:00, 13:00)


def _features(timetable, 요청공강=frozenset(), 점심차단=False):
    """시간표(직렬화된 과목 리스트)의 구조적 사실. 시간대 관련은 '대면(오프라인)'만 집계하고,
    과목 성격(전공/교양·영어·온라인)은 전체 기준으로 센다.
    요청공강: 사용자가 일부러 비운 요일(그 밖의 공강은 '보너스'). 점심차단: 사용자가 차단시간으로
    점심을 이미 비웠는지(그렇다면 '점심 보존'을 생색내지 않음)."""
    by_day = {}
    영어 = 전공 = 교양 = 온라인 = 0
    for c in timetable:
        구분 = str(c.get("이수구분", ""))
        if "전공" in 구분:
            전공 += 1
        elif "교양" in 구분:
            교양 += 1
        if "영어" in str(c.get("언어", "")):
            영어 += 1
        if _is_online(c):
            온라인 += 1
            continue
        for d, s, e in c.get("slots", []):
            by_day.setdefault(d, []).append((int(s), int(e)))
    오전블록 = 오후블록 = 큰공강 = 연강최대 = 0
    일찍끝나는날, 늦게끝나는날 = [], []
    점심보존 = False
    for _d, iv in by_day.items():
        iv.sort()
        for s, e in iv:
            if s < 12 * 60:
                오전블록 += 1
            else:
                오후블록 += 1
        endN = iv[-1][1]
        if endN <= 13 * 60:            # 그 날 마지막 대면 수업이 오후 1시 전에 끝
            일찍끝나는날.append(_d)
        if endN >= 18 * 60:            # 저녁 6시 이후까지
            늦게끝나는날.append(_d)
        # 점심 보존: 점심 앞뒤로 수업이 있는데 점심시간대는 비어 있는 날 (자연 발생분만)
        앞 = any(e <= _LUNCH[0] for _s, e in iv)
        뒤 = any(s >= _LUNCH[1] for s, _e in iv)
        중 = any(s < _LUNCH[1] and _LUNCH[0] < e for s, e in iv)
        if 앞 and 뒤 and not 중:
            점심보존 = True
        for (_s1, e1), (s2, _e2) in zip(iv, iv[1:]):
            if s2 - e1 >= 180:         # 같은 날 3시간 이상 공강
                큰공강 += 1
        # 가장 긴 연속(연강) 블록의 길이(분) — 15분 이내로 이어지면 한 덩어리로 본다.
        # '몇 쌍'이 아니라 '얼마나 길게 이어지나'로 봐야 성격을 가르는 연강만 잡힌다.
        run_s, run_e = iv[0]
        for s, e in iv[1:]:
            if s - run_e <= 15:
                run_e = e
            else:
                연강최대 = max(연강최대, run_e - run_s)
                run_s, run_e = s, e
        연강최대 = max(연강최대, run_e - run_s)
    공강요일 = [d for d in _WEEKDAYS if d not in by_day]
    return {
        "대면과목수": sum(1 for c in timetable if not _is_online(c)),
        "온라인과목수": 온라인, "영어강의수": 영어, "전공수": 전공, "교양수": 교양,
        "공강요일": 공강요일,
        "보너스공강": [d for d in 공강요일 if d not in 요청공강],  # 요청 안 했는데 생긴 자유 요일
        "요청공강": [d for d in 공강요일 if d in 요청공강],
        "오전블록": 오전블록, "오후블록": 오후블록,
        "일찍끝나는날": [d for d in _WEEKDAYS if d in 일찍끝나는날],
        "늦게끝나는날": [d for d in _WEEKDAYS if d in 늦게끝나는날],
        "큰공강수": 큰공강, "연강최대분": 연강최대,
        "점심보존": 점심보존 and not 점심차단,
    }


def _tags(f):
    """구조적 사실 → 태그 [(코드, 역할, 사실), ...]. 여기서는 '사실'만 확정한다(완성된 조언
    문장이 아님). 역할은 Solar가 어떻게 굴릴지 알려주는 힌트다:
      · 전략  = 지금의 선택이 학기 이후에 갖는 의미 → '지금 이러면 나중에 이렇다'는 앞을 내다본 조언
      · 기회  = 활용할 여지 → 무엇을 하면 좋을지 구체적 행동 제안
      · 리스크 = 미리 대비할 점 → 주의·대비를 짚기
      · 정보  = 중립 특징
    새내기가 잘 모를 '이면의 함의'(전략·기회)를 앞쪽에 두고, 눈에 바로 보이는 것(연강·공강)은
    뒤에 둔다. 상위 몇 개를 요약에 쓴다. 바뀐 과목이 하나여도 태그가 달라지면 설명이 갈린다."""
    tags = []
    # 1. 학기 전략 — 지금 선택이 나중에 갖는 의미(새내기가 가장 모르는 이면)
    if f["전공수"] and f["전공수"] > f["교양수"]:
        tags.append(("전공중심", "전략",
                     "전공 위주라 이번 학기는 빡세지만, 전공 학점을 앞당겨 쌓는 셈이라 고학년 때 시간표가 크게 가벼워져 취업·자격증 준비에 몰두할 수 있다"))
    elif f["교양수"] and f["교양수"] > f["전공수"]:
        tags.append(("교양중심", "전략",
                     "교양 위주라 학업 강도가 낮은 편이라, 이 여유를 자격증·대외활동·어학 같은 데 미리 투자해 두면 나중에 크게 앞선다"))
    # 2. 온라인 비중 — 실제 구속 시간이 보이는 것보다 적음(새내기가 과소평가)
    if f["온라인과목수"] >= 2:
        tags.append(("온라인많음", "기회",
                     f"온라인 과목이 {f['온라인과목수']}개라, 시간표상 학점보다 실제 등교·구속 시간이 훨씬 적다"))
    elif f["온라인과목수"] == 1:
        tags.append(("온라인", "기회",
                     "온라인 과목 1개는 정해진 기간에 편할 때 들으면 돼, 그 시간은 사실상 자유 시간이다"))
    # 3. 영어강의 — 학점 유리(인사이더 팁, 단정 아님)
    if f["영어강의수"] >= 2:
        tags.append(("영어강의", "기회",
                     f"영어 강의가 {f['영어강의수']}개인데, 영어 강의는 학점을 잘 받기 유리하다는 얘기가 많아 학점 관리에 도움이 될 수 있다"))
    # 4. 의외의 / 요청 공강요일 — 통 시간을 주간 루틴으로
    if f["보너스공강"]:
        요일 = "·".join(f["보너스공강"]) + "요일"
        tags.append(("보너스공강", "기회",
                     f"요청하지 않았는데 {요일}이 통째로 비어, 고정 알바나 자격증 수업 같은 주간 루틴을 심기 좋다"))
    elif f["요청공강"]:
        요일 = "·".join(f["요청공강"]) + "요일"
        tags.append(("요청공강", "기회", f"{요일}을 비워 둬 그날 통째로 쓸 수 있어, 주간 루틴을 심기 좋다"))
    # 5. 대면 시간대 형태
    if f["대면과목수"] and f["오후블록"] == 0:
        tags.append(("오전집중", "기회", "대면 수업이 오전에 끝나 오후가 매일 통째로 빈다"))
    elif f["대면과목수"] and f["오전블록"] == 0:
        tags.append(("오후시작", "기회", "오전이 비어 하루를 여유롭게 늦게 시작할 수 있다"))
    # 6. 연강 / 큰공강 — 눈에 보이지만 대비가 필요한 리스크(뒤로)
    if f["연강최대분"] >= 180:          # 3시간 이상 쭉 이어지는 연강 구간
        tags.append(("연강", "리스크", "쉬는 시간 없이 3시간 넘게 이어지는 연강이 있어 그날은 체력 소모가 크다"))
    if f["큰공강수"]:
        tags.append(("큰공강", "리스크", "같은 날 3시간 이상 뜨는 큰 공강이 있어 자칫 시간이 붕 뜬다"))
    # 7. 점심 보존(자연 발생분만)
    if f["점심보존"]:
        tags.append(("점심보존", "기회", "수업 사이 점심시간이 비어 끼니를 규칙적으로 챙기기 좋다"))
    # 8. 매일 꽉 참 / 일찍 끝남
    if not f["공강요일"] and f["늦게끝나는날"]:
        tags.append(("빡빡", "리스크", "평일 내내 수업이 있고 늦게 끝나는 날도 있어 전반적으로 빡빡하다"))
    elif not f["공강요일"]:
        tags.append(("꽉참", "정보", "평일마다 수업이 고르게 있어 공강 없이 알차다"))
    if f["일찍끝나는날"] and not any(c == "오전집중" for c, *_ in tags):
        요일 = "·".join(f["일찍끝나는날"]) + "요일"
        tags.append(("일찍끝남", "기회", f"{요일}은 일찍 끝나 오후가 길다"))
    return tags


_TOP = 3   # 요약에 쓸 상위 태그 수 (성격을 가르는 순으로 결정론적 선택 → 안정성 유지)


def _base_summary(tags):
    """LLM 없이 쓰는 폴백 요약 — 상위 태그의 사실을 이어 붙임(코치 어투는 아님, 폴백용)."""
    return " ".join(t for _c, _r, t in tags[:2])


def explain(alts, 요청공강=frozenset(), 점심차단=False, use_llm=True):
    """추천안들에 'summary'를 붙인다. 결정론적 태그가 '사실+역할'을 정하고 Solar는 그 사실로부터
    행동을 이끌어내는 코치 조언을 쓴다. 여러 안을 함께 볼 때는 '그 안만의 구별되는 태그'를
    앞으로 끌어올려, 과목 하나 차이(연강 등)라도 조언이 그 차이를 반드시 짚게 한다.
    태그가 완전히 같은 안들은 조언도 같다(안정성). use_llm=False/실패 시 사실 문장으로 폴백."""
    if not alts:
        return
    tag_lists = [_tags(_features(a.get("timetable", []), 요청공강, 점심차단)) for a in alts]
    code_sets = [{c for c, _r, _t in tl} for tl in tag_lists]
    공통 = set.intersection(*code_sets) if code_sets else set()   # 모든 안이 공유하는 태그
    per = []
    for a, tl in zip(alts, tag_lists):
        구별 = [x for x in tl if x[0] not in 공통]                # 이 안만의 특징 (먼저)
        공유 = [x for x in tl if x[0] in 공통]
        정렬 = 구별 + 공유
        a["_tags"] = [c for c, _r, _t in 정렬]                    # 검증·디버깅용
        a["summary"] = _base_summary(정렬)                        # 폴백 먼저 채워둠
        per.append({"안": a["label"],
                    "핵심": [{"역할": r, "사실": t} for _c, r, t in 정렬[:_TOP]]})
    if not use_llm:
        return
    try:
        _polish(alts, per)
    except Exception:
        pass                                            # 폴백 summary 유지


def _polish(alts, per):
    """Solar가 각 안의 확정된 '사실+역할'로부터 행동을 이끌어내는 코치 조언을 쓴다."""
    from openai import OpenAI
    from chatbot.pipeline import UPSTAGE_API_KEY, CHAT_BASE_URL
    import json

    if not any(x["핵심"] for x in per):                 # 조언할 사실이 없으면 호출 생략
        return
    schema = {
        "type": "object",
        "properties": {"해설들": {"type": "array", "items": {"type": "object",
            "properties": {"안": {"type": "string"}, "해설": {"type": "string"}},
            "required": ["안", "해설"]}}},
        "required": ["해설들"],
    }
    client = OpenAI(api_key=UPSTAGE_API_KEY, base_url=CHAT_BASE_URL)
    resp = client.chat.completions.create(
        model="solar-pro2", temperature=0.3,
        messages=[
            {"role": "system", "content": (
                "너는 대학생 수강신청 코치다. 각 안의 '핵심'은 그 시간표에 대해 코드가 확정한 사실이며, "
                "사실마다 '역할'이 붙어 있다. 역할에 맞게 굴려라:\n"
                "· 전략 → '지금 이렇게 해 두면 나중에 이렇게 된다'처럼 앞을 내다보는 조언을 해라.\n"
                "· 기회 → 그 여유·이점으로 무엇을 하면 좋을지 구체적 행동(자격증·알바·루틴·자기계발 등)을 제안해라.\n"
                "· 리스크 → 미리 대비하라고 짚어라.\n"
                "· 정보 → 중립적으로만 언급.\n"
                "목표: 학생이 시간표만 봐도 아는 사실(연강이 있다·금요일이 빈다 같은 눈에 보이는 것)은 "
                "짧게 스치고, **새내기는 잘 모를 이면의 함의와 그로부터 할 행동**을 중심으로 조언해라. "
                "즉 설명이 아니라 '그래서 이렇게 해봐'로 이어지게.\n"
                "지켜라: (1) 핵심에 없는 사실은 지어내지 마라(교수·과제·시험 등). (2) 사용자가 고른 "
                "시간대를 '좋다'고 되풀이하지 마라. (3) 인과가 어긋나는 조언 금지(예: 늦게 끝나는 날 "
                "저녁에 뭘 하라는 식). (4) 핵심이 비슷한 안은 결론도 비슷하게. (5) 친근한 '~요' 말투로 "
                "2~3문장, 억지로 다 담지 말고 앞쪽 사실 위주로."
            )},
            {"role": "user", "content": json.dumps(per, ensure_ascii=False)},
        ],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "tt_summaries", "schema": schema}},
    )
    by = {d["안"]: d["해설"] for d in json.loads(resp.choices[0].message.content).get("해설들", [])}
    for a in alts:
        if by.get(a["label"]):
            a["summary"] = by[a["label"]]
