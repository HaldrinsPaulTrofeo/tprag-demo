"""Authenticated request intake, decisions, allocation snapshots and letters."""
from contextlib import contextmanager
from datetime import date, datetime
from io import BytesIO
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from auth import require_any, require_staff, require_barangay
from barangays import canonical_barangay, norm_barangay
from database import get_db_connection
from migrate_requests import CATEGORIES, STATUSES
from request_allocation import recommend_requests, PENDING
from profile_api import load_profile, is_complete
import signatures

router = APIRouter(prefix="/api/requests", tags=["requests"])
Category = Literal["ANTI_RABIES", "LIVESTOCK", "SEEDS", "FINGERLINGS", "INPUTS", "OTHER"]
Status = Literal["SUBMITTED", "UNDER_REVIEW", "APPROVED", "PARTIALLY_APPROVED",
                 "DEFERRED", "DECLINED", "FULFILLED"]

class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    barangay: str = Field(min_length=1, max_length=64)
    category: Category = "ANTI_RABIES"
    item: str | None = Field(default=None, max_length=120)
    unit: str = Field(default="vials", min_length=1, max_length=24)
    qty_requested: int = Field(gt=0, le=10000, strict=True)
    animals_estimated: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    households_estimated: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    requested_by: str | None = Field(default=None, max_length=120)
    contact_no: str | None = Field(default=None, max_length=40)
    request_date: date = Field(default_factory=date.today)
    needed_by: date | None = None
    source: Literal["online", "letter"] = "online"

    @field_validator("request_date")
    @classmethod
    def not_future(cls, value):
        if value > date.today():
            raise ValueError("request_date cannot be in the future")
        return value

    @model_validator(mode="after")
    def dates_and_unit(self):
        if self.needed_by and self.needed_by < self.request_date:
            raise ValueError("needed_by cannot precede request_date")
        if self.category == "ANTI_RABIES":
            if self.unit.lower() != "vials":
                raise ValueError("Anti-rabies quantities must be entered in vials")
            self.unit = "vials"
        return self

class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    qty_granted: int = Field(ge=0, le=10000, strict=True)
    status: Status
    decision_note: str | None = Field(default=None, max_length=512)
    session_id: int | None = Field(default=None, gt=0, strict=True)

class AllocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_ids: list[int] = Field(min_length=1, max_length=200)
    vials_available: int = Field(ge=0, le=10000000, strict=True)
    service_level: float = Field(default=0.75, gt=0, lt=1)

    @field_validator("request_ids")
    @classmethod
    def unique_ids(cls, values):
        if any(v < 1 for v in values) or len(set(values)) != len(values):
            raise ValueError("request_ids must be positive, unique, and in priority order")
        return values

@contextmanager
def connection():
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(503, "Database unavailable. Please try again.")
    try:
        yield conn
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        # Do not expose credentials, SQL, contact numbers or schema internals.
        raise HTTPException(503, "Request storage is unavailable; check the migration and database.") from exc
    finally:
        conn.close()

