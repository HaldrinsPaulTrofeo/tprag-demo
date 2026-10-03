"""Download a letter to the Provincial Veterinarian as Word. Staff only.

Printing and PDF are done in the browser from the same preview. Nothing here
sends anything to the province: there is no authorised online channel yet.
"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

import signatures
from auth import require_staff
from barangays import canonical_barangay
from database import get_db_connection
from profile_api import load_profile
from request_letter import build_provincial_docx

router = APIRouter(prefix="/api/provincial-letter", tags=["provincial letter"])


class Row(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    barangay: str = Field(min_length=1, max_length=64)
    session_date: date | None = None
    vials: int = Field(gt=0, le=10000, strict=True)


class LetterIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    template: Literal["schedule", "general"]
    letter_date: date
    addressee_name: str = Field(min_length=3, max_length=150)
    addressee_title: str = Field(min_length=2, max_length=150)
    addressee_office: str = Field(default="", max_length=150)
    subject: str = Field(default="", max_length=200)
    salutation: str = Field(default="", max_length=60)
    body: str = Field(min_length=10, max_length=4000)
    closing: str = Field(default="", max_length=60)
    rows: list[Row] = Field(default_factory=list, max_length=60)
    include_signature: bool = True


@router.post("/docx")
def download_docx(body: LetterIn, user=Depends(require_staff)):
    if body.template == "schedule" and not body.rows:
        raise HTTPException(422, "Add at least one barangay, date and number of vials to the schedule.")
    rows = []
    for row in body.rows:
        try:
            rows.append((canonical_barangay(row.barangay), row.session_date, row.vials))
        except ValueError as exc:
            raise HTTPException(422, f"{row.barangay}: {exc}") from exc

    conn = get_db_connection()
    if conn is None:
        raise HTTPException(503, "Database unavailable. Please try again.")
    try:
        cur = conn.cursor(dictionary=True)
        profile = load_profile(cur, user["uid"]) or {}
        cur.close()
    finally:
        conn.close()
    if not (profile.get("profile_name") and profile.get("profile_position")):
        raise HTTPException(409, "Set your printed name and position in My Account; they sign the letter.")

    signature_path = None
    if body.include_signature and profile.get("signature_sha"):
        candidate = signatures.STORE / f"{profile['signature_sha']}.png"
        signature_path = candidate if candidate.exists() else None

    paragraphs = [p.strip() for p in body.body.replace("\r\n", "\n").split("\n\n") if p.strip()]
    letter = body.model_dump()
    letter.update(rows=rows, paragraphs=paragraphs,
                  signatory_name=profile["profile_name"], signatory_position=profile["profile_position"])
    data = build_provincial_docx(letter, signature_path)
    name = f"provincial_letter_{body.template}_{body.letter_date.isoformat()}.docx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
