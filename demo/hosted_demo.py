"""Public click-through demo of T-PRAG's request, allocation and document features.

Runs the real application modules (request intake, three-term allocation,
signed request documents, barangay portal, provincial letter, citizen pet check)
against a fresh SQLite database of FICTIONAL records. It never connects to MySQL
and contains no real resident, official or signature.

    python demo/hosted_demo.py                 # http://127.0.0.1:7860/demo
    uvicorn demo.hosted_demo:app --port 7860   # same, as a module

Visitors sign in with one click. Password changes and account administration are
switched off so every visitor finds the same sample accounts; "Reset demo data"
restores the starting state.
"""
import io
import math
import os
import random
import re
import sqlite3
import sys
import tempfile
import types
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
STATIC = BASE / "static"
WORK = Path(os.environ.get("DEMO_DIR") or tempfile.mkdtemp(prefix="tprag-demo-"))
DB_PATH = WORK / "demo.sqlite"

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel


# --------------------------------------------------------------------------- database

class Cursor:
    """MySQL-flavoured cursor over SQLite: %s placeholders, dictionary rows."""

    def __init__(self, conn, dictionary=False):
        self.cur, self.dictionary = conn.cursor(), dictionary

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith(("CREATE TABLE", "ALTER TABLE")):
            return self            # schema is created up front
        self.cur.execute(sql.replace("%s", "?").replace(" FOR UPDATE", ""), tuple(params))
        return self

    def _row(self, row):
        if row is None or not self.dictionary:
            return row
        return dict(zip([d[0] for d in self.cur.description], row))

    def fetchone(self):
        return self._row(self.cur.fetchone())

    def fetchall(self):
        return [self._row(r) for r in self.cur.fetchall()]

    @property
    def lastrowid(self):
        return self.cur.lastrowid

    @property
    def rowcount(self):
        return self.cur.rowcount

    def close(self):
        self.cur.close()


class Connection:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, timeout=10, detect_types=0)

    def cursor(self, dictionary=False):
        return Cursor(self.conn, dictionary)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


connect = Connection


