"""
학사일정 데이터 + 날짜 파싱

수강편람의 "2026학년도 학사일정" 표(50개 이벤트, 이미 정리된 원본)를 기반으로
실제 date 객체로 변환해서, "D-day 계산"이나 "월별 정리"에 바로 쓸 수 있게 함.
"""

import re
from datetime import date

RAW_EVENTS = [
    (2026, 1, "2(금) - 3(토)", "2학기 기말고사 성적 마감"),
    (2026, 1, "26(월) - 2.1(일)", "1학기 복학, 휴학 신청"),
    (2026, 2, "10(화) - 13(금)", "1학기 수강신청"),
    (2026, 2, "20(금)", "제 84회 학위수여식"),
    (2026, 2, "23(월)", "입학식"),
    (2026, 2, "23(월) - 26(목)", "1학기 등록"),
    (2026, 3, "3(화)", "1학기 개강"),
    (2026, 3, "4(수) - 9(월)", "수강신청 과목 확인 및 변경"),
    (2026, 3, "4(수) - 17(화)", "교직신청"),
    (2026, 3, "25(수) - 27(금)", "수강신청과목 철회"),
    (2026, 4, "21(화) - 27(월)", "1학기 중간고사"),
    (2026, 4, "28(화) - 5.4(월)", "1학기 중간고사 성적 입력"),
    (2026, 5, "1(금)", "창립 86주년 기념휴일(창립일 : 1940. 5. 20)"),
    (2026, 5, "4(월) - 28(목)", "복수·부전공, 연계융합전공 신청"),
    (2026, 5, "5(화) - 9(토)", "1학기 중간고사 성적 열람 및 정정"),
    (2026, 5, "11(월) - 6.19(금)", "세종인재자기설계전공 신청"),
    (2026, 6, "1(월) - 4(목)", "하계 계절학기 수강신청"),
    (2026, 6, "1(월) - 12(금)", "전과 신청"),
    (2026, 6, "8(월) - 29(월)", "1학기 강의평가"),
    (2026, 6, "16(화) - 22(월)", "1학기 기말고사 및 수업결손 보충"),
    (2026, 6, "20(토) - 26(금)", "1학기 기말고사 성적 입력"),
    (2026, 6, "23(화)", "하계방학 시작 및 계절학기 개강"),
    (2026, 6, "27(토) - 7.1(수)", "1학기 기말고사 성적 열람 및 정정"),
    (2026, 7, "2(목) - 4(토)", "1학기 기말고사 성적 마감"),
    (2026, 7, "27(월) - 8.2(일)", "2학기 복학, 휴학 신청"),
    (2026, 8, "14(금) - 21(금)", "2학기 수강신청"),
    (2026, 8, "21(금)", "제 84회 후기 학위수여식"),
    (2026, 8, "25(화) - 28(금)", "2학기 등록"),
    (2026, 9, "1(화)", "2학기 개강"),
    (2026, 9, "2(수) - 7(월)", "수강신청과목 확인 및 변경"),
    (2026, 9, "23(수) - 28(월)", "수강신청과목 철회"),
    (2026, 10, "20(화) - 26(월)", "2학기 중간고사"),
    (2026, 10, "27(화) - 11.2(월)", "2학기 중간고사 성적 입력"),
    (2026, 11, "2(월) - 26(목)", "복수·부전공, 연계융합전공 신청"),
    (2026, 11, "3(화) - 7(토)", "2학기 중간고사 성적 열람 및 정정"),
    (2026, 11, "9(월) - 12.18(금)", "세종인재자기설계전공 신청"),
    (2026, 12, "1(화) - 3(목)", "동계 계절학기 수강신청"),
    (2026, 12, "1(화) - 11(금)", "전과 신청"),
    (2026, 12, "1(화) - 25(금)", "전공 배정 신청"),
    (2026, 12, "8(화) - 31(목)", "2학기 강의평가"),
    (2026, 12, "15(화) - 21(월)", "2학기 기말고사 및 수업결손 보충"),
    (2026, 12, "22(화) - 28(월)", "2학기 기말고사 성적 입력"),
    (2026, 12, "22(화)", "동계방학 시작 및 계절학기 개강"),
    (2026, 12, "29(화) - 1.2(토)", "2학기 기말고사 성적 열람 및 정정"),
    (2027, 1, "3(일) - 5(화)", "2학기 기말고사 성적 마감"),
    (2027, 1, "26(화) - 2.1(월)", "1학기 복학, 휴학 신청"),
    (2027, 2, "15(월) - 18(목)", "1학기 수강신청"),
    (2027, 2, "19(금)", "제 85회 학위수여식"),
    (2027, 2, "22(월)", "입학식"),
    (2027, 2, "22(월) - 25(목)", "1학기 등록"),
]

