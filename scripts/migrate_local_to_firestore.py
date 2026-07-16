"""Migrate local ward JSON data into the configured Firestore backend.

This script copies the current local storage layout:

    data/wards_registry.json
    data/wards/{ward_id}/app_state.json
    data/wards/{ward_id}/users.json

into the Firestore layout used by core.persistence:

    wards/{ward_id}
    wards/{ward_id}/app_state/main
    wards/{ward_id}/duty_requests/{request_id}
    wards/{ward_id}/users/{name}

Set STORAGE_BACKEND=firestore and FIREBASE_CREDENTIALS_JSON to a Firebase
service account JSON string before running this script.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.persistence import (  # noqa: E402
    DATA_DIR,
    WARDS_REGISTRY_PATH,
    _firestore,
    _split_requests,
    _to_firestore_payload,
)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _migrate_ward(db, ward_id: str, ward_info: dict, dry_run: bool) -> dict[str, int]:
    ward_dir = DATA_DIR / "wards" / ward_id
    state_path = ward_dir / "app_state.json"
    users_path = ward_dir / "users.json"

    state_payload = _load_json(state_path)
    users = _load_json(users_path)
    rest, requests = _split_requests(_to_firestore_payload(state_payload)) if state_payload else ({}, {})

    counts = {
        "state_docs": 1 if rest else 0,
        "request_docs": len(requests),
        "user_docs": len(users),
    }
    if dry_run:
        return counts

    ward_ref = db.collection("wards").document(ward_id)
    batch = db.batch()
    batch.set(ward_ref, ward_info)
    if rest:
        batch.set(ward_ref.collection("app_state").document("main"), rest)
    for doc_id, request in requests.items():
        batch.set(ward_ref.collection("duty_requests").document(doc_id), request)
    for name, account in users.items():
        batch.set(ward_ref.collection("users").document(name), account)
    batch.commit()
    return counts


def _delete_stale_firestore_docs(db, ward_id: str, local_state: dict, local_users: dict) -> dict[str, int]:
    """Remove Firestore request/user docs that no longer exist locally."""
    ward_ref = db.collection("wards").document(ward_id)
    _, local_requests = _split_requests(local_state) if local_state else ({}, {})
    local_user_names = set(local_users)

    deleted_requests = 0
    deleted_users = 0
    batch = db.batch()
    for snap in ward_ref.collection("duty_requests").stream():
        if snap.id not in local_requests:
            batch.delete(snap.reference)
            deleted_requests += 1
    for snap in ward_ref.collection("users").stream():
        if snap.id not in local_user_names:
            batch.delete(snap.reference)
            deleted_users += 1
    if deleted_requests or deleted_users:
        batch.commit()
    return {"deleted_request_docs": deleted_requests, "deleted_user_docs": deleted_users}


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local ward JSON data to Firestore.")
    parser.add_argument("--ward-id", help="Migrate only one ward id.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be migrated.")
    parser.add_argument(
        "--delete-stale",
        action="store_true",
        help="Delete Firestore request/user docs that are absent from local JSON.",
    )
    args = parser.parse_args()

    db = None if args.dry_run else _firestore()
    if db is None and not args.dry_run:
        raise SystemExit(
            "Firestore credentials are not configured. Set FIREBASE_CREDENTIALS_JSON "
            "to a Firebase service account JSON string, then rerun this script."
        )

    wards = _load_json(WARDS_REGISTRY_PATH)
    if args.ward_id:
        if args.ward_id not in wards:
            raise SystemExit(f"Ward id not found in {WARDS_REGISTRY_PATH}: {args.ward_id}")
        wards = {args.ward_id: wards[args.ward_id]}

    if not wards:
        raise SystemExit(f"No wards found in {WARDS_REGISTRY_PATH}")

    total = {"wards": 0, "state_docs": 0, "request_docs": 0, "user_docs": 0}
    stale_total = {"deleted_request_docs": 0, "deleted_user_docs": 0}
    for ward_id, ward_info in wards.items():
        counts = _migrate_ward(db, ward_id, ward_info, args.dry_run)
        total["wards"] += 1
        for key in ("state_docs", "request_docs", "user_docs"):
            total[key] += counts[key]

        if args.delete_stale and not args.dry_run:
            ward_dir = DATA_DIR / "wards" / ward_id
            stale_counts = _delete_stale_firestore_docs(
                db,
                ward_id,
                _load_json(ward_dir / "app_state.json"),
                _load_json(ward_dir / "users.json"),
            )
            for key, value in stale_counts.items():
                stale_total[key] += value

        action = "Would migrate" if args.dry_run else "Migrated"
        print(
            f"{action} {ward_id}: state={counts['state_docs']}, "
            f"requests={counts['request_docs']}, users={counts['user_docs']}"
        )

    print(
        f"Done: wards={total['wards']}, state={total['state_docs']}, "
        f"requests={total['request_docs']}, users={total['user_docs']}"
    )
    if args.delete_stale and not args.dry_run:
        print(
            f"Deleted stale docs: requests={stale_total['deleted_request_docs']}, "
            f"users={stale_total['deleted_user_docs']}"
        )


if __name__ == "__main__":
    main()
