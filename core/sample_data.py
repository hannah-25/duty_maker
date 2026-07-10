"""Sample ward roster and default staffing templates."""

from __future__ import annotations

from core.models import Nurse, NurseLevel, ShiftRequirement, ShiftType


def build_real_nurses() -> list[Nurse]:
    return [
        Nurse(
            name="강하은",
            level=NurseLevel.SENIOR_CHARGE,
            weekday_only=True,
            allowed_shifts={ShiftType.D},
            max_n_hard=0,
        ),
        Nurse(
            name="박서윤",
            level=NurseLevel.SENIOR_CHARGE,
            allowed_shifts={ShiftType.D, ShiftType.N},
            excluded_shifts={ShiftType.E},
            n_soft_consecutive_limit=2,
        ),
        Nurse(name="조민지", level=NurseLevel.SENIOR_CHARGE),
        Nurse(
            name="윤지호",
            level=NurseLevel.SENIOR_CHARGE,
            allowed_shifts={ShiftType.E, ShiftType.N},
            excluded_shifts={ShiftType.D},
            n_soft_consecutive_limit=2,
        ),
        Nurse(name="한소율", level=NurseLevel.SENIOR_CHARGE),
        Nurse(name="오다은", level=NurseLevel.MIDDLE),
        Nurse(name="임가은", level=NurseLevel.MIDDLE),
        Nurse(name="배수민", level=NurseLevel.MIDDLE),
        Nurse(name="문지우", level=NurseLevel.JUNIOR),
        Nurse(name="노은서", level=NurseLevel.JUNIOR),
        Nurse(name="유하윤", level=NurseLevel.JUNIOR),
        Nurse(name="곽서현", level=NurseLevel.JUNIOR),
        Nurse(name="백지원", level=NurseLevel.NEW_JUNIOR),
        Nurse(name="남예린", level=NurseLevel.NEW_JUNIOR),
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
