# Duty Maker

병동 간호사 근무표를 자동으로 생성하는 웹앱입니다. 제약 조건(연차, 야간 근무 상한, 직급별 자격 등)을 만족하는 한 달치 근무표를 최적화 솔버로 생성하고, 결과를 검증한 뒤 병동 지정 양식(HWP)으로 내려받을 수 있습니다.

## 주요 기능

- **근무표 자동 생성**: OR-Tools 기반 제약 충족 솔버로 하루 인원 기준, 직급별 자격(차지 가능 여부, S 근무 자격 등), 연속 근무·나이트 제한, 개인별 연차/오프 목표를 반영해 한 달치 표를 생성
- **전수 검증**: 생성된 표가 모든 하드 규칙을 지켰는지 별도 검증기로 재확인하고, 입력한 제약 조건(연차 목표, 인원 기준, 신청 반영 등)이 실제로 반영됐는지 항목별 체크리스트로 표시
- **듀티 신청 반영**: 개인별 희망/제외 신청을 입력하면 우선순위에 따라 최대한 반영하고, 반영/미반영 내역을 확인 및 조정 가능
- **보조 인력 관리**: 간호조무사 등 솔버 대상이 아닌 인력도 명단 관리와 휴무 신청이 가능하며 결과표·HWP에 함께 표시
- **HWP 양식 다운로드**: 병동에서 쓰는 hwpx 양식에 생성 결과를 그대로 채워 내려받기 (근무 표기, 연차·오프 색상, 주말/공휴일 배경 자동 반영)
- **로그인/권한 분리**: 이름 + PIN(4~6자리) 로그인, 쿠키 미사용(세션 메모리만). 일반 사용자는 본인 신청 등록/열람만, 관리자는 명단·기준·생성·확정·계정 관리 전체 권한
- **데이터 저장**: 명단·신청·설정·생성 결과를 저장해 새로고침해도 유지 (로컬 실행 시 JSON 파일, 배포 시 Firebase Firestore)

## 기술 스택

- Python 3.13, Streamlit (UI)
- OR-Tools CP-SAT (근무표 최적화)
- lxml (hwpx 양식 조작), openpyxl (엑셀 내보내기)
- Firebase Firestore (배포 환경 데이터 저장, 로컬은 JSON 폴백)

## 로컬 실행

```bash
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -r requirements.txt
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속 후 로그인합니다. 관리자 비밀번호는 기본값 `admin1234` (배포 시 반드시 변경).

## 프로젝트 구조

```
core/               도메인 로직 (화면과 무관)
  models.py           간호사/신청/결과 데이터 정의
  solver.py           근무표 생성 (OR-Tools)
  constraints.py      하드/소프트 제약 정의
  validator.py        생성 결과 검증 + 반영 체크리스트
  hwpx_export.py       HWP 양식에 결과 채워 내보내기
  auth.py             PIN 해시/계정 검증
  persistence.py      상태 저장/복원 (로컬 JSON ↔ Firestore)
  holidays_kr.py      공휴일 조회
  sample_data.py      데모용 샘플 명단/기준

ui/                 Streamlit 화면
  login.py            로그인/가입/계정 관리
  nurse_editor.py      명단·보조 인력 편집
  requirement_editor.py 인원 기준·공휴일·특정일 예외
  duty_request_editor.py 듀티 신청 등록/조정
  schedule_view.py     생성 결과 표시·다운로드

app.py              진입점 (권한별 화면 라우팅)
templates/          HWP 양식 원본
tests/              pytest 테스트
```

## 배포

Streamlit Community Cloud + Firebase Firestore 조합으로 배포합니다. 단계별 절차는 [DEPLOY.md](DEPLOY.md) 참고.
