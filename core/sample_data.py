"""Sample ward roster and default staffing templates."""

from __future__ import annotations

from core.models import Nurse, NurseLevel, ShiftRequirement, ShiftType


def build_real_nurses() -> list[Nurse]:
    return [
        Nurse(
            name="공혜송",
            level=NurseLevel.SENIOR_CHARGE,
            weekday_only=True,
            allowed_shifts={ShiftType.D},
            max_n_hard=0,
        ),
        Nurse(
            name="김성애",
            level=NurseLevel.SENIOR_CHARGE,
            allowed_shifts={ShiftType.D, ShiftType.N},
            excluded_shifts={ShiftType.E},
            n_soft_consecutive_limit=2,
        ),
        Nurse(name="이수현", level=NurseLevel.SENIOR_CHARGE),
        Nurse(
            name="최낙안",
            level=NurseLevel.SENIOR_CHARGE,
            allowed_shifts={ShiftType.E, ShiftType.N},
            excluded_shifts={ShiftType.D},
            n_soft_consecutive_limit=2,
        ),
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
    """Return default (weekday, weekend) templates, each ordered as (D, E, N)."""
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