def create_schema():
    from migrate_requests import EXPECTED
    defaults = {"status": "TEXT DEFAULT 'SUBMITTED'", "source": "TEXT DEFAULT 'online'",
                "unit": "TEXT DEFAULT 'vials'", "category": "TEXT DEFAULT 'ANTI_RABIES'",
                "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP"}
    ints = {"qty_requested", "qty_recommended", "qty_granted", "animals_estimated",
            "households_estimated", "session_id"}
    cols = ["request_id INTEGER PRIMARY KEY AUTOINCREMENT" if c == "request_id" else
            f"{c} {defaults.get(c) or ('INTEGER' if c in ints else 'TEXT')}" for c in EXPECTED]
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE service_requests (" + ", ".join(cols) + ")")
    con.executescript("""
        CREATE TABLE staff_users (user_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, full_name TEXT,
            pw_hash TEXT, pw_salt TEXT, role TEXT DEFAULT 'staff', barangay TEXT, is_active INTEGER DEFAULT 1,
            must_change_password INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, last_login TEXT,
            profile_name TEXT, profile_position TEXT, signature_sha TEXT, seal_sha TEXT, profile_updated_at TEXT);
        CREATE TABLE vaccination_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, barangay TEXT, session_date TEXT,
            doses_administered INTEGER, vials_used REAL, households_served INTEGER);
        CREATE TABLE audit_log (audit_id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, action TEXT, target TEXT,
            details TEXT, ip_addr TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    con.commit()
    con.close()


# ------------------------------------------------------- stand-ins for heavy modules

REGISTRY: list[dict] = []

_mt = types.ModuleType("mysql_temporal")
_mt.RABIES_INTERVAL_DAYS = 365
_mt.get_latest_rabies_vaccinations = lambda: list(REGISTRY)
sys.modules["mysql_temporal"] = _mt


def _audit(actor, action, target="", details="", ip=""):
    c = connect()
    try:
        c.cursor().execute("INSERT INTO audit_log (actor, action, target, details, ip_addr) VALUES (%s,%s,%s,%s,%s)",
                           (actor, action, target, details[:2000], ip))
        c.commit()
    finally:
        c.close()


_oa = types.ModuleType("ocr_api")
_oa.audit = _audit
sys.modules["ocr_api"] = _oa

import auth                      # noqa: E402  (after the stand-ins above)
import accounts_api              # noqa: E402
import barangay_portal_api       # noqa: E402
import barangays                 # noqa: E402
import citizen_api               # noqa: E402
import database                  # noqa: E402
import profile_api               # noqa: E402
import provincial_letter_api     # noqa: E402
import requests_api              # noqa: E402
import session_forecast          # noqa: E402
import signatures                # noqa: E402

for module in (auth, database, requests_api, profile_api, barangay_portal_api,
               provincial_letter_api, session_forecast):
    module.get_db_connection = connect
barangays.get_db_connection = lambda: None     # canonical barangay list only
auth.ensure_table = lambda: True
signatures.STORE = WORK / "signatures"


# --------------------------------------------------------------------------- app

app = FastAPI(title="T-PRAG public demo", docs_url=None, redoc_url=None)
LOCKED = re.compile(r"^/api/(me/password|accounts)")

# On Hugging Face (SPACE_ID is set) the page is shown inside an iframe on another
# domain, where browsers drop SameSite=Lax cookies. There the session cookie must be
# SameSite=None; Secure; Partitioned, or the one-click sign-in would never stick.
EMBEDDED = bool(os.environ.get("SPACE_ID"))


def set_session(response, user):
    kw = {"max_age": auth.SESSION_MAX_AGE, "httponly": True}
    if EMBEDDED:
        kw.update(samesite="none", secure=True)
        if "partitioned" in Response.set_cookie.__code__.co_varnames:
            kw["partitioned"] = True
    else:
        kw["samesite"] = "lax"
    response.set_cookie(auth.COOKIE_NAME, auth.make_session_token(user), **kw)


@app.middleware("http")
async def demo_rules(request: Request, call_next):
    if request.method != "GET" and LOCKED.match(request.url.path):
        return JSONResponse({"detail": "Switched off in the public demo so every visitor gets the same sample "
                                       "accounts. In the real system this works for administrators."}, 403)
    response = await call_next(request)
    if request.method == "GET" and not request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


for module in (requests_api, profile_api, accounts_api, barangay_portal_api, provincial_letter_api, citizen_api):
    app.include_router(module.router)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

BANNER = ('<div style="background:#7a4b00;color:#fff;padding:8px 16px;font:600 13px/1.5 system-ui,sans-serif;'
          'position:sticky;top:0;z-index:999" class="no-print">PUBLIC DEMO &mdash; every name, signature, pet and request '
          'here is fictional. <a style="color:#ffe9b8" href="/demo">Demo guide and sign-in</a></div>')
HEAD_EXTRA = ('<script>window.PROV_DEFAULTS={name:"DR. SAMPLE PROVINCIAL VETERINARIAN (DEMO)",'
              'title:"Provincial Veterinarian",office:"Province of Laguna"};</script>')
_ASSET = re.compile(r'((?:src|href)="/static/[^"?#]+\.(?:js|css))"')


def page(html):
    html = _ASSET.sub(lambda m: f'{m.group(1)}?v={int((STATIC / m.group(1).split("/static/", 1)[1]).stat().st_mtime)}"', html)
    html = html.replace("</head>", HEAD_EXTRA + "</head>", 1)
    return HTMLResponse(re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + BANNER, html, count=1))


def static_page(name):
    return page((STATIC / name).read_text(encoding="utf-8"))


def guard(request, staff_only=False, barangay_only=False):
    user = auth.current_user(request)
    if user is None:
        return RedirectResponse("/demo", 302)
    if staff_only and user.get("r") == "barangay":
        return RedirectResponse("/barangay", 302)
    if barangay_only and user.get("r") != "barangay":
        return RedirectResponse("/", 302)
    return None


# HEAD as well as GET: hosting health checks (and Gradio's start-up check) probe "/" with HEAD.
@app.api_route("/", methods=["GET", "HEAD"])
def dashboard(request: Request):
    user = auth.current_user(request)
    if user is None:
        # Health checks and first-time visitors get a plain 200 page, not a redirect.
        return guide()
    if (r := guard(request, staff_only=True)):
        return r
    source = (STATIC / "dashboard.html").read_text(encoding="utf-8")
    section = source[source.index('<section id="requestsQueue"'):source.index("  <!-- Overdue hero -->")]
    head = source[:source.index("</head>")]
    note = ('<p class="rq-note" style="max-width:1100px;margin:16px auto 0;padding:0 20px">The full dashboard also has '
            'the overdue list, demand forecast, vial planner and SMS reminders; this demo shows the request and '
            'allocation part.</p>')
    return page(head + '</head><body data-page="dashboard">' + note + '<main class="wrap">' + section + "</main></body></html>")


for path, name, opts in (("/barangay", "barangay.html", {"barangay_only": True}),
                         ("/request", "request.html", {}), ("/account", "account.html", {}),
                         ("/accounts", "accounts.html", {"staff_only": True})):
    def make(name=name, opts=opts):
        def view(request: Request):
            return guard(request, **opts) or static_page(name)
        return view
    app.get(path)(make())


@app.get("/request/{request_id}/document")
def document_page(request_id: int, request: Request):
    return guard(request) or static_page("request-document.html")


@app.get("/citizen")
def citizen():
    return static_page("citizen.html")


@app.get("/login")
def login_page():
    return static_page("login.html")


@app.get("/registry")
@app.get("/verify")
@app.get("/checker")
@app.get("/charter")
def not_in_demo(request: Request):
    return page(f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Not in this demo</title><link rel=stylesheet href="/static/gov.css"><link rel=stylesheet href="/static/requests.css">
<script src="/static/site.js" defer></script></head><body data-page="charter"><main class="wrap" id="main" style="max-width:760px;margin:24px auto;padding:0 20px">
<section class="rq-card"><h1>Not included in the public demo</h1>
<p>The pet registry, vaccination card digitisation (OCR), application checker and Citizen's Charter Q&amp;A are part of the
full system but need the office's database, document AI or language-model services, so they are not part of this demo.</p>
<p><a class="rq-link" href="/demo">Back to the demo guide</a></p></section></main></body></html>""")


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def api_login(body: LoginIn, response: Response):
    user = auth.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(401, "Invalid username or password. Use the one-click sign-in on the demo guide.")
    set_session(response, user)
    return {"ok": True, "redirect": "/barangay" if user["role"] == "barangay" else "/"}


