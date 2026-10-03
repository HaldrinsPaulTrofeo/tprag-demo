"""Adviser demo: request intake, data-based allocation and the request-to-grant chain.

Runs the real request API, allocation rule and pages against a throwaway SQLite
database filled with SYNTHETIC records. It never reads or writes the project's
MySQL database. Every page carries a "synthetic data" banner.

    python demo/run_demo.py            # serve on http://127.0.0.1:8800/demo
    python demo/run_demo.py --check    # seed, print the scenario, exit (no server)
"""
import argparse
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BASE), str(BASE / "tests")]

import pytest
import auth
import requests_api as api
import session_planner_api
from barangays import BARANGAYS
from test_requests_feature import client as fixture

BANNER = ('<div style="background:#7a4b00;color:#fff;padding:8px 16px;font:600 13px system-ui;'
          'position:sticky;top:0;z-index:99">DEMONSTRATION &mdash; synthetic data in a temporary '
          'database. No real barangay, session or request records are shown. '
          '<a style="color:#ffe9b8" href="/demo">Demo guide</a></div>')

# (barangay, doses administered) per past session. Binan, Sampaloc and Poblacion Uno
# have six or more sessions, so they use their own history; the rest fall back to
# the municipal distribution, which the screen says explicitly.
SESSIONS = {
    "Binan": [60, 75, 90, 80, 110, 95, 85],
    "Sampaloc": [40, 55, 50, 70, 65, 60],
    "Poblacion Uno": [120, 140, 130, 160, 150, 145],
    "Sabang": [30, 45, 40],
    "Layugan": [25, 35],
    "Dingin": [50, 65, 60],
    "Lambac": [35, 40],
}


def days_ago(n):
    return str(date.today() - timedelta(days=n))


def build():
    temp = tempfile.TemporaryDirectory(prefix="capstone-demo-")
    patch = pytest.MonkeyPatch()
    client = fixture.__wrapped__(Path(temp.name), patch)
    names = {n.casefold(): n for n in BARANGAYS}

    def canonical(value):
        found = names.get(value.strip().casefold())
        if found is None:
            raise ValueError("Choose a barangay from the provided list.")
        return found

    patch.setattr(api, "canonical_barangay", canonical)
    session_planner_api.barangay_choices = lambda: {
        "barangays": sorted(BARANGAYS), "canonical": BARANGAYS, "unrecognised": []}

    import sqlite3
    con = sqlite3.connect(client.database_path)
    con.execute("DELETE FROM vaccination_sessions")
    rows, sid = [], 1
    for name, doses in SESSIONS.items():
        for d in doses:
            rows.append((sid, name, d))
            sid += 1
    con.executemany("INSERT INTO vaccination_sessions VALUES (?,?,?)", rows)
    con.commit()
    con.close()
    return temp, patch, client


def seed(client):
    """Create the scenario through the real API so every number comes from the real rules."""
    token = auth.make_session_token({"user_id": 1, "username": "demo-officer",
                                     "role": "staff", "barangay": None})
    client.cookies.set(auth.COOKIE_NAME, token)

    def post(path, body, ok=(200, 201)):
        r = client.post(path, json=body)
        assert r.status_code in ok, (path, r.status_code, r.text)
        return r.json()

    def make(barangay, qty, **kw):
        return post("/api/requests", {"barangay": barangay, "qty_requested": qty, **kw})["request_id"]

    # Earlier requests that the office has already decided: these fill the chain table.
    dingin = make("Dingin", 100, request_date=days_ago(40), requested_by="Punong Barangay (demo)")
    lambac = make("Lambac", 40, request_date=days_ago(38), requested_by="Kagawad (demo)")
    post("/api/requests/allocation", {"request_ids": [dingin, lambac],
                                      "vials_available": 60, "service_level": 0.75})
    d = client.get(f"/api/requests/{dingin}").json()
    post(f"/api/requests/{dingin}/decide", {
        "qty_granted": d["qty_recommended"], "status": "PARTIALLY_APPROVED",
        "decision_note": "Granted the history-supported quantity; remainder deferred to the next release."})
    l = client.get(f"/api/requests/{lambac}").json()
    post(f"/api/requests/{lambac}/decide", {
        "qty_granted": l["qty_recommended"], "status": "PARTIALLY_APPROVED",
        "decision_note": "Granted the history-supported quantity."} if l["qty_recommended"] < 40
        else {"qty_granted": 40, "status": "APPROVED"})

    # Pending anti-rabies requests used for the live allocation step.
    ids = {}
    for name, qty, age in [("Poblacion Uno", 100, 9), ("Binan", 100, 8), ("Sampaloc", 60, 6),
                           ("Sabang", 80, 5), ("Layugan", 40, 3)]:
        ids[name] = make(name, qty, request_date=days_ago(age),
                         animals_estimated=qty * 8, requested_by=f"Punong Barangay of {name} (demo)")
    # One paper letter encoded by staff, and agriculture requests (captured, not recommended).
    make("Anibong", 50, request_date=days_ago(2), source="letter", requested_by="Letter received at the MAO (demo)")
    make("Magdapio", 20, category="SEEDS", unit="bags", item="Rice seed (demo)", request_date=days_ago(4))
    make("Cabanbanan", 500, category="FINGERLINGS", unit="pieces", item="Tilapia fingerlings (demo)", request_date=days_ago(3))
    make("Maulawin", 10, category="LIVESTOCK", unit="heads", item="Cattle deworming (demo)", request_date=days_ago(1))
    client.cookies.clear()
    return ids


