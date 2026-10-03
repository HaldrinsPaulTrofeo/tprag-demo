"""Read-only views for a signed-in barangay account.

Everything is scoped to the barangay in the signed session, never to a query
parameter. The overview returns counts only. The follow-up list names owners
and pets so barangay officials can remind residents, under data-minimisation
rules (RA 10173): only the fields needed for follow-up, contact numbers masked
until deliberately revealed, and every list view and reveal written to audit_log.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import require_barangay
from barangays import norm_barangay
from database import get_db_connection

router = APIRouter(prefix="/api/barangay", tags=["barangay portal"])

SERVICE_LEVEL = 0.75
def iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


STATUS_KEYS = {"UP_TO_DATE": "up_to_date", "PROACTIVE_ALERT_DUE": "due_soon",
               "OVERDUE": "overdue", "NEVER_VACCINATED": "never_vaccinated"}


def request_section(barangay):
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT status, COUNT(*) AS n FROM service_requests WHERE barangay=%s "
                    "GROUP BY status", (barangay,))
        by_status = {r["status"]: int(r["n"]) for r in cur.fetchall()}
        cur.execute("SELECT request_id, request_date, category, item, unit, qty_requested, "
                    "qty_granted, status, decision_note, decided_at FROM service_requests "
                    "WHERE barangay=%s ORDER BY request_id DESC LIMIT 8", (barangay,))
        recent = []
        for r in cur.fetchall():
            r = dict(r)
            for key in ("request_date", "decided_at"):
                r[key] = iso(r.get(key))
            recent.append(r)
        cur.close()
    except Exception:
        return None
    finally:
        conn.close()
    pending = by_status.get("SUBMITTED", 0) + by_status.get("UNDER_REVIEW", 0)
    return {"by_status": by_status, "total": sum(by_status.values()),
            "pending": pending, "recent": recent}


def animal_section(barangay):
    try:
        from mysql_temporal import get_latest_rabies_vaccinations
        pets = get_latest_rabies_vaccinations()
    except Exception:
        return None
    key = norm_barangay(barangay)
    out = {"registered": 0, "dogs": 0, "cats": 0, "other": 0,
           "up_to_date": 0, "due_soon": 0, "overdue": 0, "never_vaccinated": 0}
    for pet in pets:
        if norm_barangay(pet.get("barangay")) != key:
            continue
        out["registered"] += 1
        species = (pet.get("species") or "").title()
        out["dogs" if species == "Dog" else "cats" if species == "Cat" else "other"] += 1
        status = STATUS_KEYS.get(pet.get("status"))
        if status:
            out[status] += 1
    out["up_to_date_pct"] = (round(100 * out["up_to_date"] / out["registered"], 1)
                             if out["registered"] else None)
    return out


def session_section(barangay):
    conn = get_db_connection()
    if conn is None:
        return None, []
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT barangay, session_date, doses_administered, vials_used, "
                    "households_served FROM vaccination_sessions")
        rows = cur.fetchall()
        cur.close()
    except Exception:
        return None, []
    finally:
        conn.close()
    key = norm_barangay(barangay)
    all_sessions = [(r["barangay"], int(r["doses_administered"]))
                    for r in rows if r.get("doses_administered") and r["doses_administered"] > 0]
    own = [r for r in rows if norm_barangay(r["barangay"]) == key]
    own.sort(key=lambda r: str(r.get("session_date") or ""), reverse=True)
    recent = [{"session_date": iso(r.get("session_date")),
               "doses_administered": r.get("doses_administered"),
               "vials_used": float(r["vials_used"]) if r.get("vials_used") is not None else None,
               "households_served": r.get("households_served")} for r in own[:10]]
    return {"count": len(own), "total_doses": sum(int(r.get("doses_administered") or 0) for r in own),
            "recent": recent}, all_sessions


def estimate_section(barangay, all_sessions):
    if not all_sessions:
        return None
    from session_forecast import forecast_session, MIN_BARANGAY_SESSIONS
    f = forecast_session(barangay, SERVICE_LEVEL, all_sessions)
    if not f.n_sessions_used:
        return None
    own = f.basis == "barangay"
    return {"recommended_vials": f.recommended_vials, "service_level": SERVICE_LEVEL,
            "basis": f.basis, "n_sessions_used": f.n_sessions_used,
            "n_sessions_barangay": f.n_sessions_barangay, "min_local_sessions": MIN_BARANGAY_SESSIONS,
            "explanation": (
                f"Based on {f.n_sessions_used} past sessions "
                + ("in your barangay" if own else
                   f"across Pagsanjan, because your barangay has {f.n_sessions_barangay} recorded "
                   f"(at least {MIN_BARANGAY_SESSIONS} are needed to use its own history)")
                + f", {f.recommended_vials} vials would have been enough for "
                  f"{int(SERVICE_LEVEL * 100)}% of sessions. The Municipal Agriculture Office "
                  "makes the final allocation, which also depends on vaccine supply.")}


@router.get("/overview")
def overview(user=Depends(require_barangay)):
    barangay = user["b"]
    sessions, all_sessions = session_section(barangay)
    try:
        estimate = estimate_section(barangay, all_sessions)
    except Exception:
        estimate = None
    return {"barangay": barangay, "requests": request_section(barangay),
            "animals": animal_section(barangay), "sessions": sessions, "estimate": estimate}


FOLLOW_UP = {"overdue": "OVERDUE", "due_soon": "PROACTIVE_ALERT_DUE",
             "never": "NEVER_VACCINATED", "vaccinated": "UP_TO_DATE"}
PAGE_SIZE = 20


def _audit(request, user, action, target, details=""):
    try:
        from ocr_api import audit
        audit(user["u"], action, target, details, request.client.host if request.client else "")
    except Exception:
        pass   # auditing must never block the barangay's work


def mask_contact(number):
    digits = "".join(c for c in str(number or "") if c.isdigit())
    if len(digits) < 7:
        return None
    return digits[:4] + " ••• " + digits[-3:]


def _own_pets(barangay):
    from mysql_temporal import get_latest_rabies_vaccinations, RABIES_INTERVAL_DAYS
    key = norm_barangay(barangay)
    try:
        pets = get_latest_rabies_vaccinations()
    except Exception as exc:
        raise HTTPException(503, "Registry records could not be loaded. Please try again.") from exc
    return [p for p in pets if norm_barangay(p.get("barangay")) == key], RABIES_INTERVAL_DAYS


def _row(p, interval, today):
    last = p.get("last_rabies_date")
    due = last + timedelta(days=interval) if last else None
    stray = bool(p.get("is_stray")) or not p.get("owner_name")
    return {"pet_id": p["pet_id"], "pet_name": p.get("pet_name") or "(no name)",
            "species": p.get("species"), "breed": p.get("breed"), "sex": p.get("sex"),
            "owner_name": "Stray / no owner on record" if stray else p["owner_name"],
            "is_stray": stray, "contact_masked": None if stray else mask_contact(p.get("contact_no")),
            "last_rabies_date": iso(last), "next_due": iso(due), "status": p.get("status"),
            "days_overdue": (today - due).days if due and due < today else None}


@router.get("/pets")
def follow_up_list(request: Request, status: str = Query("overdue", pattern="^(overdue|due_soon|never|vaccinated)$"),
                   q: str = Query("", max_length=80), page: int = Query(1, ge=1),
                   user=Depends(require_barangay)):
    pets, interval = _own_pets(user["b"])
    counts = {name: sum(1 for p in pets if p.get("status") == code) for name, code in FOLLOW_UP.items()}
    wanted = [p for p in pets if p.get("status") == FOLLOW_UP[status]]
    needle = q.strip().casefold()
    if needle:
        wanted = [p for p in wanted if needle in (p.get("owner_name") or "").casefold()
                  or needle in (p.get("pet_name") or "").casefold()]
    today = date.today()
    rows = [_row(p, interval, today) for p in wanted]
    # Longest overdue first; for vaccinated pets, the soonest next booster first.
    rows.sort(key=lambda r: (r["next_due"] or "", r["owner_name"]))
    start = (page - 1) * PAGE_SIZE
    _audit(request, user, "BRGY_VIEW_PETS", user["b"], f"status={status} page={page} q={bool(needle)}")
    return {"barangay": user["b"], "status": status, "counts": counts, "total": len(rows),
            "page": page, "page_size": PAGE_SIZE, "items": rows[start:start + PAGE_SIZE]}


@router.post("/pets/{pet_id}/contact")
def reveal_contact(pet_id: str, request: Request, user=Depends(require_barangay)):
    pets, _ = _own_pets(user["b"])
    pet = next((p for p in pets if str(p.get("pet_id")) == pet_id), None)
    if pet is None:
        raise HTTPException(404, "Pet not found in your barangay.")
    if pet.get("is_stray") or not pet.get("contact_no"):
        raise HTTPException(404, "No contact number on record.")
    _audit(request, user, "BRGY_REVEAL_CONTACT", f"pet:{pet_id}", f"barangay={user['b']}")
    return {"pet_id": pet_id, "owner_name": pet.get("owner_name"), "contact_no": pet["contact_no"]}
