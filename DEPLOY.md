# Duty Maker 배포 가이드

이 프로젝트는 FastAPI가 `/api` JSON API와 `frontend/` 정적 파일을 함께 서빙합니다.
운영 배포는 **Cloud Run 단일 서비스 + Firestore + GitHub Actions**를 기준으로 합니다.

## 배포 흐름

```text
pull_request / push -> GitHub Actions CI -> pytest
master push          -> GitHub Actions Deploy -> Cloud Run
Cloud Run            -> FastAPI + frontend
Firestore            -> 병동/계정/근무표 데이터 저장
```

## 레포에 포함된 배포 파일

- `Dockerfile`: Cloud Run 컨테이너 실행 정의
- `Procfile`: Cloud Run source/buildpack 배포 fallback 시작 명령
- `.dockerignore`: 배포 이미지에서 로컬/민감 파일 제외
- `.github/workflows/ci.yml`: PR/push 테스트
- `.github/workflows/deploy.yml`: `master` push 또는 수동 실행 시 Cloud Run 배포

## 운영 환경 변수와 Secret

Cloud Run에는 아래 값이 필요합니다.

| 이름 | 권장 저장 위치 | 설명 |
| --- | --- | --- |
| `SECRET_KEY` | Secret Manager | JWT 서명 키. 충분히 긴 임의 문자열을 사용합니다. |
| `WARD_REGISTRATION_CODE` | Secret Manager | 새 병원/병동 등록 코드입니다. |
| `STORAGE_BACKEND` | Cloud Run 환경 변수 | 운영에서는 `firestore`로 고정합니다. |
| `FIREBASE_CREDENTIALS_JSON` | 사용하지 않음 권장 | 로컬/임시 배포용 서비스 계정 JSON. Cloud Run에서는 기본 서비스 계정 인증을 씁니다. |

GitHub Actions 배포 워크플로우는 Secret Manager의 아래 secret 이름을 사용합니다.

```text
duty-maker-secret-key
duty-maker-ward-registration-code
```

## Google Cloud 1회 설정

아래 값은 본인 프로젝트에 맞게 바꿉니다.

```bash
PROJECT_ID="your-gcp-project-id"
PROJECT_NUMBER="your-gcp-project-number"
REGION="asia-northeast3"
SERVICE="duty-maker"
REPO="github-owner/github-repo"
DEPLOYER_SA="github-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SA="duty-maker-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
POOL_ID="github"
PROVIDER_ID="github"
```

필수 API를 켭니다.

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  iamcredentials.googleapis.com \
  --project "${PROJECT_ID}"
```

Firestore 데이터베이스를 생성합니다. 콘솔에서 Firestore Native mode로 생성해도 됩니다.

```bash
gcloud firestore databases create \
  --database="(default)" \
  --location="${REGION}" \
  --project "${PROJECT_ID}"
```

Secret Manager 값을 만듭니다.

```bash
printf "replace-with-long-random-secret" | \
  gcloud secrets create duty-maker-secret-key \
    --data-file=- \
    --project "${PROJECT_ID}"

printf "replace-with-private-registration-code" | \
  gcloud secrets create duty-maker-ward-registration-code \
    --data-file=- \
    --project "${PROJECT_ID}"
```

서비스 계정을 만듭니다.

```bash
gcloud iam service-accounts create github-deployer \
  --display-name="GitHub Actions Cloud Run deployer" \
  --project "${PROJECT_ID}"

gcloud iam service-accounts create duty-maker-runtime \
  --display-name="Duty Maker Cloud Run runtime" \
  --project "${PROJECT_ID}"
```

런타임 서비스 계정에 Firestore와 Secret 접근 권한을 줍니다.

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/datastore.user"

gcloud secrets add-iam-policy-binding duty-maker-secret-key \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project "${PROJECT_ID}"

gcloud secrets add-iam-policy-binding duty-maker-ward-registration-code \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project "${PROJECT_ID}"
```

GitHub Actions 배포 서비스 계정에 source deploy 권한을 줍니다.

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DEPLOYER_SA}" \
  --role="roles/run.sourceDeveloper"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${DEPLOYER_SA}" \
  --role="roles/serviceusage.serviceUsageConsumer"

gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
  --member="serviceAccount:${DEPLOYER_SA}" \
  --role="roles/iam.serviceAccountUser" \
  --project "${PROJECT_ID}"

gcloud secrets add-iam-policy-binding duty-maker-secret-key \
  --member="serviceAccount:${DEPLOYER_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project "${PROJECT_ID}"

gcloud secrets add-iam-policy-binding duty-maker-ward-registration-code \
  --member="serviceAccount:${DEPLOYER_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project "${PROJECT_ID}"
```

Cloud Build 기본 서비스 계정에 source build 권한을 줍니다.

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/run.builder"
```

## GitHub Actions OIDC 연결

Workload Identity Pool과 Provider를 만듭니다.

```bash
gcloud iam workload-identity-pools create "${POOL_ID}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL_ID}" \
  --display-name="GitHub Actions provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='${REPO}'"
```

GitHub repo가 배포 서비스 계정을 impersonate할 수 있게 합니다.

```bash
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_SA}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"
```

GitHub 저장소의 **Settings -> Secrets and variables -> Actions -> Variables**에 아래 값을 넣습니다.

| 이름 | 예시 |
| --- | --- |
| `GCP_PROJECT_ID` | `your-gcp-project-id` |
| `CLOUD_RUN_REGION` | `asia-northeast3` |
| `CLOUD_RUN_SERVICE` | `duty-maker` |
| `CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT` | `duty-maker-runtime@PROJECT_ID.iam.gserviceaccount.com` |
| `WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github` |
| `WIF_SERVICE_ACCOUNT` | `github-deployer@PROJECT_ID.iam.gserviceaccount.com` |

## 첫 배포

`master` 브랜치에 push하면 `.github/workflows/deploy.yml`이 실행됩니다.

수동 실행도 가능합니다.

```text
GitHub -> Actions -> Deploy -> Run workflow
```

배포가 끝나면 Actions 로그의 `Show service URL` 단계에 Cloud Run URL이 출력됩니다.

## 배포 후 확인

1. Cloud Run URL에 접속합니다.
2. 병원/병동을 등록합니다.
3. 등록 코드에 `WARD_REGISTRATION_CODE` 값을 입력합니다.
4. 관리자 계정을 생성합니다.
5. 명단, 인원 기준, 요청, 근무표 생성, HWPX/XLSX 다운로드를 확인합니다.

## 로컬 실행

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
uvicorn api.main:app --reload
```

로컬에서는 `STORAGE_BACKEND=local`(기본값)로 `data/` 아래 JSON 파일 저장소를 사용합니다.
운영 Cloud Run에서는 `STORAGE_BACKEND=firestore`로 설정하고, `FIREBASE_CREDENTIALS_JSON` 없이 런타임 서비스 계정의 Application Default Credentials로 Firestore에 연결합니다. Firestore 연결 검증에 실패하면 로컬 파일로 전환하지 않고 애플리케이션 시작이 실패합니다.
