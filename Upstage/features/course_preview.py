"""
과목 미리보기 - 로드맵에서 과목 클릭 시 간략 설명 제공

기존 pipeline.py의 챗봇(수강편람 문서에서만 답하는 방식)과는 다르게,
이건 Solar Pro 3의 일반 지식을 그대로 활용해서 "이 과목이 대략 뭘 배우는 과목인지"
설명하는 용도. 수강편람에 없는 일반 전공과목 설명이 목적이라 RAG를 거치지 않음.

주의: 세종대학교 고유 규정(학점, 이수구분 등)은 이 함수로 답하면 안 됨 —
      그건 반드시 기존 RAG 챗봇(pipeline.ask)을 사용해야 정확함.
      이 함수는 "일반적으로 이런 걸 배우는 과목이다" 수준의 참고용 설명만 담당.
"""

import json
import os
from openai import OpenAI

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 프로젝트 루트
UPSTAGE_API_KEY = json.load(open(os.path.join(_ROOT, "secrets.json")))["UPSTAGE_API_KEY"]
CHAT_BASE_URL = "https://api.upstage.ai/v1"

SYSTEM_PROMPT = (
    "너는 대학교 과목 소개를 도와주는 도우미야. "
    "사용자가 과목명 하나를 주면, 그 과목이 일반적으로 대학 커리큘럼에서 "
    "무엇을 배우는 과목인지 2~3문장으로 간단하고 쉽게 설명해줘. "
    "특정 대학의 정확한 학점, 이수구분, 개설학기 같은 세부 행정 정보는 "
    "절대 언급하지 마 (그건 학교마다 다르고 이 설명의 범위 밖이야). "
    "순수하게 '이 과목이 다루는 주제/내용'에만 집중해서 설명해. "
     "이 과목들은 전부 세종대학교의 과목이야. 세종대학교에는 수의학과, 의학과, 약학과가 없으니, "
    "과목명에 '수의', '의학', '약학' 같은 표현이 들어가도 해당 전공 분야의 전문 과목일 가능성은 낮아. "
    "과목명만으로 무슨 과목인지 짐작이 안 되면, 억지로 지어내지 말고 "
    "'과목명만으로는 구체적인 내용을 파악하기 어렵습니다'라고 답해."
)


def explain_course(course_name):
    client = OpenAI(api_key=UPSTAGE_API_KEY, base_url=CHAT_BASE_URL)
    resp = client.chat.completions.create(
        model="solar-pro3",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"'{course_name}' 과목에 대해 설명해줘."},
        ],
    )
    return resp.choices[0].message.content


if __name__ == "__main__":
    import sys
    course = sys.argv[1] if len(sys.argv) > 1 else "컴퓨터구조"
    print(explain_course(course))
