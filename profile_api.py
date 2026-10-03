"""Signatory profile: printed name, position, e-signature and (barangays) seal."""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

import signatures
from auth import require_any
from database import get_db_connection

router = APIRouter(prefix="/api/profile", tags=["profile"])

PROFILE_COLUMNS = "profile_name, profile_position, signature_sha, seal_sha, profile_updated_at"


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    profile_name: str = Field(min_length=3, max_length=150)
    profile_position: str = Field(min_length=2, max_length=150)


def load_profile(cur, user_id):
    """Shared by request signing: read a profile through the caller's cursor."""
    cur.execute("SELECT " + PROFILE_COLUMNS + " FROM staff_users WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return row if isinstance(row, dict) else dict(zip(
        ["profile_name", "profile_position", "signature_sha", "seal_sha", "profile_updated_at"], row))


def is_complete(profile):
    return bool(profile and profile.get("profile_name") and profile.get("profile_position")
                and profile.get("signature_sha"))


def _connection():
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(503, "Database unavailable. Please try again.")
    return conn


def _public(profile, user):
    p = profile or {}
    return {"username": user["u"], "role": user["r"], "barangay": user.get("b"),
            "profile_name": p.get("profile_name"), "profile_position": p.get("profile_position"),
            "signature": signatures.data_uri(p.get("signature_sha")),
            "seal": signatures.data_uri(p.get("seal_sha")) if user["r"] == "barangay" else None,
            "complete": is_complete(p)}


@router.get("")
def get_profile(user=Depends(require_any)):
    conn = _connection()
    try:
        cur = conn.cursor(dictionary=True)
        profile = load_profile(cur, user["uid"])
        cur.close()
    finally:
        conn.close()
    return _public(profile, user)


def _update(user, assignments, values):
    conn = _connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("UPDATE staff_users SET " + ", ".join(a + "=%s" for a in assignments) +
                    ", profile_updated_at=%s WHERE user_id=%s",
                    tuple(values) + (datetime.now(), user["uid"]))
        conn.commit()
        profile = load_profile(cur, user["uid"])
        cur.close()
    finally:
        conn.close()
    return _public(profile, user)


@router.post("")
def save_profile(body: ProfileIn, user=Depends(require_any)):
    return _update(user, ["profile_name", "profile_position"],
                   [body.profile_name, body.profile_position])


async def _store(upload, kind):
    data = await upload.read(signatures.MAX_BYTES + 1)
    try:
        return signatures.save_image(data, kind)
    except signatures.ImageRejected as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/signature")
async def upload_signature(file: UploadFile = File(...), attest: bool = Form(False),
                           user=Depends(require_any)):
    if not attest:
        raise HTTPException(422, "Confirm that this is your own signature before uploading.")
    key = await _store(file, "signature")
    return _update(user, ["signature_sha"], [key])


@router.post("/seal")
async def upload_seal(file: UploadFile = File(...), user=Depends(require_any)):
    if user["r"] != "barangay":
        raise HTTPException(403, "Only barangay accounts carry a barangay seal.")
    key = await _store(file, "seal")
    return _update(user, ["seal_sha"], [key])