def get_one(cur, request_id, lock=False):
    cur.execute("SELECT * FROM service_requests WHERE request_id=%s" +
                (" FOR UPDATE" if lock else ""), (request_id,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "Request not found")
    return row

def public_row(row, municipal=True):
    row = dict(row)
    snapshot = row.pop("recommendation_json", None)
    row["recommendation"] = json.loads(snapshot) if snapshot else None
    history = row.pop("decision_history_json", None)
    if municipal:
        row["decision_history"] = json.loads(history) if history else []
    else:
        # Other barangays' names/queue context must not leak through a snapshot.
        row["recommendation"] = None
        row.pop("decided_by", None)
    return row

def validate_decision(row, body, override=False):
    old = row["status"]
    fulfill = body.status == "FULFILLED" and old in ("APPROVED", "PARTIALLY_APPROVED")
    if old not in PENDING and not override and not fulfill:
        raise HTTPException(409, "Already decided; an explicit override is required")
    if body.status == "SUBMITTED":
        raise HTTPException(422, "Use UNDER_REVIEW or a decision status")
    if body.qty_granted > row["qty_requested"]:
        raise HTTPException(422, "Granted quantity cannot exceed the requested quantity")
    if body.qty_granted < row["qty_requested"] and not body.decision_note:
        raise HTTPException(422, "A reason is required when granting less than requested")
    if override and not body.decision_note:
        raise HTTPException(422, "An override requires a decision note")
    if body.status == "APPROVED" and body.qty_granted != row["qty_requested"]:
        raise HTTPException(422, "APPROVED requires the full requested quantity")
    if body.status == "PARTIALLY_APPROVED" and not 0 < body.qty_granted < row["qty_requested"]:
        raise HTTPException(422, "PARTIALLY_APPROVED requires a positive partial quantity")
    if body.status in ("DEFERRED", "DECLINED", "UNDER_REVIEW") and body.qty_granted != 0:
        raise HTTPException(422, "This status requires a zero grant")
    if body.status == "FULFILLED":
        if not fulfill:
            raise HTTPException(422, "Approve the request before marking it fulfilled")
        if body.qty_granted != row["qty_granted"]:
            raise HTTPException(422, "Fulfilment cannot change the approved quantity")
        if row["category"] == "ANTI_RABIES" and not body.session_id:
            raise HTTPException(422, "Link the vaccination session to fulfil an anti-rabies request")
    rec = row.get("qty_recommended")
    if rec is not None and body.qty_granted != rec and not body.decision_note:
        raise HTTPException(422, "Explain why the grant differs from the recommendation")

@router.post("", status_code=201)
def submit(body: RequestIn, user=Depends(require_any)):
    try:
        name = canonical_barangay(body.barangay)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if user["r"] == "barangay":
        if name.casefold() != user["b"].casefold():
            raise HTTPException(403, "You can submit only for your assigned barangay")
        if body.source != "online":
            raise HTTPException(403, "Only municipal staff can encode paper letters")
    values = body.model_dump()
    values["barangay"] = name
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        if user["r"] == "barangay":
            # The barangay signs at submission; the snapshot is frozen in the row.
            profile = load_profile(cur, user["uid"])
            if not is_complete(profile):
                raise HTTPException(409, "Complete your profile first: printed name, position and "
                                         "signature (My Account).")
            values.update(requester_name=profile["profile_name"],
                          requester_position=profile["profile_position"],
                          requester_signature=profile["signature_sha"],
                          requester_seal=profile.get("seal_sha"),
                          requester_signed_at=datetime.now())
        fields = list(values)
        cur.execute("INSERT INTO service_requests (" + ",".join(fields) +
                    ",created_at) VALUES (" + ",".join(["%s"] * len(fields)) + ",%s)",
                    tuple(values[f] for f in fields) + (datetime.now(),))
        request_id = cur.lastrowid
        row = get_one(cur, request_id)
        conn.commit()
        cur.close()
    return public_row(row, user["r"] != "barangay")

def list_rows(status=None, barangay=None, category=None, page=1, scoped=False):
    clauses, params = [], []
    for column, value in (("status", status), ("barangay", barangay), ("category", category)):
        if value is not None:
            clauses.append(column + "=%s")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) AS n FROM service_requests" + where, tuple(params))
        count = cur.fetchone()["n"]
        cur.execute("SELECT * FROM service_requests" + where +
                    " ORDER BY request_date ASC,request_id ASC LIMIT %s OFFSET %s",
                    tuple(params) + (20, (page - 1) * 20))
        rows = [public_row(r, not scoped) for r in cur.fetchall()]
        cur.close()
    return {"items": rows, "total": count, "page": page, "page_size": 20}

@router.get("")
def queue(status: Status | None = None, barangay: str | None = None,
          category: Category | None = None, page: int = Query(1, ge=1),
          user=Depends(require_staff)):
    return list_rows(status, barangay, category, page)

@router.get("/mine")
def mine(page: int = Query(1, ge=1), user=Depends(require_barangay)):
    return list_rows(barangay=user["b"], page=page, scoped=True)