@app.post("/api/logout")
def api_logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def api_me(request: Request):
    user = auth.current_user(request)
    if user is None:
        raise HTTPException(401, "Not logged in")
    return {"username": user["u"], "role": user["r"], "barangay": user.get("b"), "must_change": False}


@app.get("/api/planner/barangays")
def planner_barangays(request: Request):
    auth.require_any(request)
    return {"barangays": barangays.BARANGAYS, "canonical": barangays.BARANGAYS, "unrecognised": []}


@app.get("/demo/login/{username}")
def demo_login(username: str):
    c = connect()
    try:
        cur = c.cursor(dictionary=True)
        cur.execute("SELECT * FROM staff_users WHERE username=%s AND username LIKE 'demo.%%'", (username,))
        user = cur.fetchone()
    finally:
        c.close()
    if not user:
        return RedirectResponse("/demo", 302)
    resp = RedirectResponse("/barangay" if user["role"] == "barangay" else "/", 302)
    set_session(resp, user)
    return resp


@app.post("/demo/reset")
def demo_reset():
    seed()
    resp = RedirectResponse("/demo?reset=1", 303)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


@app.get("/demo")
def guide(reset: int = 0):
    brgy_buttons = "".join(f'<a class="rq-link secondary" href="/demo/login/{username_for(b)}">Barangay {b}</a> '
                           for b in ("Binan", "Sabang", "Lambac", "Cabanbanan", "Anibong"))
    done = '<p class="rq-message rq-success">Demo data was reset to its starting state.</p>' if reset else ""
    return page(f"""<!doctype html><html lang="en"><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>T-PRAG demo guide</title><link rel=stylesheet href="/static/gov.css"><link rel=stylesheet href="/static/requests.css">
<script src="/static/site.js" defer></script><style>.g ol li{{margin:6px 0;line-height:1.6}}.g .rq-link{{display:inline-block;margin:4px 4px 4px 0}}</style>
</head><body data-page="charter"><main class="wrap g" id="main" style="max-width:900px;margin:20px auto;padding:0 20px">
<section class="rq-card"><p class="rq-note">Pagsanjan Municipal Agriculture Office · capstone prototype</p>
<h1>T-PRAG: decision support for anti-rabies vaccine requests</h1>{done}
<p>Barangays request vaccine and other services online. The system recommends how much each barangay should receive
from data: the <b>smallest</b> of what its past sessions needed, what supply remains, and what it asked for. The municipal
officer makes the final decision, and every request becomes a signed document.</p>
<p class="rq-note">Everything here is fictional sample data. Nothing is sent anywhere.</p></section>

<section class="rq-card"><h2>1. See it as a barangay</h2>{brgy_buttons}
<ol><li><b>Home</b> shows the barangay's requests and the office's reasons, a data-based estimate for its next session,
registered-pet status, and a follow-up list of overdue pets (contact numbers masked until revealed, and logged).</li>
<li><b>Service Requests</b>: fill in the form and watch the letter preview build itself, then submit. It is signed with
the barangay's e-signature and timestamp.</li>
<li>Open a request's <b>document</b>: approved ones carry the MAO's signature and approval date; declined ones are
stamped <i>KINANSELA / CANCELLED</i>.</li></ol></section>

<section class="rq-card"><h2>2. See it as the Municipal Agriculture Office</h2>
<a class="rq-link" href="/demo/login/demo.mao">Sign in as the MAO officer</a>
<ol><li>The <b>request queue</b> lists every request (online, paper letter, walk-in) with requested, recommended and granted side by side.</li>
<li>Open <b>Plan an allocation</b>: tick the pending Cabanbanan, Buboy and Magdapio requests, enter <b>60</b> vials and calculate.
Then try <b>20</b> vials: the binding constraint changes from history to supply and a barangay is deferred instead of under-served.</li>
<li><b>Review</b> a request to see all three terms and their basis, then approve, partly approve (a reason is required) or decline.</li>
<li><b>Requests &amp; Letters</b>: prepare the letter to the Provincial Veterinarian and print it or download it as Word.</li>
<li><b>Request to grant chain</b> shows how much was asked for, recommended and granted per category.</li></ol></section>

<section class="rq-card"><h2>3. See it as a resident</h2>
<a class="rq-link secondary" href="/citizen">Check a pet's vaccination</a>
<p>Try the name <b>Juan Dela Cruz</b> with barangay <b>Binan</b>. A partial name finds nothing, by design, and no contact
details are ever shown.</p></section>

<section class="rq-card"><h2>Start over</h2><p>Other visitors may have changed things. This restores the sample data for everyone.</p>
<form method="post" action="/demo/reset"><button type="submit" class="secondary">Reset demo data</button></form></section>
</main></body></html>""")


