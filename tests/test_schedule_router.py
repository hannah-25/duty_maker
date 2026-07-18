from datetime import date

import pytest

from api.deps import CurrentUser
from api.routers import schedule as schedule_router
from api.routers.schedule import (
    TRINITY_A_WARD_ID,
    _manual_assignments,
    _requests_for_month,
    _solver_settings,
    _validate_selected_cells,
)
from api.schemas import ManualAssignmentIn, ScheduleCellIn, ScheduleOut
from core.models import DutyRequest, Nurse, ScheduleResult, ShiftType


def test_requests_for_month_excludes_previous_month_and_unknown_nurses():
    requests = [
        DutyRequest("Kim", date(2026, 7, 31), ShiftType.O),
        DutyRequest("Kim", date(2026, 8, 1), ShiftType.D),
        DutyRequest("Unknown", date(2026, 8, 2), ShiftType.E),
    ]

    result = _requests_for_month({"duty_requests": requests}, {"Kim"}, 2026, 8)

    assert result == [requests[1]]


def test_manual_assignments_reads_only_current_month():
    state = {
        "manual_overrides": {
            "Kim|2026-07-01": "N",
            "Lee|2026-08-01": "D",
            "broken": "E",
        }
    }

    assert _manual_assignments(state, 2026, 7) == {("Kim", date(2026, 7, 1)): ShiftType.N}


def test_validate_selected_cells_rejects_helper_and_out_of_month_cells():
    state = {"nurses": [Nurse("Kim"), Nurse("Helper", is_helper=True)]}

    with pytest.raises(Exception):
        _validate_selected_cells(state, [ScheduleCellIn(nurse_name="Helper", date="2026-07-01")], 2026, 7)
    with pytest.raises(Exception):
        _validate_selected_cells(state, [ScheduleCellIn(nurse_name="Kim", date="2026-08-01")], 2026, 7)


def test_manual_assignment_pins_cell_and_increments_revision(monkeypatch):
    day = date(2026, 7, 1)
    state = {
        "year": 2026, "month": 7, "schedule_revision": 3, "manual_overrides": {},
        "schedule_previews": {"stale": {}}, "nurses": [Nurse("Kim")], "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=True, assignments={("Kim", day): ShiftType.D}),
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_staffing_violations", lambda *_: [])
    monkeypatch.setattr(
        schedule_router, "_schedule_out",
        lambda ss, user: ScheduleOut(year=2026, month=7, published=False, visible=True, revision=ss["schedule_revision"]),
    )

    result = schedule_router.update_assignment(
        ManualAssignmentIn(nurse_name="Kim", date="2026-07-01", shift="N", expected_revision=3),
        CurrentUser("ward", "admin", True),
    )

    assert state["schedule_result"].assignments[("Kim", day)] is ShiftType.N
    assert state["manual_overrides"] == {"Kim|2026-07-01": "N"}
    assert state["schedule_previews"] == {}
    assert result.revision == 4


def test_trinity_pair_preference_is_limited_to_trinity_a(monkeypatch):
    monkeypatch.setattr(schedule_router, "resolve_ward_settings", lambda _: {"weekday_charge_D": 2})

    trinity = _solver_settings({}, CurrentUser(TRINITY_A_WARD_ID, "admin", True))
    other = _solver_settings({}, CurrentUser("other-ward", "admin", True))

    assert trinity["trinity_a_pair_overlap"] is True
    assert "trinity_a_pair_overlap" not in other


def test_generate_enables_pair_preference_for_trinity_a(monkeypatch):
    state = {
        "year": 2026,
        "month": 8,
        "nurses": [Nurse("우창희"), Nurse("정해주")],
        "duty_requests": [],
        "manual_overrides": {},
    }
    captured = {}
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_requirements", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_off_target", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_infeasibility_messages", lambda *_: [])
    monkeypatch.setattr(schedule_router, "_schedule_out", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_solver_settings", lambda *_: {"trinity_a_pair_overlap": True})

    def fake_generate(*_args, **kwargs):
        captured.update(kwargs["settings"])
        return ScheduleResult(feasible=False)

    monkeypatch.setattr(schedule_router, "generate_schedule", fake_generate)

    schedule_router.generate(CurrentUser(TRINITY_A_WARD_ID, "admin", True))

    assert captured["trinity_a_pair_overlap"] is True
