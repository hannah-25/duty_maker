# Duty Maker 배포 가이드

이 앱은 FastAPI 서버가 JSON API와 정적 프론트엔드를 함께 제공합니다.

## 필수 환경 변수

| 이름 | 설명 |
| --- | --- |
| `SECRET_KEY` | JWT 서명 키. 충분히 긴 임의 문자열을 사용하세요. |
| `WARD_REGISTRATION_CODE` | 새 병원/병동 등록에 필요한 코드입니다. |
| `FIREBASE_CREDENTIALS_JSON` | 선택 사항. Firebase 서비스 계정 JSON 문자열입니다. 없으면 로컬 파일 저장소를 사용합니다. |

## 실행 명령

```bash
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Windows PowerShell 로컬 실행:

```powershell
pip install -r requirements.txt
uvicorn api.main:app --reload
```

## 저장소 선택

### 로컬 JSON

`FIREBASE_CREDENTIALS_JSON`을 설정하지 않으면 `data/wards/{ward_id}/` 아래에 JSON 파일로 저장합니다.

이 방식은 로컬 개발에는 간단하지만, 서버 재배포 때 파일 시스템이 초기화되는 호스팅에는 적합하지 않습니다.

### Firebase Firestore

운영 배포에서는 Firestore 사용을 권장합니다.

1. Firebase Console에서 프로젝트를 생성합니다.
2. Firestore Database를 생성합니다.
3. 서비스 계정 JSON을 발급합니다.
4. JSON 전체를 한 줄 문자열로 `FIREBASE_CREDENTIALS_JSON` 환경 변수에 설정합니다.

## 최초 설정

1. 앱에 접속합니다.
2. 병원/병동을 등록합니다.
3. 등록 코드에는 `WARD_REGISTRATION_CODE` 값을 입력합니다.
4. 최초 관리자 이름과 PIN을 등록합니다.
5. 관리자 계정으로 명단, 인원 기준, 계정 권한을 설정합니다.
6. 사용자에게 URL을 공유하면 명단에 있는 이름으로 PIN을 등록할 수 있습니다.

## 운영 메모

- `SECRET_KEY`를 변경하면 기존 JWT는 모두 무효화됩니다.
- 병동 등록 코드는 외부에 공개하지 마세요.
- Firestore를 사용할 때는 서비스 계정 JSON을 저장소에 커밋하지 마세요.
- HWPX 다운로드는 `templates/duty_template.hwpx`가 배포 패키지에 포함되어야 동작합니다.
