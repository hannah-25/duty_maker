# Duty Maker

병동 간호사 근무표를 자동 생성하는 FastAPI + vanilla HTML/CSS/JS 애플리케이션입니다.

기존 스케줄링 로직은 `core/`에 두고, FastAPI는 `/api` JSON API와 `frontend/` 정적 파일을 함께 제공합니다.

## 주요 기능

- 병원/병동 등록 및 병동별 데이터 분리
- 이름 + PIN 기반 로그인
- 관리자/일반 사용자 권한 분리
- 간호사 및 보조 인력 명단 관리
- 평일/주말/특정 날짜별 인원 기준 관리
- 근무 희망/제외 신청 및 신청 마감
- OR-Tools 기반 근무표 생성
- 생성 결과 공개/비공개
- 공개된 근무표 사용자 조회
- HWPX/XLSX 다운로드
- 로컬 JSON 또는 Firebase Firestore 저장

## 기술 스택

- Python 3.13
- FastAPI / Uvicorn
- Vanilla HTML, CSS, JavaScript
- OR-Tools CP-SAT
- pandas / openpyxl
- lxml
- Firebase Firestore 선택 지원

## 로컬 실행

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
uvicorn api.main:app --reload
```

브라우저에서 `http://127.0.0.1:8000`으로 접속합니다.

기본 병동 등록 코드는 `admin1234`입니다. 배포 환경에서는 반드시 `WARD_REGISTRATION_CODE`로 변경하세요.

## 환경 변수

| 이름 | 설명 |
| --- | --- |
| `SECRET_KEY` | JWT 서명 키. 배포 환경에서 필수로 설정하세요. |
| `WARD_REGISTRATION_CODE` | 새 병동 등록 코드. 기본값은 `admin1234`입니다. |
| `FIREBASE_CREDENTIALS_JSON` | Firebase 서비스 계정 JSON 문자열. 없으면 로컬 `data/`에 저장합니다. |

## 프로젝트 구조

```text
api/                 FastAPI 앱과 라우터
  main.py
  routers/
frontend/            정적 프론트엔드
  index.html
  css/
  js/
core/                UI와 무관한 도메인 로직
  models.py
  solver.py
  constraints.py
  validator.py
  persistence.py
  hwpx_export.py
templates/           HWPX 템플릿
tests/               pytest 테스트
scripts/             샘플 생성/마이그레이션 스크립트
```

## 검증

```bash
python -m pytest
```

현재 테스트는 스케줄러와 공휴일 계산 로직을 검증합니다.

## 배포

FastAPI를 실행할 수 있는 호스팅 환경에 배포합니다. 자세한 내용은 [DEPLOY.md](DEPLOY.md)를 참고하세요.
