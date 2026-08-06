"""Security primitives used by the web application."""

from __future__ import annotations

import secrets
from hmac import compare_digest

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request


password_hasher = PasswordHasher()
CSRF_COOKIE_NAME = "csrf_token"


def hash_password(password: str) -> str:
    """Return a password hash using Argon2id parameters from argon2-cffi."""

    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password without exposing whether an account exists."""

    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        # Legacy plaintext records are intentionally not accepted. A database
        # reset is safer than retaining a plaintext compatibility path.
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return password_hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, VerificationError):
        return False


def is_password_hash(value: str) -> bool:
    return value.startswith("$argon2")


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def require_csrf(request: Request) -> None:
    """Validate the double-submit CSRF token for browser state changes."""

    expected = request.cookies.get(CSRF_COOKIE_NAME)
    provided = request.headers.get("X-CSRF-Token")
    if not provided:
        form = await request.form()
        provided = form.get("csrf_token")

    if not expected or not isinstance(provided, str) or not compare_digest(expected, provided):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")
