# Streamlit to FastAPI Migration Plan

## Goal

Replace the existing Streamlit UI with a FastAPI backend and a vanilla HTML/CSS/JS frontend while preserving the existing scheduling domain logic in `core/`.

The final app should run as:

```bash
uvicorn api.main:app --reload
```

FastAPI will serve both JSON APIs under `/api` and the static frontend from `frontend/`.

## Target Structure

```text
core/          Domain logic kept UI-independent
api/           FastAPI app, routers, schemas, auth, state adapters
frontend/      Vanilla HTML, CSS, and JavaScript SPA
tests/         Core tests plus API tests
templates/     Existing HWPX template assets
```

The Streamlit entrypoint and UI modules will be removed after feature parity is reached:

```text
app.py
ui/
streamlit dependency
```

## Migration Principles

1. Keep `core/` as the source of truth for scheduling, validation, persistence, authentication helpers, and export logic.
2. Move UI state out of `st.session_state` and into plain dictionaries loaded and saved through `api/state_store.py`.
3. Expose every user workflow through explicit JSON endpoints.
4. Keep the frontend simple: route by JavaScript modules, call `api.js`, and render each screen from `frontend/js/views/`.
5. Remove Streamlit only after login, admin workflows, member workflows, schedule generation, result publishing, and exports all work.

## Phase 1: Stabilize Current FastAPI/Frontend Baseline

- Fix Python and JavaScript syntax errors introduced by broken Korean strings.
- Replace mojibake UI text with readable Korean labels.
- Ensure `api.main:app` imports successfully.
- Ensure the static frontend loads without browser console syntax errors.
- Verify existing endpoints:
  - `GET /api/wards`
  - `POST /api/wards`
  - `POST /api/auth/login`
  - `POST /api/auth/register`
  - `GET /api/nurses`
  - `PUT /api/nurses`

## Phase 2: Complete Authentication and Ward Selection

- Finish ward list and ward registration UI.
- Finish login and member registration UI.
- Keep JWT in memory only unless persistent login is explicitly desired.
- Confirm admin/member routing:
  - Admin: roster, requirements, requests, result, accounts
  - Member: requests, published result

## Phase 3: Roster Management

- Complete nurse and assistant editing.
- Preserve row ordering for export and schedule display.
- Validate nurse names, levels, shift eligibility, night limits, annual leave target, and weekday-only settings.
- Add API tests for roster read/write.

## Phase 4: Staffing Requirements

- Add `/api/requirements` endpoints.
- Port behavior from `ui/requirement_editor.py`:
  - year/month selection
  - weekday template
  - weekend template
  - selected holidays
  - date-specific overrides
- Build `frontend/js/views/requirements.js`.
- Store requirements in the existing ward state payload.

## Phase 5: Duty Requests

- Add `/api/requests` endpoints.
- Port behavior from `ui/duty_request_editor.py`:
  - member self-service request editing
  - admin request review/editing
  - request lock toggle
  - remote reload behavior when applicable
- Build `frontend/js/views/requests.js`.
- Enforce member access so non-admin users can only edit their own requests.

## Phase 6: Schedule Generation and Validation

- Add schedule endpoints:
  - `POST /api/schedule/generate`
  - `GET /api/schedule`
  - `PUT /api/schedule/publish`
- Port generation logic from `app.py`:
  - build monthly requirements
  - compute off targets from weekends and selected holidays
  - filter duty requests to active roster names
  - call `generate_schedule`
  - call `validate_schedule`
  - save result and validation report
- Build `frontend/js/views/schedule-result.js`.
- Show infeasible solver output clearly.

## Phase 7: Account Administration

- Add `/api/accounts` endpoints for admins.
- Port account administration from `ui/login.py`:
  - list accounts
  - create/reset PIN
  - remove users if supported by current behavior
  - manage admin flag if supported by current behavior
- Build `frontend/js/views/accounts.js`.

## Phase 8: Exports

- Add export endpoints:
  - `GET /api/exports/hwpx`
  - `GET /api/exports/xlsx`
- Reuse `core/hwpx_export.py` and existing export helpers.
- Return downloadable binary responses from FastAPI.
- Trigger downloads from the frontend using Blob URLs.

## Phase 9: Remove Streamlit

- Delete `app.py`.
- Delete `ui/`.
- Remove `streamlit` from `requirements.txt`.
- Remove Streamlit-specific deployment instructions.
- Ensure Firebase credentials use `FIREBASE_CREDENTIALS_JSON` or another server-side environment variable.

## Phase 10: Documentation and Verification

- Update `README.md`:
  - FastAPI run command
  - environment variables
  - project structure
  - local JSON vs Firebase persistence
- Update `DEPLOY.md` for FastAPI hosting.
- Run tests:
  - existing core tests
  - new API tests
- Manually verify the main browser workflows:
  - create ward
  - login admin
  - edit roster
  - edit requirements
  - submit requests
  - generate schedule
  - publish result
  - login member
  - view published result
  - download export

## Current Next Steps

1. Stabilize the existing FastAPI/frontend scaffold.
2. Finish the roster workflow.
3. Add requirements API and UI.
4. Add duty request API and UI.
5. Add schedule generation/result API and UI.
