"""레거시(병동 구분 도입 이전) 데이터를 새 병동 구조로 옮기는 1회성 스크립트.

병원/병동 개념을 도입하기 전에는 앱 전체가 데이터 하나만 공유했다. 이 스크립트는
그 데이터를 지정한 병원/병동 아래로 복사한다. 원본은 지우지 않는다 (비파괴적) —
확인 후 필요하면 수동으로 정리한다.

사용법:
    python scripts/migrate_to_ward.py "병원 이름" "병동 이름"

로컬 JSON 백엔드: data/app_state.json, data/users.json -> data/wards/{ward_id}/...
Firestore 백엔드: 최상위 app_state/main, users/*, duty_requests/* -> wards/{ward_id}/...
    (Streamlit secrets.toml에 [firebase] 설정이 있어야 Firestore로 동작)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.persistence import DATA_DIR, _firestore, create_ward  # noqa: E402


def _migrate_local(ward_id: str) -> None:
    legacy_state = DATA_DIR / "app_state.json"
    legacy_users = DATA_DIR / "users.json"
    ward_dir = DATA_DIR / "wards" / ward_id
    ward_dir.mkdir(parents=True, exist_ok=True)

    if legacy_state.exists():
        (ward_dir / "app_state.json").write_text(
            legacy_state.read_text(encoding="utf-8"), encoding="utf-8"
        )
        print(f"이전 완료: {legacy_state} -> {ward_dir / 'app_state.json'}")
    else:
        print(f"레거시 상태 파일 없음: {legacy_state} (건너뜀)")

    if legacy_users.exists():
        (ward_dir / "users.json").write_text(
            legacy_users.read_text(encoding="utf-8"), encoding="utf-8"
        )
        print(f"이전 완료: {legacy_users} -> {ward_dir / 'users.json'}")
    else:
        print(f"레거시 계정 파일 없음: {legacy_users} (건너뜀)")


def _migrate_firestore(ward_id: str) -> None:
    db = _firestore()
    ward_ref = db.collection("wards").document(ward_id)

    state_doc = db.collection("app_state").document("main").get()
    if state_doc.exists:
        ward_ref.collection("app_state").document("main").set(state_doc.to_dict())
        print(f"이전 완료: app_state/main -> wards/{ward_id}/app_state/main")
    else:
        print("레거시 app_state/main 문서 없음 (건너뜀)")

    request_snaps = list(db.collection("duty_requests").stream())
    for snap in request_snaps:
        ward_ref.collection("duty_requests").document(snap.id).set(snap.to_dict())
    print(f"이전 완료: duty_requests {len(request_snaps)}건")

    user_snaps = list(db.collection("users").stream())
    for snap in user_snaps:
        ward_ref.collection("users").document(snap.id).set(snap.to_dict())
    print(f"이전 완료: users {len(user_snaps)}건")


def main() -> None:
    if len(sys.argv) != 3:
        print('사용법: python scripts/migrate_to_ward.py "병원 이름" "병동 이름"')
        sys.exit(1)
    hospital_name, ward_name = sys.argv[1], sys.argv[2]

    ward_id = create_ward(hospital_name, ward_name)
    if ward_id is None:
        print("이미 등록된 병원/병동입니다. wards_registry.json(로컬) 또는 Firestore wards 컬렉션을 확인하세요.")
        sys.exit(1)
    print(f"병동 등록: {hospital_name} - {ward_name} (ward_id={ward_id})")

    if _firestore() is not None:
        _migrate_firestore(ward_id)
    else:
        _migrate_local(ward_id)

    print("이전 완료. 원본 레거시 데이터는 그대로 남아 있습니다 (필요하면 수동으로 정리하세요).")


if __name__ == "__main__":
    main()
