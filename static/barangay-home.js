document.addEventListener("DOMContentLoaded", async () => {
  const U = RequestUI, $ = id => document.getElementById(id);
  const LABEL = {SUBMITTED:"Submitted", UNDER_REVIEW:"Under review", APPROVED:"Approved",
    PARTIALLY_APPROVED:"Partly approved", DEFERRED:"Deferred", DECLINED:"Declined", FULFILLED:"Fulfilled"};
  const CATEGORY = {ANTI_RABIES:"Anti-rabies", LIVESTOCK:"Livestock", SEEDS:"Seeds",
    FINGERLINGS:"Fingerlings", INPUTS:"Agricultural inputs", OTHER:"Other"};
  const stat = (value, label, cls) => { const d = U.el("div", null, "bp-stat" + (cls ? " " + cls : ""));
    d.append(U.el("b", value == null ? "—" : String(value)), U.el("span", label)); return d; };
  const unavailable = text => U.el("p", text, "rq-note");

  let data;
  try { data = await U.api("/api/barangay/overview"); }
  catch (e) { U.message("bpMessage", e.message, true); return; }

  $("bpTitle").textContent = "Barangay " + data.barangay;
  document.title = "Barangay " + data.barangay + " | Pagsanjan MAO";

  const r = data.requests;
  $("reqStats").replaceChildren();
  if (!r) { $("reqStats").append(unavailable("Requests could not be loaded right now.")); }
  else {
    const s = r.by_status;
    $("reqStats").append(stat(r.pending, "Waiting for the office", r.pending ? "warn" : ""),
      stat((s.APPROVED || 0) + (s.PARTIALLY_APPROVED || 0), "Approved or partly approved"),
      stat(s.FULFILLED || 0, "Fulfilled"),
      stat(s.DEFERRED || 0, "Deferred to next supply", s.DEFERRED ? "warn" : ""),
      stat(r.total, "All requests"));
    for (const q of r.recent) {
      const tr = U.el("tr");
      tr.append(U.el("td", "#" + q.request_id + " · " + q.request_date),
        U.el("td", (CATEGORY[q.category] || q.category) + (q.item ? " · " + q.item : "")),
        U.el("td", q.qty_requested + " " + q.unit),
        U.el("td", q.qty_granted == null ? "Not yet decided" : q.qty_granted + " " + q.unit));
      const st = U.el("td"); st.append(U.el("span", LABEL[q.status] || q.status, "bp-status " + q.status)); tr.append(st);
      tr.append(U.el("td", q.decision_note || (q.qty_granted == null ? "—" : "No reason recorded")));
      $("reqRows").append(tr);
    }
    if (!r.recent.length) { const tr = U.el("tr"), td = U.el("td", "No requests yet. Use “Submit a new request” to send one to the office."); td.colSpan = 6; tr.append(td); $("reqRows").append(tr); }
  }

  const e = data.estimate, box = $("estimate");
  box.replaceChildren();
  if (!e) box.append(unavailable("There are no recorded sessions yet to base an estimate on."));
  else {
    const big = U.el("div", null, "bp-big"); big.append(String(e.recommended_vials) + " ", U.el("small", "vials"));
    box.append(big, U.el("p", e.explanation, "rq-note"),
      U.el("p", e.basis === "barangay" ? "Basis: your barangay's own history." : "Basis: municipal history (your barangay needs more recorded sessions).", "rq-note"));
  }

  const p = data.animals, pets = $("pets");
  pets.replaceChildren();
  if (!p) pets.append(unavailable("Registry figures could not be loaded right now."));
  else if (!p.registered) pets.append(unavailable("No pets from your barangay are in the municipal registry yet."));
  else {
    const grid = U.el("div", null, "bp-stats");
    grid.append(stat(p.registered, "Registered pets"), stat(p.dogs, "Dogs"), stat(p.cats, "Cats"),
      stat(p.due_soon, "Booster due soon", p.due_soon ? "warn" : ""),
      stat(p.overdue, "Overdue", p.overdue ? "bad" : ""),
      stat(p.never_vaccinated, "No vaccination record", p.never_vaccinated ? "bad" : ""));
    const meter = U.el("div", null, "bp-meter"), fill = U.el("i"); fill.style.width = (p.up_to_date_pct || 0) + "%"; meter.append(fill);
    meter.setAttribute("role", "img"); meter.setAttribute("aria-label", p.up_to_date_pct + "% up to date");
    pets.append(grid, meter, U.el("p", p.up_to_date + " of " + p.registered + " registered pets (" + p.up_to_date_pct +
      "%) are up to date on anti-rabies. This counts registered pets only, not every pet in the barangay.", "rq-note"));
  }

  const ses = data.sessions;
  if (!ses) $("sesSummary").textContent = "Session records could not be loaded right now.";
  else {
    $("sesSummary").textContent = ses.count ? ses.count + " recorded sessions · " + ses.total_doses + " doses given in total. Showing the latest " + ses.recent.length + "." : "No vaccination sessions have been recorded for your barangay yet.";
    for (const x of ses.recent) {
      const tr = U.el("tr");
      for (const v of [x.session_date || "—", x.doses_administered ?? "—", x.vials_used ?? "—", x.households_served ?? "—"]) tr.append(U.el("td", String(v)));
      $("sesRows").append(tr);
    }
  }
});
