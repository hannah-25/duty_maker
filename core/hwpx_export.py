"""정해진 hwpx 양식(templates/duty_template.hwpx)에 생성 결과를 채워 내보낸다.

hwpx는 OWPML XML들을 담은 zip이므로, 양식의 표 구조·스타일은 그대로 두고
셀 텍스트/글자색/배경만 바꿔치기한다. 아래 스타일 ID들은 이 템플릿 파일에
정의된 값이라 템플릿을 교체하면 함께 갱신해야 한다.
"""

from __future__ import annotations

import io
import zipfile
from copy import deepcopy
from datetime import date
from pathlib import Path

from lxml import etree

from core.models import Assistant, Nurse, ShiftType, month_dates

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {"hp": HP}

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "duty_template.hwpx"
SECTION_NAME = "Contents/section0.xml"

# 글자 스타일 (모두 굵게): 검정 근무, 빨강 오프 X, 파랑(연차·신청 반영)
CHAR_BLACK = "8"
CHAR_RED = "20"
CHAR_BLUE = "16"
CHAR_LABEL = "18"  # 구분/이름 칸

# 평일 배경 -> 주말·공휴일(연주황) 배경 페어. 테두리 종류별로 짝이 다르다.
FILL_TO_WEEKEND = {"20": "23", "21": "24", "22": "25"}
FILL_TO_WEEKDAY = {weekend: weekday for weekday, weekend in FILL_TO_WEEKEND.items()}

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일 "]  # 템플릿 표기 그대로 ("일 ")

DAY_COL_START = 2  # colAddr 2 == 1일
COL_E, COL_N, COL_OFF = 33, 34, 35


def _tag(name: str) -> str:
    return f"{{{HP}}}{name}"


def _cell_col(tc) -> int:
    return int(tc.find("hp:cellAddr", NS).get("colAddr"))


def _cells_by_col(tr) -> dict[int, object]:
    return {_cell_col(tc): tc for tc in tr.findall("hp:tc", NS)}


def _set_cell_text(tc, text: str, char_pr: str) -> None:
    """셀을 단일 문단·단일 run으로 교체. 빈 텍스트면 run만 남긴다 (셀 내 줄바꿈은 자동 wrap에 맡김)."""
    paragraphs = tc.findall(".//hp:p", NS)
    p = paragraphs[0]
    for extra in paragraphs[1:]:
        extra.getparent().remove(extra)
    for run in p.findall("hp:run", NS):
        p.remove(run)
    run = etree.Element(_tag("run"), charPrIDRef=char_pr)
    if text:
        t = etree.SubElement(run, _tag("t"))
        t.text = text
    p.insert(0, run)


def _set_day_fill(tc, is_off_day: bool) -> None:
    current = tc.get("borderFillIDRef")
    mapping = FILL_TO_WEEKEND if is_off_day else FILL_TO_WEEKDAY
    tc.set("borderFillIDRef", mapping.get(current, current))


def _duty_text(shift: ShiftType, is_blue: bool) -> tuple[str, str]:
    if shift == ShiftType.AL:
        return "연", CHAR_BLUE
    if shift == ShiftType.O:
        return "X", CHAR_BLUE if is_blue else CHAR_RED
    return shift.value, CHAR_BLUE if is_blue else CHAR_BLACK


def _nurse_role(index: int) -> str:
    if index == 0:
        return "수간호사"
    if index == 1:
        return "책임간호사"
    return "간호사"