# --------------------------------------------------------------------------- sample data

OFFICIALS = ["Maria Santos", "Jose Ramos", "Ana Villanueva", "Pedro Bautista", "Liza Mendoza", "Carlo Reyes",
             "Rosa Garcia", "Ramon Aquino", "Elena Cruz", "Mario Flores", "Teresa Navarro", "Andres Torres",
             "Gloria Rivera", "Danilo Castro", "Nora Domingo", "Ruben Salazar"]
FIRST = ["Juan", "Maria", "Jose", "Ana", "Pedro", "Rosa", "Carlo", "Liza", "Ramon", "Elena", "Mario", "Nora",
         "Andres", "Gloria", "Danilo", "Teresa", "Ruben", "Clara", "Miguel", "Lourdes"]
LAST = ["Dela Cruz", "Santos", "Reyes", "Garcia", "Mendoza", "Bautista", "Ramos", "Aquino", "Navarro", "Torres",
        "Castro", "Domingo", "Rivera", "Flores", "Salazar", "Villanueva"]
PETS = ["Bantay", "Muning", "Brownie", "Whitey", "Choco", "Tiger", "Lucky", "Snow", "Bruno", "Mingming", "Coco", "Max"]


def username_for(barangay):
    return "demo." + re.sub(r"[^a-z0-9]+", "-", barangay.lower()).strip("-")