@router.get("/summary")
def summary(user=Depends(require_staff)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT status,category,COUNT(*) AS count FROM service_requests "
                    "GROUP BY status,category")
        rows = cur.fetchall()
        cur.execute("SELECT category,unit,COUNT(*) AS requests,SUM(qty_requested) AS requested,"
                    "SUM(CASE WHEN qty_recommended IS NOT NULL THEN qty_requested END) AS assessed_requested,"
                    "SUM(qty_recommended) AS recommended,"
                    "SUM(CASE WHEN status NOT IN ('SUBMITTED','UNDER_REVIEW') THEN qty_requested END) AS decided_requested,"
                    "SUM(CASE WHEN status NOT IN ('SUBMITTED','UNDER_REVIEW') THEN qty_granted END) AS granted "
                    "FROM service_requests GROUP BY category,unit ORDER BY category,unit")
        chain = [chain_row(r) for r in cur.fetchall()]
        cur.close()
    return {"groups": rows, "total": sum(r["count"] for r in rows), "chain": chain}

def chain_row(row):
    """Requested -> recommended -> granted, compared like for like.

    Each ratio uses only the requests that reached that stage, so a request that
    has not been assessed or decided yet cannot make the fill rate look low.
    """
    n = lambda key: int(row[key] or 0)
    assessed, decided = n("assessed_requested"), n("decided_requested")
    return {"category": row["category"], "unit": row["unit"], "requests": n("requests"),
            "requested": n("requested"), "recommended": n("recommended"),
            "granted": n("granted"),
            "assessed_requested": assessed, "decided_requested": decided,
            "recommended_pct_of_assessed": round(100 * n("recommended") / assessed, 1) if assessed else None,
            "granted_pct_of_decided": round(100 * n("granted") / decided, 1) if decided else None}

def calculate_allocation(cur, ids, available, level, lock=False):
    # Fetch locks in a stable order to avoid deadlocks from different priority orders.
    rows = {request_id: get_one(cur, request_id, lock) for request_id in sorted(ids)}
    if any(row["status"] not in PENDING for row in rows.values()):
        raise HTTPException(409, "Allocation accepts only submitted or under-review requests")
    if any(r["category"] == "ANTI_RABIES" for r in rows.values()):
        cur.execute("SELECT barangay,doses_administered FROM vaccination_sessions "
                    "WHERE doses_administered>0")
        sessions = [(r["barangay"], int(r["doses_administered"])) for r in cur.fetchall()]
    else:
        sessions = []
    return recommend_requests([rows[i] for i in ids], sessions, available, level)

