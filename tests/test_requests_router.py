from datetime import date

from api.routers.requests import _apply_request_cells, _replace_opposite_kind, _requests_for_target_month
from core.models import DutyRequest, ShiftType


def _request(name: str, day: date, kind: str, shift: ShiftType) -> DutyRequest:
    return DutyRequest(
        nurse_name=name,
        day=day,
        requested_shift=shift,
        kind=kind,
        decision="force",
        memo="",
    )


def test_replace_opposite_kind_removes_only_conflicting_date_and_nurse():
    target_day = date(2026, 7, 10)
    requests = [
        _request("Kim", target_day, "prefer", ShiftType.D),
        _request("Kim", target_day, "avoid", ShiftType.N),
        _request("Lee", target_day, "avoid", ShiftType.E),
        _request("Kim", date(2026, 7, 11), "avoid", ShiftType.O),
    ]

    result = _replace_opposite_kind(requests, "Kim", target_day, "avoid")

    assert [(req.nurse_name, req.day, req.kind) for req in result] == [
        ("Kim", target_day, "avoid"),
        ("Lee", target_day, "avoid"),
        ("Kim", date(2026, 7, 11), "avoid"),
    ]


def test_replace_opposite_kind_keeps_multiple_requests_of_same_kind():
    target_day = date(2026, 7, 10)
    requests = [
        _request("Kim", target_day, "prefer", ShiftType.D),
        _request("Kim", target_day, "prefer", ShiftType.E),
    ]

    assert _replace_opposite_kind(requests, "Kim", target_day, "prefer") == requests


def test_requests_for_target_month_excludes_requests_from_previous_month():
    july = _request("Kim", date(2026, 7, 31), "prefer", ShiftType.D)
    august = _request("Kim", date(2026, 8, 1), "avoid", ShiftType.N)
    state = {"year": 2026, "month": 8, "duty_requests": [july, august]}

    assert _requests_for_target_month(state) == [august]


def test_requests_for_target_month_hides_legacy_s_request():
    day = date(2026, 8, 1)
    state = {
        "year": 2026,
        "month": 8,
        "duty_requests": [
            _request("Kim", day, "prefer", ShiftType.S),
            _request("Kim", day, "prefer", ShiftType.D),
        ],
    }

    assert _requests_for_target_month(state) == [state["duty_requests"][1]]


def test_apply_request_cells_replaces_only_its_bucket_and_opposite_kind():
    target_day = date(2026, 7, 10)
    requests = [
        _request("Kim", target_day, "prefer", ShiftType.D),
        _request("Kim", target_day, "avoid", ShiftType.N),
        DutyRequest("Kim", target_day, ShiftType.E, kind="prefer", decision="force", memo="교육"),
        _request("Lee", target_day, "avoid", ShiftType.N),
    ]

    result = _apply_request_cells(
        requests, [("Kim", target_day)], ShiftType.N, "prefer", ""
    )

    assert [(req.nurse_name, req.kind, req.requested_shift, req.memo) for req in result] == [
        ("Kim", "prefer", ShiftType.E, "교육"),
        ("Lee", "avoid", ShiftType.N, ""),
        ("Kim", "prefer", ShiftType.N, ""),
    ]