def drawn_signature(seed_value, colour):
    rnd = random.Random(seed_value)
    img = Image.new("RGB", (700, 230), (246, 245, 240))
    d = ImageDraw.Draw(img)
    pts, x = [], 40
    a, f = rnd.uniform(25, 45), rnd.uniform(0.035, 0.06)
    while x < 560:
        pts.append((x, 120 + a * math.sin(x * f) + rnd.uniform(-14, 14)))
        x += 9
    d.line(pts, fill=colour, width=6, joint="curve")
    d.line((pts[3][0] - 10, 170, pts[-1][0] + 30, 150 + rnd.uniform(-12, 12)), fill=colour, width=4)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def drawn_seal(label):
    img = Image.new("RGB", (320, 320), "white")
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 312, 312), outline=(38, 84, 58), width=10)
    d.ellipse((34, 34, 286, 286), outline=(38, 84, 58), width=3)
    d.ellipse((80, 80, 240, 240), fill=(196, 222, 200))
    try:
        font = ImageFont.load_default(size=26)
    except TypeError:
        font = ImageFont.load_default()
    text = label.upper()[:12]
    w = d.textlength(text, font=font)
    d.text(((320 - w) / 2, 145), text, fill=(25, 60, 40), font=font)
    d.text((118, 255), "SAMPLE", fill=(25, 60, 40), font=font)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


SESSION_DOSES = {"Binan": [60, 75, 90, 80, 110, 95, 85], "Sampaloc": [40, 55, 50, 70, 65, 60],
                 "Poblacion Uno": [120, 140, 130, 160, 150, 145], "Sabang": [30, 45, 40], "Layugan": [25, 35],
                 "Dingin": [50, 65, 60], "Lambac": [35, 40, 45], "Cabanbanan": [70, 85, 90, 75, 80, 95],
                 "Buboy": [40, 30, 55], "Magdapio": [20, 35], "Anibong": [15, 25, 20]}


def build_registry(rnd):
    today = date.today()
    rows, n = [], 0
    for b in barangays.BARANGAYS:
        owners = 7 if b != "Binan" else 9
        for i in range(owners):
            name = "Juan Dela Cruz" if (b == "Binan" and i == 0) else f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
            for k in range(2 if i % 3 == 0 else 1):
                n += 1
                pick = rnd.random()
                if b == "Binan" and i == 0:
                    days = 410 if k == 0 else 40
                elif pick < 0.18:
                    days = None
                else:
                    days = rnd.choice([20, 60, 120, 200, 300, 345, 352, 380, 420, 500])
                last = today - timedelta(days=days) if days is not None else None
                status = ("NEVER_VACCINATED" if last is None else "OVERDUE" if days > 365 else
                          "PROACTIVE_ALERT_DUE" if days > 335 else "UP_TO_DATE")
                rows.append({"pet_id": f"D{n:04d}", "barangay": b, "owner_name": name,
                             "contact_no": f"09{rnd.randint(10, 99)}{rnd.randint(1000000, 9999999)}",
                             "pet_name": rnd.choice(PETS), "species": "Dog" if rnd.random() < 0.7 else "Cat",
                             "breed": rnd.choice(["Aspin", "Puspin", "Shih Tzu", "Mixed"]), "sex": rnd.choice("MF"),
                             "is_stray": False, "status": status, "last_rabies_date": last})
        rows.append({"pet_id": f"S{n:04d}", "barangay": b, "owner_name": "", "contact_no": None, "pet_name": "Askal",
                     "species": "Dog", "breed": "Aspin", "sex": "M", "is_stray": True,
                     "status": "NEVER_VACCINATED", "last_rabies_date": None})
    return rows


