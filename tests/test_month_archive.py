"""월별 근무표 보관: 연월을 오가도 각 달의 근무표가 유지되는지 검증한다."""

from datetime import date

import pytest

from api.deps import CurrentUser
from api.routers import requirements as requirements_router
from api.schemas import RequirementsIn, ShiftRequirementIn, StaffingTemplateIn
from api.state_store import (
    _mirror_active_month,
    load_ward_state,
    prev_month_confirmed,
    prev_month_history,
    save_ward_state,
)
from core import persistence
from core.models import Nurse, ScheduleResult, ShiftType


@pytest.fixture
def local_store(monkeypatch, tmp_path):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(persistence, "DATA_DIR", tmp_path)
    monkeypatch.setattr(persistence, "WARDS_REGISTRY_PATH", tmp_path / "wards_registry.json")
    return "ward-1"


def _template() -> StaffingTemplateIn:
    row = ShiftRequirementIn(minimum=1, maximum=3, target=2)
    return StaffingTemplateIn(D=row, E=row, N=row)


def _requirements_body(year: int, month: int) -> RequirementsIn:
    return RequirementsIn(
        year=year,
        month=month,
        weekday_template=_template(),
        weekend_template=_template(),
        selected_holidays=[],
        date_overrides=[],
    )


def test_active_slot_mirrors_current_month_archive(local_store):
    ward = local_store
    ss = load_ward_state(ward)
    ss["year"], ss["month"] = 2026, 7
    ss["nurses"] = [Nurse("Kim")]
    ss["prev_month_inputs"] = {"2026-07": {}}
    ss["schedule_result"] = ScheduleResult(
        feasible=True, assignments={("Kim", date(2026, 7, 1)): ShiftType.D}
    )
    save_ward_state(ward, ss)

    reloaded = load_ward_state(ward)
    assert "2026-07" in reloaded["schedules_by_month"]
    assert reloaded["schedule_result"].assignments[("Kim", date(2026, 7, 1))] is ShiftType.D


def test_schedule_survives_month_round_trip(local_store):
    ward = local_store
    admin = CurrentUser(ward, "admin", True)

    # 7월 근무표를 심어 둔다.
    ss = load_ward_state(ward)
    ss["year"], ss["month"] = 2026, 7
    ss["nurses"] = [Nurse("Kim")]
    ss["prev_month_inputs"] = {"2026-07": {}}
    ss["schedule_result"] = ScheduleResult(
        feasible=True, assignments={("Kim", date(2026, 7, 1)): ShiftType.D}
    )
    save_ward_state(ward, ss)

    # 8월로 이동(연월 적용) — 8월엔 아직 근무표 없음.
    requirements_router.put_requirements(_requirements_body(2026, 8), admin)
    mid = load_ward_state(ward)
    assert mid["month"] == 8
    assert mid["schedule_result"] is None  # 8월은 비어 있고
    assert "2026-07" in mid["schedules_by_month"]  # 7월은 보관돼 있어야 한다

    # 다시 7월로 이동 — 7월 근무표가 그대로 살아 있어야 한다.
    requirements_router.put_requirements(_requirements_body(2026, 7), admin)
    back = load_ward_state(ward)
    assert back["month"] == 7
    assert back["schedule_result"].assignments[("Kim", date(2026, 7, 1))] is ShiftType.D


def test_schedule_preserved_even_when_staffing_changes(local_store):
    ward = local_store
    admin = CurrentUser(ward, "admin", True)

    ss = load_ward_state(ward)
    ss["year"], ss["month"] = 2026, 7
    ss["nurses"] = [Nurse("Kim")]
    ss["prev_month_inputs"] = {"2026-07": {}}
    ss["schedule_result"] = ScheduleResult(
        feasible=True, assignments={("Kim", date(2026, 7, 1)): ShiftType.D}
    )
    save_ward_state(ward, ss)

    # 첫 저장은 현재 인원 기준을 baseline으로 채택할 뿐 삭제하지 않는다.
    requirements_router.put_requirements(_requirements_body(2026, 7), admin)
    assert load_ward_state(ward)["schedule_result"] is not None

    # 같은 인원 기준으로 다시 저장(변경 없음) → 표 유지.
    requirements_router.put_requirements(_requirements_body(2026, 7), admin)
    assert load_ward_state(ward)["schedule_result"] is not None

    # 인원 기준(D 템플릿)을 실제로 바꿔 저장해도 표는 보존된다.
    # 근무표는 관리자가 근무표 생성을 다시 눌렀을 때만 교체된다.
    changed = _requirements_body(2026, 7)
    changed.weekday_template.D = ShiftRequirementIn(minimum=2, maximum=4, target=3)
    requirements_router.put_requirements(changed, admin)
    after = load_ward_state(ward)
    assert after["schedule_result"] is not None
    assert after["schedule_result"].assignments[("Kim", date(2026, 7, 1))] is ShiftType.D


def test_prev_month_autofill_on_advance(local_store):
    ward = local_store
    admin = CurrentUser(ward, "admin", True)

    ss = load_ward_state(ward)
    ss["year"], ss["month"] = 2026, 7
    ss["nurses"] = [Nurse("Kim")]
    ss["prev_month_inputs"] = {"2026-07": {}}
    # 7월 말일 N — 8월 lookback(7/27~7/31)에 포함.
    ss["schedule_result"] = ScheduleResult(
        feasible=True, assignments={("Kim", date(2026, 7, 31)): ShiftType.N}
    )
    save_ward_state(ward, ss)

    requirements_router.put_requirements(_requirements_body(2026, 8), admin)
    ss = load_ward_state(ward)

    assert prev_month_confirmed(ss, 2026, 8)  # 자동 채움으로 확정됨
    assert prev_month_history(ss, 2026, 8) == {("Kim", date(2026, 7, 31)): ShiftType.N}
