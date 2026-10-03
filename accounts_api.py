"""Own-password changes for every user; account administration for admins."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

import auth
from barangays import canonical_barangay

router = APIRouter(tags=["accounts"])


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class ActiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field(default="", max_length=150)
    role: Literal["barangay", "staff"] = "barangay"
    barangay: str | None = Field(default=None, max_length=64)


def _db_error(exc):
    raise HTTPException(503, "Account storage is unavailable. Please try again.") from exc


@router.post("/api/me/password")
def change_own_password(body: PasswordIn, request: Request, response: Response):
    # Deliberately not require_any: that guard blocks users who still hold a
    # temporary password, and this is the one route they must be able to reach.
    user = auth.current_user(request)
    if user is None:
        raise HTTPException(401, "Login required")
    try:
        updated = auth.change_password(user["uid"], body.current_password, body.new_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        _db_error(exc)
    response.set_cookie(key=auth.COOKIE_NAME, value=auth.make_session_token(updated),
                        max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax")
    return {"ok": True, "redirect": "/barangay" if updated["role"] == "barangay" else "/"}


def _public(row):
    row = dict(row)
    for key in ("created_at", "last_login"):
        value = row.get(key)
        row[key] = str(value)[:16] if value else None
    row["is_active"] = bool(row.get("is_active"))
    row["must_change_password"] = bool(row.get("must_change_password"))
    return row


@router.get("/api/accounts")
def accounts(user=Depends(auth.require_admin)):
    try:
        return {"accounts": [_public(r) for r in auth.list_accounts()]}
    except RuntimeError as exc:
        _db_error(exc)


@router.post("/api/accounts", status_code=201)
def create_account(body: AccountIn, user=Depends(auth.require_admin)):
    barangay = None
    if body.role == "barangay":
        try:
            barangay = canonical_barangay(body.barangay or "")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    temporary = auth.generate_password()
    try:
        ok = auth.create_user(body.username, temporary, full_name=body.full_name,
                              role=body.role, barangay=barangay, must_change=True)
    except RuntimeError as exc:
        _db_error(exc)
    if not ok:
        raise HTTPException(409, "That username already exists.")
    return {"username": body.username, "temporary_password": temporary,
            "note": "Shown once. The user must change it at first sign-in."}


def _not_self(user, username):
    if username == user["u"]:
        raise HTTPException(422, "Use My account to manage your own sign-in.")


@router.post("/api/accounts/{username}/reset")
def reset(username: str, user=Depends(auth.require_admin)):
    _not_self(user, username)
    try:
        temporary = auth.reset_password(username)
    except KeyError:
        raise HTTPException(404, "Account not found")
    except RuntimeError as exc:
        _db_error(exc)
    return {"username": username, "temporary_password": temporary,
            "note": "Shown once. The user must change it at next sign-in."}


@router.post("/api/accounts/{username}/active")
def activate(username: str, body: ActiveIn, user=Depends(auth.require_admin)):
    _not_self(user, username)
    try:
        found = auth.set_active(username, body.active)
    except RuntimeError as exc:
        _db_error(exc)
    if not found:
        raise HTTPException(404, "Account not found")
    return {"username": username, "is_active": body.active}