def seed():
    rnd = random.Random(2026)
    create_schema()
    REGISTRY[:] = build_registry(rnd)
    today = date.today()
    c = connect()
    cur = c.cursor()
    sid = 1
    for b, doses in SESSION_DOSES.items():
        for j, dose in enumerate(doses):
            cur.execute("INSERT INTO vaccination_sessions (id, barangay, session_date, doses_administered, vials_used, "
                        "households_served) VALUES (%s,%s,%s,%s,%s,%s)",
                        (sid, b.upper(), (today - timedelta(days=60 + 45 * j)).isoformat(), dose, -(-dose // 10), dose // 3))
            sid += 1
    c.commit()
    c.close()

    def profile(username, name, position, colour, seal=None):
        c = connect()
        cur = c.cursor()
        cur.execute("UPDATE staff_users SET profile_name=%s, profile_position=%s, signature_sha=%s, seal_sha=%s "
                    "WHERE username=%s", (name, position, signatures.save_image(drawn_signature(username, colour), "signature"),
                                          signatures.save_image(drawn_seal(seal), "seal") if seal else None, username))
        c.commit()
        c.close()

    auth.create_user("demo.mao", "demo-only-2026", full_name="Demo MAO officer", role="admin")
    profile("demo.mao", "Juana R. Mabini (Demo)", "OIC-Municipal Agriculturist", (20, 20, 20))
    for i, b in enumerate(barangays.BARANGAYS):
        u = username_for(b)
        auth.create_user(u, "demo-only-2026", full_name=f"Barangay {b} (demo)", role="barangay", barangay=b)
        profile(u, f"Hon. {OFFICIALS[i]} (Demo)", "Punong Barangay", (25, 45, 140), seal=b)

    client = TestClient(app)

    def as_user(username):
        c = connect()
        cur = c.cursor(dictionary=True)
        cur.execute("SELECT * FROM staff_users WHERE username=%s", (username,))
        user = cur.fetchone()
        c.close()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_token(user))

    def ask(username, barangay, qty, days_ago, **extra):
        as_user(username)
        r = client.post("/api/requests", json={"barangay": barangay, "qty_requested": qty,
                                               "request_date": (today - timedelta(days=days_ago)).isoformat(), **extra})
        assert r.status_code == 201, r.text
        return r.json()["request_id"]

    binan = ask("demo.binan", "Binan", 70, 30, animals_estimated=700, requested_by="Kagawad, Committee on Health")
    lambac = ask("demo.lambac", "Lambac", 40, 28, animals_estimated=150)
    sabang = ask("demo.sabang", "Sabang", 25, 26, item="Anti-rabies vaccine")
    layugan = ask("demo.layugan", "Layugan", 20, 22, category="LIVESTOCK", unit="heads",
                  item="Vitamins and deworming for cattle and carabao")
    ask("demo.cabanbanan", "Cabanbanan", 100, 9, animals_estimated=900,
        needed_by=(today + timedelta(days=20)).isoformat())
    ask("demo.buboy", "Buboy", 30, 7, animals_estimated=150)
    ask("demo.magdapio", "Magdapio", 60, 5)
    ask("demo.sampaloc", "Sampaloc", 15, 3, category="SEEDS", unit="bags", item="Certified rice seed")
    ask("demo.mao", "Anibong", 8, 2, source="letter", requested_by="Kgg. Sample Kagawad (paper letter)")

    as_user("demo.mao")
    plan = client.post("/api/requests/allocation", json={"request_ids": [binan, lambac, sabang],
                                                         "vials_available": 12, "service_level": 0.75})
    assert plan.status_code == 200, plan.text
    recs = {r["request_id"]: r for r in plan.json()["recommendations"]}

    def decide(rid, status, granted, note=None):
        r = client.post(f"/api/requests/{rid}/decide",
                        json={"status": status, "qty_granted": granted, "decision_note": note})
        assert r.status_code == 200, r.text

    decide(binan, "PARTIALLY_APPROVED", recs[binan]["recommended"],
           "Granted what Binan's past sessions needed at a 75% service level; the remainder goes on the next provincial request.")
    decide(lambac, "DEFERRED", 0, "Supply exhausted after Binan; scheduled for the next delivery.")
    decide(sabang, "DEFERRED", 0, "Supply exhausted after Binan; scheduled for the next delivery.")
    decide(layugan, "DECLINED", 0, "Livestock vitamins are not stocked by the MAO this quarter; referred to the Provincial Veterinarian.")


if not os.environ.get("DEMO_SKIP_SEED"):
    seed()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "7860")))
