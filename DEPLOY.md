# Duty Maker 배포 가이드 (Streamlit Community Cloud + Firebase Firestore)

앱 실행은 Streamlit Community Cloud(무료), 데이터 저장은 Firebase Firestore(무료 한도)를 사용합니다.
모든 데이터(명단·신청·근무표·계정)는 Firestore에만 저장되며 사용자 브라우저·쿠키에는 남지 않습니다.

## 1. Firebase 프로젝트 만들기 (약 5분)

1. https://console.firebase.google.com 접속 → 구글 계정 로그인 → **프로젝트 추가**
   - 프로젝트 이름: 예) `duty-maker` (애널리틱스는 꺼도 됨)
2. 왼쪽 메뉴 **빌드 → Firestore Database → 데이터베이스 만들기**
   - 위치: `asia-northeast3 (서울)` 권장
   - 보안 규칙: **프로덕션 모드**(잠금 모드) 선택 — 앱은 서비스 계정 키로 접근하므로 규칙을 열 필요가 없습니다
3. 서비스 계정 키 발급: **프로젝트 설정(톱니바퀴) → 서비스 계정 → 새 비공개 키 생성**
   - JSON 파일이 다운로드됩니다. **이 파일은 절대 GitHub에 올리지 마세요** (아래 Secrets에만 붙여넣음)

## 2. GitHub에 코드 올리기

1. https://github.com 에서 **비공개(Private) 저장소** 생성: 예) `duty-maker`
2. 이 폴더에서:
   ```bash
   git remote add origin https://github.com/<계정명>/duty-maker.git
   git push -u origin master
   ```
   (`data/` 폴더는 .gitignore로 제외되어 있어 개인 데이터는 올라가지 않습니다)

## 3. Streamlit Community Cloud 배포

1. https://share.streamlit.io 접속 → GitHub 계정으로 로그인
2. **New app** → 저장소 `duty-maker`, 브랜치 `master`, 메인 파일 `app.py` 선택
3. **Advanced settings → Secrets** 에 아래 내용 붙여넣기:

   ```toml
   admin_password = "수쌤만_아는_비밀번호로_변경"

   [firebase]
   # 1-3에서 받은 서비스 계정 JSON의 내용을 그대로 옮겨 적습니다
   type = "service_account"
   project_id = "duty-maker-xxxxx"
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "firebase-adminsdk-...@duty-maker-xxxxx.iam.gserviceaccount.com"
   client_id = "..."
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "..."
   ```

   주의: `private_key` 값의 줄바꿈은 JSON에 있는 그대로 `\n` 포함해 한 줄로 붙여넣습니다.
4. **Deploy** 클릭 → 몇 분 뒤 `https://<앱이름>.streamlit.app` 주소가 생깁니다

## 4. 첫 설정 (수쌤)

1. 앱 접속 → **관리자** 탭에서 Secrets에 설정한 `admin_password`로 로그인
2. **명단** 탭에서 간호사/보조 인력 이름 정리 (이 명단에 있는 이름만 PIN 등록 가능)
3. 간호사들에게 주소 공유 → 각자 **PIN 등록(처음)** 탭에서 본인 이름 + PIN(4~6자리 숫자) 등록
4. **계정** 탭에서 특정 계정에 관리자 권한을 주거나, PIN 분실 시 초기화 가능
5. 신청을 받는 기간이 끝나면 **듀티 신청** 탭의 "신청 마감" 토글
6. 근무표 생성·조정 후 **결과** 탭의 "근무표 확정"을 눌러야 일반 사용자에게 공개됩니다

## 운영 메모

- 새 코드 배포: `git push` 하면 자동 재배포
- 앱은 한동안 접속이 없으면 잠들었다가 첫 접속 때 30초쯤 걸려 깨어납니다
- 여러 명이 동시에 신청해도 안전하게 저장됩니다 (신청 1건 = Firestore 문서 1개).
  관리자는 생성 전에 "신청 새로 불러오기" 버튼으로 최신 신청을 반영하세요
- 로컬에서 돌릴 때(Firebase 미설정)는 지금처럼 `data/` 폴더의 JSON 파일에 저장됩니다
- 백업: Firebase 콘솔 → Firestore에서 데이터 확인/내보내기 가능