def make_app(client):
    from fastapi import Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    app = client.app
    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

    def page(html):
        return HTMLResponse(html.replace("<main", BANNER + "<main", 1))

    @app.get("/api/me")
    def me(request: Request):
        u = auth.require_any(request)
        return {"username": u["u"], "role": u["r"], "barangay": u.get("b")}

    @app.get("/demo/login/{role}")
    def login(role: str, barangay: str = "Binan"):
        staff = role != "barangay"
        resp = RedirectResponse("/" if staff else "/request")
        resp.set_cookie(auth.COOKIE_NAME, auth.make_session_token({
            "user_id": 1, "username": "demo-officer" if staff else "demo-" + barangay.lower(),
            "role": "staff" if staff else "barangay", "barangay": None if staff else barangay}))
        return resp

    @app.get("/request")
    def request_form():
        return page((BASE / "static/request.html").read_text(encoding="utf-8"))

    @app.get("/")
    def queue():
        source = (BASE / "static/dashboard.html").read_text(encoding="utf-8")
        section = source[source.index('<section id="requestsQueue"'):source.index("  <!-- Overdue hero -->")]
        head = source[:source.index("</head>")]
        return HTMLResponse(head + '</head><body data-page="dashboard">' + BANNER +
                            '<main class="wrap">' + section + "</main></body></html>")

    @app.get("/demo")
    def guide():
        return HTMLResponse(f"""<!doctype html><meta charset=utf-8><title>T-PRAG demo</title>{BANNER}
<body style="font:16px/1.6 system-ui;max-width:760px;margin:30px auto;padding:0 18px;color:#223c2e">
<h1>T-PRAG request and allocation demo</h1>
<p>Follow DEMO_SCRIPT.md. Start here:</p><ol>
<li><a href="/demo/login/barangay?barangay=Binan">Sign in as a barangay (Binan)</a> &rarr; submit a request</li>
<li><a href="/demo/login/staff">Sign in as the municipal officer</a> &rarr; queue, allocation, decision, chain</li></ol>
<p>Everything on these pages runs the real application code against synthetic records.</p></body>""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--port", type=int, default=8800)
    args = ap.parse_args()
    temp, patch, client = build()
    try:
        ids = seed(client)
        if args.check:
            token = auth.make_session_token({"user_id": 1, "username": "demo-officer",
                                             "role": "staff", "barangay": None})
            client.cookies.set(auth.COOKIE_NAME, token)
            order = [ids[k] for k in ("Poblacion Uno", "Binan", "Sampaloc", "Sabang", "Layugan")]
            for supply in (200, 35):
                plan = client.post("/api/requests/allocation", json={
                    "request_ids": order, "vials_available": supply, "service_level": 0.75}).json()
                print(f"\nSupply {supply} vials, 75% service level")
                for r in plan["recommendations"]:
                    print(f"  #{r['request_id']:<3} {r['barangay']:<14} asked {r['qty_requested']:>4}  "
                          f"history {r['terms']['history']['value']}  recommended {r['recommended']}  "
                          f"binding {r['binding']}  -> {r['suggested_status']}")
                print("  unfunded:", [u['barangay'] for u in plan["unfunded"]])
            print("\nChain:", [(c["category"], c["requested"], c["recommended"], c["granted"])
                               for c in client.get("/api/requests/summary").json()["chain"]])
            return
        import uvicorn
        make_app(client)
        print(f"\nDemo running: http://127.0.0.1:{args.port}/demo   (Ctrl+C to stop)\n")
        uvicorn.run(client.app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        patch.undo()
        temp.cleanup()


if __name__ == "__main__":
    main()