HOLIDAYS = [
    (2026, 3, 2, "3·1절 대체휴일"),
    (2026, 5, 5, "어린이날"),
    (2026, 5, 25, "석가탄신일 대체휴일"),
    (2026, 6, 3, "2026 지방선거일"),
    (2026, 8, 17, "광복절 대체휴일"),
    (2026, 9, 24, "추석"),
    (2026, 9, 25, "추석"),
    (2026, 9, 26, "추석"),
    (2026, 10, 5, "개천절 대체휴일"),
    (2026, 10, 9, "한글날"),
    (2026, 12, 25, "성탄절"),
]


def _parse_part(part, default_year, default_month):
    """'4(월)' 또는 '5.4(월)' 형태를 (year, month, day)로 변환."""
    part = part.strip()
    m = re.match(r"(?:(\d+)\.)?(\d+)\(", part)
    if not m:
        raise ValueError(f"파싱 실패: {part}")
    month_part, day_part = m.group(1), m.group(2)
    day = int(day_part)
    if month_part:
        month = int(month_part)
        year = default_year
        if month < default_month:  # 연도가 넘어가는 경우 (예: 12월 -> 1월)
            year += 1
        return year, month, day
    return default_year, default_month, day


def parse_date_range(year, month, date_str):
    """'4(월) - 28(목)' 또는 '20(금)' 형태를 (start_date, end_date)로 변환."""
    parts = [p.strip() for p in date_str.split(" - ")]
    start_y, start_m, start_d = _parse_part(parts[0], year, month)
    start_date = date(start_y, start_m, start_d)

    if len(parts) == 2:
        end_y, end_m, end_d = _parse_part(parts[1], year, month)
        end_date = date(end_y, end_m, end_d)
    else:
        end_date = start_date

    return start_date, end_date


def get_all_events():
    """전체 이벤트를 {start, end, event, month} 딕셔너리 리스트로 반환 (start 기준 정렬)."""
    events = []
    for year, month, date_str, event in RAW_EVENTS:
        start, end = parse_date_range(year, month, date_str)
        events.append({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "event": event,
            "month_label": f"{year}년 {month}월",
        })
    events.sort(key=lambda e: e["start"])
    return events


def get_upcoming_events(today=None, limit=8):
    """오늘 기준으로 아직 끝나지 않은 일정들을 가까운 순서로 반환, D-day 포함."""
    if today is None:
        today = date.today()
    events = get_all_events()
    upcoming = []
    for e in events:
        end_date = date.fromisoformat(e["end"])
        if end_date >= today:
            start_date = date.fromisoformat(e["start"])
            d_day = (start_date - today).days
            upcoming.append({**e, "d_day": d_day})
    upcoming.sort(key=lambda e: e["start"])
    return upcoming[:limit]


def get_holidays():
    """공휴일 목록을 {date, name} 형태로 반환."""
    return [
        {"date": date(y, m, d).isoformat(), "name": name}
        for y, m, d, name in HOLIDAYS
    ]