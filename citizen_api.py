"""Public pet vaccination check by owner name.

A resident types their full name and barangay and sees their own pets' anti-rabies
status. Because the page is public, it is built so it cannot be used to look people
up casually:
  * the full name must match exactly (word order, case and accents ignored), so a
    surname alone or a partial name finds nothing;
  * the barangay must match as well;
  * only pet name, species, status and dates come back: no contact number, no
    address, no owner record;
  * "not found" reads the same whether or not the person exists;
  * lookups are rate-limited per client address.
"""
import time
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from barangays import canonical_barangay, norm_barangay

router = APIRouter(prefix="/api/citizen", tags=["citizen"])

MAX_LOOKUPS = 10
WINDOW_SECS = 10 * 60
_recent: dict[str, list[float]] = {}


class PetCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str = Field(min_length=3, max_length=150)
    barangay: str = Field(min_length=1, max_length=64)


def name_key(name):
    """'Dela Cruz, Juan' and 'juan  DELA cruz' give the same key."""
    words = norm_barangay(str(name or "").replace(",", " ").replace(".", " ")).split()
    return tuple(sorted(words))


def _throttle(request):
    ip = request.client.host if request.client else ""
    now = time.time()
    hits = [t for t in _recent.get(ip, []) if now - t < WINDOW_SECS]
    if len(hits) >= MAX_LOOKUPS:
        raise HTTPException(429, "Too many checks. Please wait a few minutes and try again.")
    _recent[ip] = hits + [now]


@router.post("/pet-check")
def pet_check(body: PetCheckIn, request: Request):
    _throttle(request)
    key = name_key(body.full_name)
    if len(key) < 2:
        raise HTTPException(422, "Enter your first and last name.")
    try:
        barangay = canonical_barangay(body.barangay)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        from mysql_temporal import get_latest_rabies_vaccinations, RABIES_INTERVAL_DAYS
        pets = get_latest_rabies_vaccinations()
    except Exception as exc:
        raise HTTPException(503, "The registry is unavailable right now. Please try again later.") from exc

    brgy = norm_barangay(barangay)
    found = []
    for p in pets:
        if p.get("is_stray") or norm_barangay(p.get("barangay")) != brgy or name_key(p.get("owner_name")) != key:
            continue
        last = p.get("last_rabies_date")
        due = last + timedelta(days=RABIES_INTERVAL_DAYS) if last else None
        found.append({"pet_name": p.get("pet_name") or "(no name on record)", "species": p.get("species"),
                      "status": p.get("status"),
                      "last_rabies_date": last.isoformat() if last else None,
                      "next_due": due.isoformat() if due else None})
    order = {"OVERDUE": 0, "NEVER_VACCINATED": 1, "PROACTIVE_ALERT_DUE": 2, "UP_TO_DATE": 3}
    found.sort(key=lambda r: (order.get(r["status"], 9), r["pet_name"]))
    return {"barangay": barangay, "pets": found}


@router.get("/barangays")
def barangay_list():
    from barangays import BARANGAYS
    return {"barangays": BARANGAYS}
