"""실제 병동 간호사 14명 명단과 병동 인원 기준 (데모 스크립트/테스트 공용).

Phase 2에서 웹 UI로 관리하게 되면 data/nurses.json으로 옮겨간다.
"""

from __future__ import annotations

from core.models import Nurse, NurseLevel, ShiftRequirement, ShiftType


def build_real_nurses() -> list[Nurse]:
    return [
        Nurse(name="공혜송", level=NurseLevel.SENIOR_CHARGE, weekday_only=True, dedicated_shift=ShiftType.D),
        Nurse(name="김성애", level=NurseLevel.SENIOR_CHARGE, excluded_shifts={ShiftType.E}, n_soft_consecutive_limit=2),
        Nurse(name="이수현", level=NurseLevel.SENIOR_CHARGE),
        Nurse(name="최낙안", level=NurseLevel.SENIOR_CHARGE, excluded_shifts={ShiftType.D}, n_soft_consecutive_limit=2),
        Nurse(name="정서정", level=NurseLevel.SENIOR_CHARGE),
        Nurse(name="신현아", level=NurseLevel.MIDDLE),
        Nurse(name="김희영", level=NurseLevel.MIDDLE),
        Nurse(name="김나영", level=NurseLevel.MIDDLE),
        Nurse(name="이진아", level=NurseLevel.JUNIOR),
        Nurse(name="정해주", level=NurseLevel.JUNIOR),
        Nurse(name="손세정", level=NurseLevel.JUNIOR),
        Nurse(name="김지현", level=NurseLevel.JUNIOR),
        Nurse(name="서은경", level=NurseLevel.NEW_JUNIOR),
        Nurse(name="최미리", level=NurseLevel.NEW_JUNIOR),
    ]


def ward_templates() -> tuple[tuple, tuple]:
    """(평일, 주말) 템플릿. 각각 (D, E, N) 순서.

    N: 매일 정확히 3명 (하드)
    D: 평일 3~4명 / 주말 2~4명 (하드 범위), 목표 4명 (소프트, 월요일 최우선)
    E: 평일 2~3명 / 주말 2~3명 (하드 범위), 목표 3명
    """
    weekday = (
        ShiftRequirement(minimum=3, maximum=4, target=4),
        ShiftRequirement(minimum=2, maximum=3, target=3),
        ShiftRequirement(minimum=3),
    )
    weekend = (
        ShiftRequirement(minimum=2, maximum=4, target=4),
        ShiftRequirement(minimum=2, maximum=3, target=3),
        ShiftRequirement(minimum=3),
    )
    return weekday, weekend
