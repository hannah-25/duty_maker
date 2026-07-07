"""이름+PIN 로그인 계정 관리.

PIN은 원문을 저장하지 않고 PBKDF2-SHA256 해시(개인 salt 포함)로만 저장한다.
계정 자체는 persistence 계층(load_users/save_users)을 통해 저장된다.
"""

from __future__ import annotations

import hashlib
import secrets

PIN_MIN_LEN = 4
PIN_MAX_LEN = 6
_ITERATIONS = 120_000


def valid_pin_format(pin: str) -> bool:
    return pin.isdigit() and PIN_MIN_LEN <= len(pin) <= PIN_MAX_LEN


def hash_pin(pin: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), _ITERATIONS).hex()
    return salt, digest


def verify_pin(pin: str, salt: str, expected_hash: str) -> bool:
    return secrets.compare_digest(hash_pin(pin, salt)[1], expected_hash)


def create_account(users: dict[str, dict], name: str, pin: str, is_admin: bool = False) -> dict[str, dict]:
    salt, digest = hash_pin(pin)
    users = dict(users)
    users[name] = {"pin_salt": salt, "pin_hash": digest, "is_admin": is_admin}
    return users


def check_login(users: dict[str, dict], name: str, pin: str) -> bool:
    account = users.get(name)
    if not account:
        return False
    return verify_pin(pin, account.get("pin_salt", ""), account.get("pin_hash", ""))
