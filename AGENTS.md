# AGENTS.md

이 저장소에서 작업하는 에이전트를 위한 주의사항 모음.

## 상태 저장: Firestore는 중첩 배열을 못 담는다

배포 환경은 Firestore(`STORAGE_BACKEND=firestore`), 로컬은 JSON 파일로 상태를 저장한다.
**Firestore 문서는 배열 안에 배열을 직접 넣을 수 없다.** 그래서 `core/persistence.py`의
`_result_to_dict`가 만드는 배정(`assignments`)은 배열-of-배열
(`[[name, day, shift], ...]`) 형태라, Firestore로 보내기 전에 반드시 배열-of-객체
(`[{nurse_name, day, shift}, ...]`)로 바꿔 줘야 한다.

이 변환은 `_to_firestore_payload` / `_from_firestore_payload`에서 하며,
`_result_assignments_to_firestore` / `_result_assignments_from_firestore` 헬퍼로 재사용한다.

- **함정:** 예전에는 `schedule_result`만 변환하고 `schedule_previews[*]["result"]`를
  빠뜨려서, "선택 영역 미리보기"가 로컬에서는 되고 배포에서만 500으로 실패했다.
  (미리보기 저장 시 중첩 배열 → Firestore 거부)
- **규칙:** 배정(`assignments`) 같은 배열-of-배열을 담는 새 상태를 저장 대상에 추가하면,
  위 두 변환 함수 **양쪽**에 변환을 반드시 추가하고, 로컬 JSON 왕복만이 아니라 Firestore
  형태(중첩 배열 없음)까지 검증하는 테스트를 넣는다.
  참고: `tests/test_deployment.py::test_firestore_payload_roundtrips_schedule_previews`.
- 로컬 JSON 저장은 중첩 배열을 그대로 받으므로, 로컬에서만 테스트하면 이 부류의 버그를
  절대 못 잡는다.

## 솔버 하드 제약: 사용자 명시적 동의 없이 바꾸지 않는다

`core/constraints.py`의 하드 규칙(`add_tier1_hard_constraints`가 부르는 `_rule_*`, `_rule_off_cap`
등)과 소프트 규칙(`add_tier2_soft_constraints`가 부르는 `_soft_*`) 사이의 경계는 병동 운영 규칙을
그대로 코드로 옮긴 것이다. 이걸 하드↔소프트로 옮기거나, 부등식 방향(`<=`/`==`/`>=`)을 바꾸거나,
가중치·상한을 조정하는 건 **동작을 바꾸는 정책 결정**이지 리팩터링이 아니다.

- **함정:** 예전에 커밋 없이 "목표 인원 미달이면 벌점"(소프트)을 "정확히 일치해야 함"(하드)으로
  바꾼 적이 있었는데, 그게 오프 목표(`off_target`)·연차 배분 로직과 맞물려 근무표가 조용히(에러
  없이) 오프 개수를 못 맞추는 결과를 냈다. 사용자는 한참 뒤 화면에서 숫자가 이상한 걸 보고서야
  원인이 이 제약 변경이었다는 걸 알게 됐다 — 정작 그 세션에서는 이걸 바꾼다는 합의가 없었다.
- **규칙:** `core/constraints.py`의 기존 하드 제약(범위·부등식·존재 여부)은 사용자가 그 규칙을
  명시적으로 지목해서 바꿔달라고 하기 전에는 건드리지 않는다. 관련 버그를 고치다가 "이 제약을
  하드로/소프트로 바꾸면 해결될 것 같다"는 판단이 서더라도, 먼저 사용자에게 확인받고 나서
  구현한다. 새 하드 제약을 추가하는 것도 마찬가지 — 기존 동작을 바꾸는 결정은 반드시 합의 후에.
