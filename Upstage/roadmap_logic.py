"""
이수체계도 관련 순수 로직 (Streamlit 의존성 없음)

server.py(FastAPI)와 personal_roadmap.py(Streamlit)가 이 모듈을 공통으로 import해서 씀.
UI 프레임워크에 얽매이지 않는 데이터 처리 로직만 여기 모아둠.
"""

import os
import re
import pandas as pd

EXCEL_DIR = "curriculum_excels"

CATEGORY_INFO = {
    "공필": {"name": "공통필수", "color": "#F0997B"},
    "균필": {"name": "균형교양필수", "color": "#B4B2A9"},
    "기필": {"name": "학문기초교양필수", "color": "#F0997B"},
    "전기": {"name": "전공기초", "color": "#5DCAA5"},
    "전필": {"name": "전공필수", "color": "#EF9F27"},
    "전선": {"name": "전공선택", "color": "#85B7EB"},
}
CATEGORY_ORDER = ["공필", "균필", "기필", "전기", "전필", "전선"]


def scan_available_excels(excel_dir=EXCEL_DIR):
    """폴더 안의 '학과명_연도.xlsx' 파일들을 스캔해서 {학과: [연도, ...]} 형태로 정리."""
    available = {}
    if not os.path.isdir(excel_dir):
        return available
    for fname in os.listdir(excel_dir):
        if not fname.lower().endswith(".xlsx"):
            continue
        m = re.match(r"(.+)_(\d{4})\.xlsx$", fname)
        if not m:
            continue
        dept, year = m.group(1), int(m.group(2))
        available.setdefault(dept, []).append(year)
    for dept in available:
        available[dept].sort(reverse=True)
    return available


def load_and_clean(file_or_path):
    df = pd.read_excel(file_or_path, skiprows=1)
    df.columns = ["순번", "학년", "개설년도", "개설학기", "교과목명", "이수구분", "학점정보"]
    df = df.iloc[1:].reset_index(drop=True)
    df["학년"] = df["학년"].astype(int)
    df["학점"] = df["학점정보"].astype(str).str.split("/").str[0].astype(float)

    def get_semester(row):
        if row["학년"] == 0:
            return "교양선택\n(연도무관)"
        ge = str(row["개설학기"])
        has1, has2 = "1학기" in ge, "2학기" in ge
        if has1 and has2:
            return f"{row['학년']}학년\n통합"
        if has1:
            return f"{row['학년']}학년\n1학기"
        if has2:
            return f"{row['학년']}학년\n2학기"
        return "기타"

    df["학기라벨"] = df.apply(get_semester, axis=1)
    return df


def semester_sort_key(label):
    if "교양선택" in label:
        return (-1, 0)
    if "기타" in label:
        return (99, 0)
    year = int(label[0])
    if "통합" in label:
        return (year, 0.5)
    sem = 1 if "1학기" in label else 2
    return (year, sem)