def export_schedule_hwpx(
    nurses: list[Nurse],
    year: int,
    month: int,
    assignments: dict[tuple[str, date], ShiftType],
    holidays: set[date],
    off_target_value: int,
    blue_cells: set[tuple[str, date]],
    assistants: list[Assistant] | None = None,
    assistant_marks: dict[tuple[str, date], ShiftType] | None = None,
) -> bytes:
    """근무표를 양식에 채운 hwpx 파일 바이트를 반환한다.

    blue_cells: 파란색으로 표시할 (간호사이름, 날짜) — 반영된 듀티 신청 칸.
    assistants: 하단 행에 표시할 보조 인력. assistant_marks의 희망 신청만 파란색으로
    표시하고 나머지 칸은 수기 기입용으로 비워 둔다.
    """
    assistants = assistants or []
    assistant_marks = assistant_marks or {}
    template_bytes = TEMPLATE_PATH.read_bytes()
    with zipfile.ZipFile(io.BytesIO(template_bytes)) as zf:
        section_xml = zf.read(SECTION_NAME)
        entries = [(item, zf.read(item.filename)) for item in zf.infolist()]

    root = etree.fromstring(section_xml)
    days = month_dates(year, month)
    off_days = {d for d in days if d.weekday() >= 5 or d in holidays}

    # --- 제목 ---------------------------------------------------------------
    for t in root.iter(_tag("t")):
        if t.text and "근무표" in t.text:
            t.text = f"집중치료실 {month}월 근무표(OFF {off_target_value}개)"
            break

    # --- 표 골격: 헤더 2행 + 간호사 행들 + 간호조무사 행 ----------------------
    tbl = root.find(".//hp:tbl", NS)
    rows = tbl.findall("hp:tr", NS)
    header_day, header_weekday = rows[0], rows[1]
    assistant_proto = rows[-1]  # 간호조무사 행 (보조 인력 행 스타일 원본)
    proto_first, proto_inner = rows[2], rows[3]  # 첫 행/내부 행 (테두리 스타일이 다름)

    nurse_rows = []
    for i, nurse in enumerate(nurses):
        nurse_rows.append(deepcopy(proto_first if i == 0 else proto_inner))
    assistant_rows = [deepcopy(assistant_proto) for _ in assistants]
    for tr in rows[2:-1]:
        tbl.remove(tr)
    for tr in [*nurse_rows, *assistant_rows]:
        assistant_proto.addprevious(tr)
    tbl.remove(assistant_proto)

    # --- 헤더: 날짜 숫자 + 요일 + 주말/공휴일 배경 ----------------------------
    day_cells = _cells_by_col(header_day)
    weekday_cells = _cells_by_col(header_weekday)
    for j in range(31):
        col = DAY_COL_START + j
        in_month = j < len(days)
        is_off = in_month and days[j] in off_days
        _set_cell_text(day_cells[col], str(j + 1) if in_month else "", "17")
        _set_day_fill(day_cells[col], is_off)
        _set_cell_text(weekday_cells[col], WEEKDAY_KR[days[j].weekday()] if in_month else "", "17")
        _set_day_fill(weekday_cells[col], is_off)

    # --- 간호사 행 채우기 -----------------------------------------------------
    for i, (nurse, tr) in enumerate(zip(nurses, nurse_rows)):
        cells = _cells_by_col(tr)
        _set_cell_text(cells[0], _nurse_role(i), CHAR_LABEL)
        _set_cell_text(cells[1], nurse.name, CHAR_LABEL)

        seq = [assignments[(nurse.name, d)] for d in days]
        for j in range(31):
            col = DAY_COL_START + j
            if j < len(days):
                shift = seq[j]
                text, char_pr = _duty_text(shift, (nurse.name, days[j]) in blue_cells)
                _set_cell_text(cells[col], text, char_pr)
                _set_day_fill(cells[col], days[j] in off_days)
            else:
                _set_cell_text(cells[col], "", CHAR_BLACK)
                _set_day_fill(cells[col], False)

        e_count = seq.count(ShiftType.E)
        n_count = seq.count(ShiftType.N)
        off_dev = seq.count(ShiftType.O) - off_target_value
        _set_cell_text(cells[COL_E], str(e_count) if e_count else "", CHAR_BLACK)
        _set_cell_text(cells[COL_N], str(n_count) if n_count else "", CHAR_BLACK)
        _set_cell_text(cells[COL_OFF], str(off_dev) if off_dev else "", CHAR_BLACK)

    # --- 보조 인력 행: 희망 신청만 파란색 표시, 나머지는 수기 기입용으로 비움 ----
    for assistant, tr in zip(assistants, assistant_rows):
        cells = _cells_by_col(tr)
        _set_cell_text(cells[0], assistant.role, CHAR_LABEL)
        _set_cell_text(cells[1], assistant.name, CHAR_LABEL)
        for j in range(31):
            col = DAY_COL_START + j
            mark = assistant_marks.get((assistant.name, days[j])) if j < len(days) else None
            if mark is not None:
                text = "X" if mark in (ShiftType.O, ShiftType.AL) else mark.value
                _set_cell_text(cells[col], text, CHAR_BLUE)
            else:
                _set_cell_text(cells[col], "", CHAR_BLACK)
            _set_day_fill(cells[col], j < len(days) and days[j] in off_days)
        for col in (COL_E, COL_N, COL_OFF):
            _set_cell_text(cells[col], "", CHAR_BLACK)

    # --- 행 주소/행 수 갱신 ----------------------------------------------------
    all_rows = tbl.findall("hp:tr", NS)
    for row_idx, tr in enumerate(all_rows):
        for tc in tr.findall("hp:tc", NS):
            tc.find("hp:cellAddr", NS).set("rowAddr", str(row_idx))
    tbl.set("rowCnt", str(len(all_rows)))

    new_section = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    # --- zip 재조립 (mimetype은 무압축 첫 항목 유지) ---------------------------
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for item, data in entries:
            if item.filename == SECTION_NAME:
                data = new_section
            compress = zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED
            zf.writestr(item.filename, data, compress_type=compress)
    return out.getvalue()
