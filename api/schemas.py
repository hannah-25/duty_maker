"""Pydantic schemas for FastAPI request/response validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WardCreate(BaseModel):
    hospital_name: str = Field(min_length=1)
    ward_name: str = Field(min_length=1)
    admin_name: str = Field(min_length=1)
    admin_pin: str
    registration_code: str


class WardOut(BaseModel):
    ward_id: str
    hospital_name: str
    ward_name: str


class TokenOut(BaseModel):
    token: str
    name: str
    is_admin: bool


class WardRegisterOut(TokenOut):
    ward_id: str


class LoginRequest(BaseModel):
    ward_id: str
    name: str = Field(min_length=1)
    pin: str


class RegisterRequest(BaseModel):
    ward_id: str
    name: str = Field(min_length=1)
    pin: str


class LookupRequest(BaseModel):
    ward_id: str
    name: str = Field(min_length=1)


class LookupOut(BaseModel):
    registered: bool
    in_roster: bool


class ChangePinRequest(BaseModel):
    current_pin: str
    new_pin: str


class NurseIn(BaseModel):
    name: str = Field(min_length=1)
    level: str = "junior"
    allowed_shifts: list[str] = Field(default_factory=lambda: ["D", "E", "N"])
    max_n_hard: int | None = 8
    n_soft_consecutive_limit: int | None = None
    al_target: int | None = None
    weekday_only: bool = False
    is_helper: bool = False
    # 헬퍼 모드 A: {"2026-07-05": "D", ...} — 날짜별 지정 듀티
    helper_shifts: dict[str, str] = Field(default_factory=dict)
    # 헬퍼 모드 B: 월 총 근무일수 (모드 A면 None)
    helper_workdays: int | None = None


class NurseOut(NurseIn):
    pass


class AssistantIn(BaseModel):
    name: str = Field(min_length=1)
    role: str = "간호조무사"


class AssistantOut(AssistantIn):
    pass


class RosterIn(BaseModel):
    nurses: list[NurseIn] = Field(default_factory=list)
    assistants: list[AssistantIn] = Field(default_factory=list)


class RosterOut(BaseModel):
    nurses: list[NurseOut]
    assistants: list[AssistantOut]


class ShiftRequirementIn(BaseModel):
    minimum: int = Field(ge=0)
    maximum: int | None = Field(default=None, ge=0)
    target: int | None = Field(default=None, ge=0)


class ShiftRequirementOut(ShiftRequirementIn):
    maximum: int
    target: int


class StaffingTemplateIn(BaseModel):
    D: ShiftRequirementIn
    E: ShiftRequirementIn
    N: ShiftRequirementIn


class StaffingTemplateOut(BaseModel):
    D: ShiftRequirementOut
    E: ShiftRequirementOut
    N: ShiftRequirementOut


class HolidayOut(BaseModel):
    date: str
    title: str
    selected: bool


class DateOverrideIn(BaseModel):
    date: str
    D: int = Field(ge=0)
    E: int = Field(ge=0)
    N: int = Field(ge=0)


class DateOverrideOut(DateOverrideIn):
    pass


class RequirementsIn(BaseModel):
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)
    weekday_template: StaffingTemplateIn
    weekend_template: StaffingTemplateIn
    selected_holidays: list[str] = Field(default_factory=list)
    date_overrides: list[DateOverrideIn] = Field(default_factory=list)


class RequirementsOut(BaseModel):
    year: int
    month: int
    weekday_template: StaffingTemplateOut
    weekend_template: StaffingTemplateOut
    holidays: list[HolidayOut]
    selected_holidays: list[str]
    date_overrides: list[DateOverrideOut]


class DutyRequestCreate(BaseModel):
    nurse_name: str | None = None
    date: str
    requested_shift: str
    kind: str = "prefer"
    memo: str = ""


class DutyRequestUpdate(BaseModel):
    decision: str


class DutyRequestOut(BaseModel):
    id: str
    nurse_name: str
    date: str
    requested_shift: str
    kind: str
    decision: str
    memo: str = ""


class DutyRequestsOut(BaseModel):
    year: int
    month: int
    locked: bool
    names: list[str]
    requests: list[DutyRequestOut]
    is_admin: bool


class RequestLockIn(BaseModel):
    locked: bool


class PrevMonthIn(BaseModel):
    # 간호사명 -> {날짜(ISO): 근무값}. 빈 값/누락 셀은 오프로 간주한다.
    values: dict[str, dict[str, str]] = Field(default_factory=dict)


class PrevMonthOut(BaseModel):
    year: int
    month: int
    dates: list[str]
    nurse_names: list[str]
    values: dict[str, dict[str, str]]
    confirmed: bool


class ScheduleAssignmentOut(BaseModel):
    nurse_name: str
    date: str
    shift: str


class ScheduleCellIn(BaseModel):
    nurse_name: str = Field(min_length=1)
    date: str


class RegeneratePreviewIn(BaseModel):
    expected_revision: int = Field(ge=0)
    cells: list[ScheduleCellIn] = Field(min_length=1)


class RegenerateApplyIn(BaseModel):
    preview_id: str = Field(min_length=1)


class ManualAssignmentIn(BaseModel):
    nurse_name: str = Field(min_length=1)
    date: str
    shift: str | None = None
    expected_revision: int = Field(ge=0)


class ScheduleRequestOut(BaseModel):
    nurse_name: str
    date: str
    requested_shift: str
    kind: str


class NurseStatsOut(BaseModel):
    """검증 리포트의 개인별 통계 (근무표 오른쪽 요약 열)."""

    worked: int
    n_count: int
    off_count: int
    annual_leave: int
    annual_leave_target: str
    off_delta: int


class ChecklistItemOut(BaseModel):
    """입력한 제약 하나가 결과에 반영됐는지 여부."""

    item: str
    subject: str
    expected: str
    actual: str
    ok: bool


class AssistantRowOut(BaseModel):
    """보조 인력 행: 날짜(ISO) -> 표에 찍을 근무 코드."""

    name: str
    marks: dict[str, str] = Field(default_factory=dict)


class ScheduleOut(BaseModel):
    year: int
    month: int
    published: bool
    visible: bool
    revision: int = 0
    feasible: bool | None = None
    objective_value: float | None = None
    infeasible_categories: list[str] = Field(default_factory=list)
    assignments: list[ScheduleAssignmentOut] = Field(default_factory=list)
    nurse_names: list[str] = Field(default_factory=list)
    honored_requests: list[ScheduleRequestOut] = Field(default_factory=list)
    dropped_requests: list[ScheduleRequestOut] = Field(default_factory=list)
    validation_ok: bool | None = None
    violations: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    holidays: list[str] = Field(default_factory=list)
    stats: dict[str, NurseStatsOut] = Field(default_factory=dict)
    assistant_rows: list[AssistantRowOut] = Field(default_factory=list)
    charge_cells: list[str] = Field(default_factory=list)  # 차지 배정 셀 "이름|날짜"
    helper_names: list[str] = Field(default_factory=list)  # 외부 헬퍼 이름
    # 아래 항목은 관리자에게만 채워진다.
    checklist: list[ChecklistItemOut] = Field(default_factory=list)
    total_requests: int = 0
    honored_count: int = 0
    unreflected_count: int = 0
    dropped_off_count: int = 0
    manual_override_cells: list[str] = Field(default_factory=list)


class WardSettings(BaseModel):
    weekday_charge_D: int = Field(default=2, ge=0, le=5)
    weekday_charge_E: int = Field(default=1, ge=0, le=5)
    weekday_charge_N: int = Field(default=1, ge=0, le=5)
    weekend_charge_D: int = Field(default=1, ge=0, le=5)
    weekend_charge_E: int = Field(default=1, ge=0, le=5)
    weekend_charge_N: int = Field(default=1, ge=0, le=5)


class ExportSettings(BaseModel):
    """??? ???? ?? ??."""

    title_mode: str = Field(default="ward_month_off", pattern="^(ward_month_off|hospital_ward_month_off|custom)$")
    custom_title: str = Field(default="", max_length=100)
    holiday_color: str = Field(default="#FFE7D8", pattern=r"^#[0-9A-Fa-f]{6}$")
    honored_off_color: str = Field(default="#2563EB", pattern=r"^#[0-9A-Fa-f]{6}$")
    summary_fields: list[str] = Field(default_factory=lambda: ["E", "N", "O"])


class PublishIn(BaseModel):
    published: bool


class AccountOut(BaseModel):
    name: str
    is_admin: bool
    in_roster: bool
    is_current: bool


class AccountsOut(BaseModel):
    accounts: list[AccountOut]
    unregistered_names: list[str] = Field(default_factory=list)


class AccountUpdate(BaseModel):
    is_admin: bool
