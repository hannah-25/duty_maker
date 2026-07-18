from io import BytesIO

import openpyxl
import pytest
from fastapi.testclient import TestClient

import api.main as main_module
import api.routers.exports as exports_module
from api.deps import CurrentUser, get_current_user
from core.models import Nurse, ScheduleResult, ShiftType, month_dates
from core.persistence import (
    _from_firestore_payload,
    _to_firestore_payload,
    serialize_state,
    storage_backend,
)


def test_storage_backend_defaults_to_local(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    assert storage_backend() == "local"


def test_storage_backend_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "unknown")
    with pytest.raises(RuntimeError, match="STORAGE_BACKEND"):
        storage_backend()


def test_health_and_local_readiness(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    with TestClient(main_module.app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "storage": "local"}


def test_readiness_failure_returns_503(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "validate_storage_backend",
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    # Calling without a context manager skips lifespan; this isolates endpoint behavior.
    client = TestClient(main_module.app, raise_server_exceptions=False)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Storage backend is not ready"}


def _has_nested_array(value) -> bool:
    """Firestore rejects an array whose elements are themselves arrays."""
    if isinstance(value, list):
        if any(isinstance(item, list) for item in value):
            return True
        return any(_has_nested_array(item) for item in value)
    if isinstance(value, dict):
        return any(_has_nested_array(item) for item in value.values())
    return False


def test_firestore_payload_roundtrips_schedule_previews():
    year, month = 2026, 7
    nurse = Nurse("preview-nurse")
    result = ScheduleResult(
        feasible=True,
        assignments={(nurse.name, day): ShiftType.O for day in month_dates(year, month)},
    )
    state = {
        "year": year,
        "month": month,
        "nurses": [nurse],
        "schedule_result": result,
        "schedule_previews": {
            "abc123": {
                "base_revision": 3,
                "selected_keys": [f"{nurse.name}|{month_dates(year, month)[0].isoformat()}"],
                "result": result,
            }
        },
    }
    payload = serialize_state(state)

    firestore_form = _to_firestore_payload(payload)
    # The reason schedule_previews needed conversion at all: Firestore rejects nested arrays.
    assert not _has_nested_array(firestore_form["schedule_previews"])

    restored = _from_firestore_payload(firestore_form)
    assert restored["schedule_previews"]["abc123"]["result"]["assignments"] == (
        payload["schedule_previews"]["abc123"]["result"]["assignments"]
    )
    assert restored["schedule_previews"]["abc123"]["base_revision"] == 3


def test_firestore_payload_roundtrips_schedules_by_month():
    year, month = 2026, 7
    nurse = Nurse("archive-nurse")
    result = ScheduleResult(
        feasible=True,
        assignments={(nurse.name, day): ShiftType.O for day in month_dates(year, month)},
    )
    state = {
        "year": year,
        "month": month,
        "nurses": [nurse],
        "schedules_by_month": {"2026-06": result, "2026-07": result},
        "published_by_month": {"2026-07": True},
        "prev_month_inputs": {"2026-07": {nurse.name: {"2026-06-30": "N"}}},
    }
    payload = serialize_state(state)

    firestore_form = _to_firestore_payload(payload)
    assert not _has_nested_array(firestore_form["schedules_by_month"])
    assert not _has_nested_array(firestore_form["prev_month_inputs"])

    restored = _from_firestore_payload(firestore_form)
    assert restored["schedules_by_month"]["2026-06"]["assignments"] == (
        payload["schedules_by_month"]["2026-06"]["assignments"]
    )


def test_xlsx_export_smoke(monkeypatch):
    year, month = 2026, 7
    nurse = Nurse("test-nurse")
    result = ScheduleResult(
        feasible=True,
        assignments={(nurse.name, day): ShiftType.O for day in month_dates(year, month)},
    )
    state = {
        "year": year,
        "month": month,
        "nurses": [nurse],
        "schedule_result": result,
        "result_published": True,
    }
    monkeypatch.setattr(exports_module, "load_ward_state", lambda _: state)
    main_module.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        "ward", "admin", True
    )
    try:
        with TestClient(main_module.app) as client:
            response = client.get("/api/exports/xlsx")
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content.startswith(b"PK")
    assert ".xlsx" in response.headers["content-disposition"]
    workbook = openpyxl.load_workbook(BytesIO(response.content))
    assert workbook.sheetnames
