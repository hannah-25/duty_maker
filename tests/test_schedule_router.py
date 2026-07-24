from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.deps import CurrentUser
from api.routers import schedule as schedule_router
from api.routers import settings as settings_router
from api.routers.schedule import (
    TRINITY_A_WARD_ID,
    _manual_assignments,
    _requests_for_month,
    _solver_settings,
    _validate_selected_cells,
)
from api.schemas import ClearOverridesIn, ScheduleCellEditIn, ScheduleCellIn, ScheduleEditBatchIn, ScheduleOut, WardSettings
from core.models import DutyRequest, Nurse, ScheduleResult, ShiftRequirement, ShiftType
from core.constraints import merge_ward_settings


def test_disabling_s_invalidates_schedule_previews(monkeypatch):
    state = {
        "constraint_settings": {},
        "schedule_revision": 7,
        "schedule_previews": {"stale": {}},
    }
    monkeypatch.setattr(settings_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(settings_router, "save_ward_state", lambda *_: None)

    result = settings_router.put_settings(
        WardSettings(use_s_shift=False), CurrentUser("ward", "admin", True)
    )

    assert result.use_s_shift is False
    assert state["constraint_settings"]["use_s_shift"] is False
    assert state["schedule_revision"] == 8
    assert state["schedule_previews"] == {}


def test_requests_for_month_excludes_previous_month_and_unknown_nurses():
    requests = [
        DutyRequest("Kim", date(2026, 7, 31), ShiftType.O),
        DutyRequest("Kim", date(2026, 8, 1), ShiftType.D),
        DutyRequest("Unknown", date(2026, 8, 2), ShiftType.E),
    ]

    result = _requests_for_month({"duty_requests": requests}, {"Kim"}, 2026, 8)

    assert result == [requests[1]]


def test_requests_for_month_excludes_legacy_s_request():
    requests = [
        DutyRequest("Kim", date(2026, 8, 1), ShiftType.S),
        DutyRequest("Kim", date(2026, 8, 1), ShiftType.D),
    ]

    assert _requests_for_month({"duty_requests": requests}, {"Kim"}, 2026, 8) == [requests[1]]


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
    monkeypatch.setattr(schedule_router, "_off_target", lambda *_: {"Kim": 0})
    monkeypatch.setattr(schedule_router, "_staffing_violations", lambda *_: [], raising=False)
    monkeypatch.setattr(
        schedule_router, "_schedule_out",
        lambda ss, user: ScheduleOut(year=2026, month=7, published=False, visible=True, revision=ss["schedule_revision"]),
    )

    result = schedule_router.update_assignments(
        ScheduleEditBatchIn(
            expected_revision=3,
            edits=[ScheduleCellEditIn(nurse_name="Kim", date="2026-07-01", shift="N", pinned=True)],
        ),
        CurrentUser("ward", "admin", True),
    )

    assert state["schedule_result"].assignments[("Kim", day)] is ShiftType.N
    assert state["manual_overrides"] == {"Kim|2026-07-01": "N"}
    assert state["schedule_previews"] == {}
    assert result.revision == 4


def test_manual_assignment_without_pin_does_not_add_override(monkeypatch):
    day = date(2026, 7, 1)
    state = {
        "year": 2026, "month": 7, "schedule_revision": 3, "manual_overrides": {},
        "schedule_previews": {}, "nurses": [Nurse("Kim")], "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=True, assignments={("Kim", day): ShiftType.D}),
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_off_target", lambda *_: {"Kim": 0})
    monkeypatch.setattr(
        schedule_router, "_schedule_out",
        lambda ss, user: ScheduleOut(year=2026, month=7, published=False, visible=True, revision=ss["schedule_revision"]),
    )

    schedule_router.update_assignments(
        ScheduleEditBatchIn(
            expected_revision=3,
            edits=[ScheduleCellEditIn(nurse_name="Kim", date="2026-07-01", shift="N", pinned=False)],
        ),
        CurrentUser("ward", "admin", True),
    )

    # 값은 바뀌지만 고정(우클릭)하지 않았으므로 manual_overrides엔 들어가지 않는다.
    assert state["schedule_result"].assignments[("Kim", day)] is ShiftType.N
    assert state["manual_overrides"] == {}


def test_manual_assignment_unpin_removes_override_keeps_value(monkeypatch):
    day = date(2026, 7, 1)
    state = {
        "year": 2026, "month": 7, "schedule_revision": 3,
        "manual_overrides": {"Kim|2026-07-01": "N"},
        "schedule_previews": {}, "nurses": [Nurse("Kim")], "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=True, assignments={("Kim", day): ShiftType.N}),
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_off_target", lambda *_: {"Kim": 0})
    monkeypatch.setattr(
        schedule_router, "_schedule_out",
        lambda ss, user: ScheduleOut(year=2026, month=7, published=False, visible=True, revision=ss["schedule_revision"]),
    )

    schedule_router.update_assignments(
        ScheduleEditBatchIn(
            expected_revision=3,
            edits=[ScheduleCellEditIn(nurse_name="Kim", date="2026-07-01", shift="N", pinned=False)],
        ),
        CurrentUser("ward", "admin", True),
    )

    assert state["schedule_result"].assignments[("Kim", day)] is ShiftType.N
    assert state["manual_overrides"] == {}


def test_manual_assignment_converts_excess_off_to_annual_leave(monkeypatch):
    days = [date(2026, 7, d) for d in range(1, 32)]
    # 7월 목표 오프(주말)는 8일. 이미 8일을 오프로 채워둔 상태에서 9번째 오프를
    # 추가로 지정하면 초과분만 오프가 아니라 연차로 저장돼야 한다.
    assignments = {("Kim", d): ShiftType.D for d in days}
    for d in days[:8]:
        assignments[("Kim", d)] = ShiftType.O
    new_off_day = days[8]
    state = {
        "year": 2026, "month": 7, "schedule_revision": 1, "manual_overrides": {},
        "schedule_previews": {}, "nurses": [Nurse("Kim")], "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=True, assignments=assignments),
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(
        schedule_router, "_schedule_out",
        lambda ss, user: ScheduleOut(year=2026, month=7, published=False, visible=True, revision=ss["schedule_revision"]),
    )

    schedule_router.update_assignments(
        ScheduleEditBatchIn(
            expected_revision=1,
            edits=[ScheduleCellEditIn(nurse_name="Kim", date=new_off_day.isoformat(), shift="O", pinned=True)],
        ),
        CurrentUser("ward", "admin", True),
    )

    assert state["schedule_result"].assignments[("Kim", new_off_day)] == ShiftType.AL
    assert state["manual_overrides"][f"Kim|{new_off_day.isoformat()}"] == "연차"


def test_manual_assignment_allows_off_swap_in_one_batch(monkeypatch):
    days = [date(2026, 7, d) for d in range(1, 32)]
    assignments = {("Kim", d): ShiftType.D for d in days}
    for d in days[:8]:
        assignments[("Kim", d)] = ShiftType.O
    old_off_day, new_off_day = days[0], days[8]
    state = {
        "year": 2026, "month": 7, "schedule_revision": 1, "manual_overrides": {},
        "schedule_previews": {}, "nurses": [Nurse("Kim")], "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=True, assignments=assignments),
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(
        schedule_router, "_schedule_out",
        lambda ss, user: ScheduleOut(year=2026, month=7, published=False, visible=True, revision=ss["schedule_revision"]),
    )

    schedule_router.update_assignments(
        ScheduleEditBatchIn(
            expected_revision=1,
            edits=[
                ScheduleCellEditIn(nurse_name="Kim", date=old_off_day.isoformat(), shift="D", pinned=True),
                ScheduleCellEditIn(nurse_name="Kim", date=new_off_day.isoformat(), shift="O", pinned=True),
            ],
        ),
        CurrentUser("ward", "admin", True),
    )

    assert state["schedule_result"].assignments[("Kim", old_off_day)] is ShiftType.D
    assert state["schedule_result"].assignments[("Kim", new_off_day)] is ShiftType.O
    assert sum(shift is ShiftType.O for shift in state["schedule_result"].assignments.values()) == 8


def test_manual_assignment_rejects_off_shortfall(monkeypatch):
    days = [date(2026, 7, d) for d in range(1, 32)]
    assignments = {("Kim", d): ShiftType.D for d in days}
    for d in days[:8]:
        assignments[("Kim", d)] = ShiftType.O
    state = {
        "year": 2026, "month": 7, "schedule_revision": 1, "manual_overrides": {},
        "schedule_previews": {}, "nurses": [Nurse("Kim")], "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=True, assignments=assignments),
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)

    with pytest.raises(HTTPException, match="오프는 개인별 목표보다 적을 수 없습니다"):
        schedule_router.update_assignments(
            ScheduleEditBatchIn(
                expected_revision=1,
                edits=[ScheduleCellEditIn(nurse_name="Kim", date=days[0].isoformat(), shift="D", pinned=True)],
            ),
            CurrentUser("ward", "admin", True),
        )

    assert state["schedule_result"].assignments[("Kim", days[0])] is ShiftType.O
    assert state["manual_overrides"] == {}


def test_clear_manual_overrides_works_when_infeasible(monkeypatch):
    """생성 실패(infeasible) 상태에서도 고정을 풀 수 있어야 교착에서 탈출한다."""
    state = {
        "year": 2026, "month": 7, "schedule_revision": 5,
        "manual_overrides": {"Kim|2026-07-01": "연차", "Lee|2026-07-02": "N"},
        "schedule_previews": {"stale": {}}, "nurses": [Nurse("Kim"), Nurse("Lee")],
        "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=False, infeasible_categories=["fixed_assignments"]),
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(
        schedule_router, "_schedule_out",
        lambda ss, user: ScheduleOut(year=2026, month=7, published=False, visible=True, revision=ss["schedule_revision"]),
    )

    # 실행 가능한 근무표가 없어도(=update_assignments는 400) 이 경로는 동작해야 한다.
    result = schedule_router.clear_manual_overrides(
        ClearOverridesIn(expected_revision=5, cells=["Kim|2026-07-01"]),
        CurrentUser("ward", "admin", True),
    )

    assert state["manual_overrides"] == {"Lee|2026-07-02": "N"}
    assert state["schedule_result"].feasible is False  # 결과는 그대로 둔다
    assert state["schedule_previews"] == {}
    assert result.revision == 6


def test_clear_manual_overrides_empty_cells_clears_all(monkeypatch):
    state = {
        "year": 2026, "month": 7, "schedule_revision": 1,
        "manual_overrides": {"Kim|2026-07-01": "연차", "Lee|2026-07-02": "N"},
        "schedule_previews": {}, "nurses": [], "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=False),
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(
        schedule_router, "_schedule_out",
        lambda ss, user: ScheduleOut(year=2026, month=7, published=False, visible=True, revision=ss["schedule_revision"]),
    )

    schedule_router.clear_manual_overrides(
        ClearOverridesIn(expected_revision=1, cells=[]),
        CurrentUser("ward", "admin", True),
    )

    assert state["manual_overrides"] == {}


def test_clear_manual_overrides_rejects_stale_revision(monkeypatch):
    state = {
        "year": 2026, "month": 7, "schedule_revision": 4,
        "manual_overrides": {"Kim|2026-07-01": "연차"},
        "schedule_previews": {}, "nurses": [], "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=False),
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)

    with pytest.raises(HTTPException, match="근무표가 변경되었습니다"):
        schedule_router.clear_manual_overrides(
            ClearOverridesIn(expected_revision=3, cells=["Kim|2026-07-01"]),
            CurrentUser("ward", "admin", True),
        )

    assert state["manual_overrides"] == {"Kim|2026-07-01": "연차"}


def test_draft_validation_does_not_persist_edits(monkeypatch):
    day = date(2026, 7, 1)
    state = {
        "year": 2026, "month": 7, "schedule_revision": 3, "manual_overrides": {},
        "schedule_previews": {}, "nurses": [Nurse("Kim")], "duty_requests": [],
        "schedule_result": ScheduleResult(feasible=True, assignments={("Kim", day): ShiftType.D}),
    }
    captured = {}
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "_off_target", lambda *_: {"Kim": 0})
    monkeypatch.setattr(schedule_router, "_requirements", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_solver_settings", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_checklist_out", lambda *_: [])
    monkeypatch.setattr(
        schedule_router,
        "validate_schedule",
        lambda _nurses, _year, _month, assignments, *_, **__: captured.update(assignments=dict(assignments)) or SimpleNamespace(ok=True, violations=[]),
    )

    response = schedule_router.validate_draft(
        ScheduleEditBatchIn(
            expected_revision=3,
            edits=[ScheduleCellEditIn(nurse_name="Kim", date=day.isoformat(), shift="N", pinned=False)],
        ),
        CurrentUser("ward", "admin", True),
    )

    assert captured["assignments"][("Kim", day)] is ShiftType.N
    assert state["schedule_result"].assignments[("Kim", day)] is ShiftType.D
    assert state["manual_overrides"] == {}
    assert response.validation_ok is True


def test_trinity_pair_preference_is_limited_to_trinity_a(monkeypatch):
    monkeypatch.setattr(schedule_router, "resolve_ward_settings", lambda _: {"weekday_charge_D": 2})

    trinity = _solver_settings({}, CurrentUser(TRINITY_A_WARD_ID, "admin", True))
    other = _solver_settings({}, CurrentUser("other-ward", "admin", True))

    assert trinity["trinity_a_pair_overlap"] is True
    assert "trinity_a_pair_overlap" not in other


def test_solver_settings_preserves_trinity_pair_flag():
    settings = merge_ward_settings({"weekday_charge_D": 3, "trinity_a_pair_overlap": True})

    assert settings["weekday_charge_D"] == 3
    assert settings["trinity_a_pair_overlap"] is True


def test_generate_enables_pair_preference_for_trinity_a(monkeypatch):
    state = {
        "year": 2026,
        "month": 8,
        "nurses": [Nurse("우창희"), Nurse("정해주")],
        "duty_requests": [],
        "manual_overrides": {},
        "prev_month_inputs": {"2026-08": {}},
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


def test_generate_allows_missing_prev_month_input(monkeypatch):
    state = {
        "year": 2026,
        "month": 8,
        "nurses": [Nurse("Kim")],
        "duty_requests": [],
        "manual_overrides": {},
        "prev_month_inputs": {},
    }
    captured = {}
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_requirements", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_off_target", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_infeasibility_messages", lambda *_: [])
    monkeypatch.setattr(schedule_router, "_schedule_out", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_solver_settings", lambda *_: {})

    def fake_generate(*_args, **kwargs):
        captured["history"] = kwargs["history"]
        return ScheduleResult(feasible=False)

    monkeypatch.setattr(schedule_router, "generate_schedule", fake_generate)
    schedule_router.generate(CurrentUser("ward", "admin", True))

    assert captured["history"] == {}


def test_generate_with_relaxations_passes_each_scoped_selection(monkeypatch):
    state = {
        "year": 2026, "month": 8, "schedule_revision": 0,
        "nurses": [Nurse("A"), Nurse("B")], "duty_requests": [],
        "manual_overrides": {}, "prev_month_inputs": {},
    }
    captured = {}
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_requirements", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_off_target", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_infeasibility_messages", lambda *_: [])
    monkeypatch.setattr(schedule_router, "_schedule_out", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_solver_settings", lambda *_: {})

    def fake_generate(*_args, **kwargs):
        captured.update(kwargs)
        return ScheduleResult(feasible=False)

    monkeypatch.setattr(schedule_router, "generate_schedule", fake_generate)
    body = schedule_router.GenerateRelaxationsIn(
        relax_off_cap_for=["A", "B"],
        relax_n_then_1off_for=["A"],
        relax_nod_for=["B"],
        relax_four_consecutive_n_for=["A"],
        relax_weekday_weekend_for=["B"],
    )
    schedule_router.generate_with_relaxations(body, CurrentUser("ward", "admin", True))

    assert captured["relaxed_off_cap_nurses"] == frozenset({"A", "B"})
    assert captured["relaxed_n_then_1off_nurses"] == frozenset({"A"})
    assert captured["relaxed_nod_nurses"] == frozenset({"B"})
    assert captured["relaxed_four_consecutive_n_nurses"] == frozenset({"A"})
    assert captured["relaxed_weekday_weekend_nurses"] == frozenset({"B"})


def test_generate_passes_prev_month_history_to_solver(monkeypatch):
    state = {
        "year": 2026,
        "month": 8,
        "nurses": [Nurse("우창희")],
        "duty_requests": [],
        "manual_overrides": {},
        # 7월 마지막 날 N — 8월 lookback에 포함되는 날짜.
        "prev_month_inputs": {"2026-08": {"우창희": {"2026-07-31": "N"}}},
    }
    captured = {}
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_requirements", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_off_target", lambda *_: {})
    monkeypatch.setattr(schedule_router, "_infeasibility_messages", lambda *_: [])
    monkeypatch.setattr(schedule_router, "_schedule_out", lambda *_: None)
    monkeypatch.setattr(schedule_router, "_solver_settings", lambda *_: {})

    def fake_generate(*_args, **kwargs):
        captured["history"] = kwargs["history"]
        return ScheduleResult(feasible=False)

    monkeypatch.setattr(schedule_router, "generate_schedule", fake_generate)

    schedule_router.generate(CurrentUser("ward", "admin", True))

    assert captured["history"] == {("우창희", date(2026, 7, 31)): ShiftType.N}


def test_generate_reports_conflicting_forced_duty_request(monkeypatch):
    """강제 반영 듀티 신청이 다른 하드 규칙과 충돌하면, 원본 진단 코드와 해당 신청이 함께 나와야 한다."""
    year, month = 2026, 8
    day = date(year, month, 3)
    days_in_month = 31
    zero_template = (ShiftRequirement(0, 0, 0), ShiftRequirement(0, 0, 0), ShiftRequirement(0, 0, 0))
    state = {
        "year": year, "month": month, "schedule_revision": 0,
        "manual_overrides": {}, "schedule_previews": {},
        "nurses": [Nurse("Kim", can_charge=True)],
        # 그 날만 하드 D 요건(1명)과 정면 충돌하는 강제 오프 신청 — 나머지 날은 전부 무근무.
        "duty_requests": [DutyRequest("Kim", day, ShiftType.O, decision="force")],
        "weekday_template": zero_template, "weekend_template": zero_template,
        "date_override_rows": [{"date": day.isoformat(), "D": 1, "E": 0, "N": 0}],
        "selected_holidays": set(),
        "constraint_settings": {
            "weekday_charge_D": 0, "weekday_charge_E": 0, "weekday_charge_N": 0,
            "weekend_charge_D": 0, "weekend_charge_E": 0, "weekend_charge_N": 0,
        },
    }
    monkeypatch.setattr(schedule_router, "load_ward_state", lambda _: state)
    monkeypatch.setattr(schedule_router, "save_ward_state", lambda *_: None)
    # 그 하루만 일하고 나머지는 전부 오프 — off_cap·연속근무 등 다른 하드 규칙과는
    # 애초에 충돌하지 않도록, 실제로 그렇게 됐을 때의 목표치를 그대로 준다.
    monkeypatch.setattr(schedule_router, "_off_target", lambda *_a: {"Kim": days_in_month - 1})

    out = schedule_router.generate(CurrentUser("ward", "admin", True))

    assert out.feasible is False
    conflicting = [c for c in out.infeasible_raw_categories if c.startswith("duty_request:")]
    assert conflicting, out.infeasible_raw_categories
    assert any(
        req.nurse_name == "Kim" and req.date == day.isoformat() and req.requested_shift == "O"
        for req in out.infeasible_duty_requests
    ), out.infeasible_duty_requests
