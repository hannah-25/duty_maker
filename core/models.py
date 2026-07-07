from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Optional


class ShiftType(str, Enum):
    D = "D"
    E = "E"
    N = "N"
    S = "S"
    AL = "연차"
    O = "O"


class NurseLevel(str, Enum):
    SENIOR_CHARGE = "senior_charge"
    MIDDLE = "middle"
    JUNIOR = "junior"
    NEW_JUNIOR = "new_junior"


WORKING_SHIFTS = (ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S)
OFF_SHIFTS = (ShiftType.O, ShiftType.AL)
ALL_SHIFTS = (ShiftType.D, ShiftType.E, ShiftType.N, ShiftType.S, ShiftType.O, ShiftType.AL)


@dataclass
class Nurse:
    name: str
    can_charge: bool = False
    is_junior: bool = False  # 저연차 여부 (S 근무 배정 자격 판단에 사용)
    level: Optional[NurseLevel] = None
    n_excluded: bool = False
    dedicated_shift: Optional[ShiftType] = None  # legacy: use allowed_shifts for new inputs
    allowed_shifts: Optional[set[ShiftType]] = None
    max_n_hard: int = 8
    n_soft_consecutive_limit: Optional[int] = 3
    excluded_shifts: set[ShiftType] = field(default_factory=set)
    weekday_only: bool = False
    al_target: Optional[int] = None

    def __post_init__(self):
        if self.level is None:
            if self.can_charge:
                self.level = NurseLevel.MIDDLE
            elif self.is_junior:
                self.level = NurseLevel.JUNIOR
        if self.level == NurseLevel.SENIOR_CHARGE:
            self.can_charge = True
            self.is_junior = False
        elif self.level == NurseLevel.MIDDLE:
            self.can_charge = True
            self.is_junior = False
        elif self.level in (NurseLevel.JUNIOR, NurseLevel.NEW_JUNIOR):
            self.can_charge = False
            self.is_junior = True
        if self.dedicated_shift not in (None, ShiftType.D, ShiftType.E, ShiftType.N):
            raise ValueError("dedicated_shift는 D, E, N, None 중 하나여야 합니다")
        if self.allowed_shifts is None:
            self.allowed_shifts = (
                {self.dedicated_shift}
                if self.dedicated_shift is not None
                else {ShiftType.D, ShiftType.E, ShiftType.N}
            )
        else:
            self.allowed_shifts = {ShiftType(s) for s in self.allowed_shifts}
        invalid = self.allowed_shifts - {ShiftType.D, ShiftType.E, ShiftType.N}
        if invalid:
            raise ValueError("allowed_shifts는 D, E, N만 허용합니다")
        if self.n_excluded or self.max_n_hard <= 0:
            self.max_n_hard = 0
            self.allowed_shifts.discard(ShiftType.N)
        if self.n_soft_consecutive_limit not in (None, 2, 3):
            raise ValueError("n_soft_consecutive_limit은 미입력, 2, 3 중 하나여야 합니다")

    @property
    def can_act(self) -> bool:
        return self.level in (NurseLevel.MIDDLE, NurseLevel.JUNIOR, NurseLevel.NEW_JUNIOR)

    @property
    def is_new_junior(self) -> bool:
        return self.level == NurseLevel.NEW_JUNIOR


@dataclass
class Assistant:
    """근무표 생성(솔버) 대상이 아닌 보조 인력 (간호조무사 등).

    결과 표와 HWP 양식 하단 행에 표시되며, 듀티 신청(희망/제외)은 표시 용도로만 쓰인다.
    """

    name: str
    role: str = "간호조무사"


@dataclass
class ShiftRequirement:
    """듀티별 하루 인원 요건: 하한~상한(하드 범위) + 목표(소프트).

    maximum 생략 시 minimum과 동일(= 정확히 그 인원, 예: N 매일 3명).
    target 생략 시 maximum과 동일(= 범위 상한을 목표로 지향).
    """

    minimum: int
    maximum: Optional[int] = None
    target: Optional[int] = None

    def __post_init__(self):
        if self.maximum is None:
            self.maximum = self.minimum
        if self.target is None:
            self.target = self.maximum
        if self.maximum < self.minimum:
            raise ValueError("maximum은 minimum 이상이어야 합니다")
        if not (self.minimum <= self.target <= self.maximum):
            raise ValueError("target은 minimum~maximum 범위 안이어야 합니다")


