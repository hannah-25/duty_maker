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
