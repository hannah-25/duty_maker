"""Enable the Cloud Firestore API for the Firebase project.

Requires FIREBASE_CREDENTIALS_JSON to contain a service account JSON string.
The service account must have permission to enable Google Cloud services.
"""

from __future__ import annotations

import json
import os
import sys
import time

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account


def main() -> None:
    raw = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    if not raw:
        raise SystemExit("FIREBASE_CREDENTIALS_JSON is not configured.")

    info = json.loads(raw)
    project_id = info["project_id"]
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    session = AuthorizedSession(credentials)

    service_name = f"projects/{project_id}/services/firestore.googleapis.com"
    enable_url = f"https://serviceusage.googleapis.com/v1/{service_name}:enable"
    response = session.post(enable_url, timeout=30)
    if response.status_code == 200:
        operation = response.json()
        name = operation.get("name")
        if not name:
            print("Cloud Firestore API enable request accepted.")
            return
        for _ in range(24):
            op_response = session.get(f"https://serviceusage.googleapis.com/v1/{name}", timeout=30)
            if op_response.status_code != 200:
                print(op_response.text, file=sys.stderr)
                op_response.raise_for_status()
            op = op_response.json()
            if op.get("done"):
                if "error" in op:
                    raise SystemExit(op["error"])
                print("Cloud Firestore API is enabled.")
                return
            time.sleep(5)
        raise SystemExit("Timed out waiting for Cloud Firestore API enable operation.")

    if response.status_code == 409:
        print("Cloud Firestore API is already enabled or enable operation is in progress.")
        return

    print(response.text, file=sys.stderr)
    response.raise_for_status()


if __name__ == "__main__":
    main()