@dataclass
class DayRequirement:
    day: date
    D: ShiftRequirement
    E: ShiftRequirement
    N: ShiftRequirement


@dataclass
class ExceptionRequest:
    nurse_name: str
    day: date
    forced_shift: ShiftType  # 강제 배정 근무 (O/AL 지정 시 강제휴무)


@dataclass
class DutyRequest:
    nurse_name: str
    day: date
    requested_shift: ShiftType
    kind: str = "prefer"  # prefer: 해당 듀티 희망, avoid: 해당 듀티 제외
    decision: str = "force"  # force: 강제 반영, ignore: 이번 생성에서 미반영
    priority: int = 1
    memo: str = ""

    def __post_init__(self):
        if self.kind not in ("prefer", "avoid"):
            raise ValueError("kind must be 'prefer' or 'avoid'")
        if self.decision not in ("force", "ignore"):
            raise ValueError("decision must be 'force' or 'ignore'")
        if self.priority < 1:
            raise ValueError("priority must be at least 1")


@dataclass
class HistoryDay:
    day: date
    assignments: dict[str, ShiftType]  # nurse_name -> ShiftType


@dataclass
class ScheduleResult:
    feasible: bool
    assignments: dict[tuple[str, date], ShiftType] = field(default_factory=dict)
    infeasible_categories: list[str] = field(default_factory=list)
    soft_violations: dict[str, float] = field(default_factory=dict)
    dropped_duty_requests: list[DutyRequest] = field(default_factory=list)
    honored_duty_requests: list[DutyRequest] = field(default_factory=list)
    objective_value: Optional[float] = None


def month_dates(year: int, month: int) -> list[date]:
    n_days = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, n_days + 1)]


def build_month_requirements(
    year: int,
    month: int,
    weekday_template: tuple[ShiftRequirement, ShiftRequirement, ShiftRequirement],
    weekend_template: tuple[ShiftRequirement, ShiftRequirement, ShiftRequirement],
    date_overrides: Optional[dict[date, DayRequirement]] = None,
) -> dict[date, DayRequirement]:
    """평일/주말 기본 템플릿 + 날짜별 예외로 한 달치 DayRequirement 생성.

    weekday_template / weekend_template: (D, E, N) 순서의 ShiftRequirement 3종.
    월요일 우대는 목표치가 아니라 벌점 가중치로 처리한다 (core/constraints.py 참고).
    """
    date_overrides = date_overrides or {}
    result: dict[date, DayRequirement] = {}
    for d in month_dates(year, month):
        if d in date_overrides:
            result[d] = date_overrides[d]
            continue
        template = weekend_template if d.weekday() >= 5 else weekday_template
        result[d] = DayRequirement(
            day=d,
            D=ShiftRequirement(template[0].minimum, template[0].maximum, template[0].target),
            E=ShiftRequirement(template[1].minimum, template[1].maximum, template[1].target),
            N=ShiftRequirement(template[2].minimum, template[2].maximum, template[2].target),
        )
    return result


def compute_month_off_target(year: int, month: int, holiday_dates: set[date]) -> int:
    """목표 오프일수 = 그달 토요일수 + 일요일수 + 공휴일수 (중복도 각각 단순합산)."""
    weekend_count = sum(1 for d in month_dates(year, month) if d.weekday() >= 5)
    holiday_count = sum(1 for d in holiday_dates if d.year == year and d.month == month)
    return weekend_count + holiday_count


def lookback_dates(year: int, month: int, n: int = 5) -> list[date]:
    """이전 달 마지막 n일 날짜 목록 (오래된 날짜 순)."""
    first_day = date(year, month, 1)
    return [first_day - timedelta(days=n - i) for i in range(n)]