@router.post("/allocation")
def save_allocation(body: AllocationIn, user=Depends(require_staff)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        plan = calculate_allocation(cur, body.request_ids, body.vials_available,
                                    body.service_level, lock=True)
        now = datetime.now()
        for result in plan["recommendations"]:
            result["scenario"] = {"priority_order": body.request_ids,
                                  "vials_available": body.vials_available,
                                  "calculated_by": user["u"], "calculated_at": now.isoformat()}
            cur.execute("UPDATE service_requests SET qty_recommended=%s,recommendation_json=%s,"
                        "recommended_at=%s WHERE request_id=%s",
                        (result["recommended"], json.dumps(result), now, result["request_id"]))
        conn.commit()
        cur.close()
    return plan

@router.get("/letter")
def letter(request_ids: str, user=Depends(require_staff)):
    ids = parse_ids(request_ids)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        rows = [get_one(cur, i) for i in ids]
        cur.close()
    if any(r["category"] != "ANTI_RABIES" or r["unit"].lower() != "vials" for r in rows):
        raise HTTPException(422, "The vaccine letter accepts anti-rabies requests in vials only")
    from request_letter import plan_from_requests, write_docx
    lines, total = plan_from_requests(rows)
    output = BytesIO()
    write_docx(lines, total, output, service_level=None)
    output.seek(0)
    return StreamingResponse(output,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="vaccine_request_letter.docx"'})

def parse_ids(text):
    try:
        ids = [int(v.strip()) for v in text.split(",")]
        AllocationIn(request_ids=ids, vials_available=0)
        return ids
    except (ValueError, TypeError):
        raise HTTPException(422, "Provide 1–200 unique positive request IDs, separated by commas")

ACCEPTED = ("APPROVED", "PARTIALLY_APPROVED")


def approval_snapshot(cur, row, status, user, now):
    """Approver signature columns for the new status.

    Accepting signs the document with the deciding officer's current profile.
    Fulfilment keeps the signature already on it. Any other outcome leaves the
    document unsigned by the MAO (declined documents show as cancelled).
    """
    if status == "FULFILLED":
        return (row.get("approver_name"), row.get("approver_position"),
                row.get("approver_signature"), row.get("approver_signed_at"))
    if status not in ACCEPTED:
        return (None, None, None, None)
    profile = load_profile(cur, user["uid"])
    if not is_complete(profile):
        raise HTTPException(409, "Complete your profile (printed name, position and signature in "
                                 "My Account) before approving: approval signs the request document.")
    return (profile["profile_name"], profile["profile_position"], profile["signature_sha"], now)


def _stamp(value):
    # MySQL returns DATE columns as date, DATETIME as datetime; only datetime takes sep/timespec.
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return value.isoformat() if hasattr(value, "isoformat") else value


@router.get("/{request_id}/document")
def document(request_id: int, user=Depends(require_any)):
    """The request as an issued letter, for the requesting barangay and municipal staff."""
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        row = get_one(cur, request_id)
        cur.close()
    if user["r"] == "barangay" and norm_barangay(row["barangay"]) != norm_barangay(user["b"]):
        raise HTTPException(404, "Request not found")
    status = row["status"]
    state = ("cancelled" if status == "DECLINED" else
             "approved" if status in ACCEPTED + ("FULFILLED",) and row.get("approver_signature") else
             "deferred" if status == "DEFERRED" else "pending")
    fields = ("request_id", "barangay", "category", "item", "unit", "qty_requested", "qty_granted",
              "animals_estimated", "households_estimated", "requested_by", "contact_no",
              "request_date", "needed_by", "status", "decision_note", "source", "created_at", "decided_at")
    doc = {k: _stamp(row.get(k)) for k in fields}
    doc.update(
        reference=f"REQ-{str(row['request_date'])[:4]}-{int(row['request_id']):05d}",
        state=state,
        seal=signatures.data_uri(row.get("requester_seal")),
        requester=None if not row.get("requester_signature") else {
            "name": row.get("requester_name"), "position": row.get("requester_position"),
            "signed_at": _stamp(row.get("requester_signed_at")),
            "signature": signatures.data_uri(row.get("requester_signature"))},
        approver=None if state != "approved" else {
            "name": row.get("approver_name"), "position": row.get("approver_position"),
            "signed_at": _stamp(row.get("approver_signed_at")),
            "signature": signatures.data_uri(row.get("approver_signature"))})
    return doc


@router.get("/{request_id}")
def detail(request_id: int, user=Depends(require_staff)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        row = get_one(cur, request_id)
        cur.close()
    return public_row(row)

@router.post("/{request_id}/decide")
def decide(request_id: int, body: DecisionIn, override: bool = False,
           user=Depends(require_staff)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        row = get_one(cur, request_id, lock=True)
        validate_decision(row, body, override)
        if body.session_id is not None:
            if body.status != "FULFILLED" or row["category"] != "ANTI_RABIES":
                raise HTTPException(422, "A session link is only used to fulfil an anti-rabies request")
            cur.execute("SELECT barangay FROM vaccination_sessions WHERE id=%s", (body.session_id,))
            session = cur.fetchone()
            if not session or norm_barangay(session["barangay"]) != norm_barangay(row["barangay"]):
                raise HTTPException(422, "Select an existing vaccination session for this barangay")
        history = json.loads(row.get("decision_history_json") or "[]")
        now = datetime.now()
        approval = approval_snapshot(cur, row, body.status, user, now)
        history.append({"previous_status": row["status"], "previous_grant": row["qty_granted"],
                        "previous_note": row.get("decision_note"),
                        "previous_recommendation": row.get("qty_recommended"),
                        "status": body.status, "qty_granted": body.qty_granted,
                        "note": body.decision_note, "actor": user["u"],
                        "at": now.isoformat(), "override": override})
        cur.execute("UPDATE service_requests SET qty_granted=%s,status=%s,decision_note=%s,"
                    "decided_by=%s,decided_at=%s,session_id=%s,decision_history_json=%s,"
                    "approver_name=%s,approver_position=%s,approver_signature=%s,approver_signed_at=%s "
                    "WHERE request_id=%s",
                    (body.qty_granted, body.status, body.decision_note, user["u"], now,
                     body.session_id, json.dumps(history), *approval, request_id))
        updated = get_one(cur, request_id)
        conn.commit()
        cur.close()
    return public_row(updated)
