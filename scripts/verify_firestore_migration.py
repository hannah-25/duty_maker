"""Verify migrated Firestore ward data counts and deserialization."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.state_store import load_ward_state  # noqa: E402
from core.persistence import _firestore  # noqa: E402


def main() -> None:
    if os.environ.get("STORAGE_BACKEND", "").lower() != "firestore":
        raise SystemExit("STORAGE_BACKEND must be set to firestore.")
    if not os.environ.get("FIREBASE_CREDENTIALS_JSON"):
        raise SystemExit("FIREBASE_CREDENTIALS_JSON is not configured.")
    db = _firestore()

    total_state = 0
    total_requests = 0
    total_users = 0
    wards = list(db.collection("wards").stream())
    for ward in wards:
        ward_ref = db.collection("wards").document(ward.id)
        state_exists = ward_ref.collection("app_state").document("main").get().exists
        requests = list(ward_ref.collection("duty_requests").stream())
        users = list(ward_ref.collection("users").stream())

        if state_exists:
            total_state += 1
            loaded = load_ward_state(ward.id)
            json.dumps(loaded.get("year"), ensure_ascii=False)
        total_requests += len(requests)
        total_users += len(users)
        print(
            f"{ward.id}: state={state_exists}, "
            f"requests={len(requests)}, users={len(users)}"
        )

    print(
        f"total: wards={len(wards)}, state={total_state}, "
        f"requests={total_requests}, users={total_users}"
    )


if __name__ == "__main__":
    main()
