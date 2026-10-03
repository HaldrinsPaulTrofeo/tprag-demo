"""Explainable allocation over a caller-supplied priority order.

The three-term minimum is kept separate from the full-session funding decision.
Available stock is a scenario input, not a live inventory balance.
"""
from session_forecast import forecast_session, MIN_BARANGAY_SESSIONS

PENDING = ("SUBMITTED", "UNDER_REVIEW")

def recommend_requests(requests, sessions, vials_available, service_level=0.75):
    if not isinstance(vials_available, int) or isinstance(vials_available, bool) or vials_available < 0:
        raise ValueError("vials_available must be a nonnegative whole number")
    if not 0 < service_level < 1:
        raise ValueError("service_level must be strictly between 0 and 1")
    remaining, funded, unfunded, results = vials_available, [], [], []
    for position, row in enumerate(requests, 1):
        requested = int(row["qty_requested"])
        result = {
            "request_id": row["request_id"], "barangay": row["barangay"],
            "qty_requested": requested, "service_level": service_level,
            "priority": position, "recommended": None, "binding": None,
            "binding_terms": [], "suggested_grant": None, "suggested_status": "UNDER_REVIEW",
            "terms": {"history": {"value": None, "basis": ""},
                      "available": {"value": None, "basis": "Vial supply does not apply to this category/unit"},
                      "requested": {"value": requested}},
        }
        if row["category"] != "ANTI_RABIES" or row["unit"].strip().lower() != "vials":
            result["explanation"] = "No service history for this category/unit; officer review required."
            result["terms"]["history"]["basis"] = result["explanation"]
            results.append(result)
            continue
        forecast = forecast_session(row["barangay"], service_level, sessions)
        result["terms"]["available"] = {
            "value": remaining,
            "basis": f"{remaining} of {vials_available} vials remain after {len(funded)} funded requests",
        }
        if not forecast.n_sessions_used:
            result["explanation"] = "No recorded vaccination sessions; no recommendation can be made."
            result["terms"]["history"]["basis"] = result["explanation"]
            results.append(result)
            continue
        history = forecast.recommended_vials
        basis = (f"{forecast.basis.capitalize()} empirical quantile at {service_level:.0%}; "
                 f"{forecast.n_sessions_used} reference sessions, "
                 f"{forecast.n_sessions_barangay} local sessions "
                 f"({MIN_BARANGAY_SESSIONS} required for a local distribution)")
        result["terms"]["history"] = {"value": history, "basis": basis}
        values = {"history": history, "available": remaining, "requested": requested}
        minimum = min(values.values())
        bindings = [key for key, value in values.items() if value == minimum]
        need = min(history, requested)
        constrained = remaining < need
        result.update(
            recommended=minimum, binding="available" if constrained else bindings[0],
            binding_terms=bindings, suggested_grant=0 if constrained else need,
            suggested_status="DEFERRED" if constrained else
                             ("APPROVED" if need == requested else "PARTIALLY_APPROVED"),
            forecast=forecast.to_dict(),
            explanation=f"Minimum of history ({history}), remaining supply ({remaining}) "
                        f"and requested ({requested}) is {minimum} vials. " +
                        ("Insufficient supply for the full planned session; defer this request "
                         "instead of distributing a smaller quantity. An officer may override with a reason."
                         if constrained else "The full history-supported quantity can be funded.") +
                        (" Municipal history is used because local history is insufficient."
                         if forecast.basis == "municipal" else ""),
        )
        if constrained:
            unfunded.append({"request_id": row["request_id"], "barangay": row["barangay"],
                             "vials_needed": need, "vials_short": need - remaining})
        else:
            remaining -= need
            funded.append({"request_id": row["request_id"], "barangay": row["barangay"],
                           "vials": need})
        results.append(result)
    for result in results:
        result["unfunded_barangays"] = unfunded
    return {"service_level": service_level, "vials_available": vials_available,
            "priority_order": [r["request_id"] for r in requests],
            "recommendations": results, "funded": funded, "unfunded": unfunded,
            "vials_committed": vials_available - remaining, "vials_remaining": remaining,
            "policy": "Full planned sessions in supplied priority order; skip those that cannot be funded",
            "supply_basis": "Officer-entered planning scenario; not a live stock ledger"}
