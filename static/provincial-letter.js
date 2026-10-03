// Municipal letter to the Provincial Veterinarian: compose, preview, print, download.
document.addEventListener("DOMContentLoaded", async () => {
  const U = RequestUI, $ = id => document.getElementById(id);
  const card = $("provCard");
  if (!card) return;
  let me, profile, barangays = [];
  try { me = await U.api("/api/me"); } catch { return; }
  if (me.role === "barangay") return;           // municipal staff only
  card.hidden = false;
  const encode = document.getElementById("requestCard");
  if (encode) encode.before(card);              // staff mainly come here for the provincial letter

  const TEMPLATES = {
    schedule: {salutation: "Sir,", closing: "",
      body: "Good day! As part of our program in the implementation of Anti-Rabies vaccination of the different barangay in our municipality the following date as schedule;"},
    general: {salutation: "Good day!", closing: "Respectfully yours,", subject: "Request for Anti-Rabies Vaccination",
      body: "May we respectfully request assistance in conducting an Anti-Rabies Vaccination for the dogs and cats in our community. This activity will greatly help ensure the safety and health of our residents and prevent the outbreak spread of rabies infection.\n\n" +
        "We hope that your office can provide vaccines and the necessary personnel to administer the vaccinations. This program will be very beneficial, especially for pet owners who may not have easy access to veterinary services.\n\n" +
        "Thank you very much for your time and assistance."}
  };
  const ADDRESSEE = Object.assign({name: "MICHAEL L. CORTEZ, DVM", title: "Provincial Veterinarian", office: "Province of Laguna"},
    window.PROV_DEFAULTS || {});   // the public demo substitutes a sample addressee
  const store = {get(k) { try { return localStorage.getItem("prov." + k); } catch { return null; } },
                 set(k, v) { try { localStorage.setItem("prov." + k, v); } catch {} }};
  const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  const longDate = iso => { if (!iso) return "____________"; const [y, m, d] = iso.split("-").map(Number); return MONTHS[m - 1] + " " + d + ", " + y; };
  const lineDate = iso => longDate(iso).replace(", ", ",");   // "March 24,2026" as in the office's letters

  function applyTemplate(name) {
    const t = TEMPLATES[name];
    $("provSalutation").value = t.salutation; $("provClosing").value = t.closing; $("provBody").value = t.body;
    $("provSubject").value = t.subject || "";
    $("provSubjectField").hidden = name !== "general"; $("provSchedule").hidden = name !== "schedule";
  }

  function addRow(row = {}) {
    const tr = U.el("tr"), sel = U.el("select"), date = U.el("input"), vials = U.el("input"), del = U.el("button", "Remove", "secondary");
    sel.append(Object.assign(U.el("option", "Choose a barangay"), {value: ""}));
    for (const b of barangays) sel.append(Object.assign(U.el("option", b), {value: b}));
    sel.value = row.barangay || ""; sel.setAttribute("aria-label", "Barangay");
    date.type = "date"; date.value = row.session_date || ""; date.setAttribute("aria-label", "Session date");
    vials.type = "number"; vials.min = 1; vials.max = 10000; vials.step = 1; vials.value = row.vials || ""; vials.setAttribute("aria-label", "Vials");
    del.type = "button"; del.onclick = () => { tr.remove(); render(); };
    for (const x of [sel, date, vials]) { const td = U.el("td"); td.append(x); tr.append(td); x.addEventListener("input", render); }
    const td = U.el("td"); td.append(del); tr.append(td);
    $("provRows").append(tr);
  }

  function rows() {
    return [...$("provRows").querySelectorAll("tr")].map(tr => {
      const [b, d, v] = tr.querySelectorAll("select,input");
      return {barangay: b.value, session_date: d.value || null, vials: v.value === "" ? null : Number(v.value)};
    });
  }

  function letterData() {
    return {template: $("provTemplate").value, letter_date: $("provDate").value,
      addressee_name: $("provName").value.trim(), addressee_title: $("provTitleField").value.trim(),
      addressee_office: $("provOffice").value.trim(), subject: $("provSubject").value.trim(),
      salutation: $("provSalutation").value.trim(), body: $("provBody").value, closing: $("provClosing").value.trim(),
      rows: $("provTemplate").value === "schedule" ? rows() : [], include_signature: $("provSign").checked};
  }

  function render() {
    const L = letterData(), a = U.el("article", null, "ltr prov");
    const head = U.el("header", null, "prov-head");
    const left = U.el("img", null, "ltr-seal"); left.src = "/static/seal-pagsanjan.png"; left.alt = "Municipality of Pagsanjan seal";
    const right = U.el("img", null, "ltr-seal"); right.src = "/static/seal-mao.png"; right.alt = "Municipal Agriculture Office seal";
    const mid = U.el("div");
    for (const t of ["Republic of the Philippines", "Province of Laguna", "Municipality of Pagsanjan", "Office of the Municipal Agriculturist"]) mid.append(U.el("div", t, "gov"));
    head.append(left, mid, right);
    a.append(head, U.el("hr", null, "ltr-rule"), U.el("p", longDate(L.letter_date), "prov-date"));
    const to = U.el("div", null, "to");
    to.append(U.el("b", L.addressee_name || "Addressee"), U.el("div", L.addressee_title), U.el("div", L.addressee_office));
    a.append(to, U.el("br"));
    if (L.template === "general" && L.subject) a.append(U.el("p", "Subject: " + L.subject));
    if (L.salutation) a.append(U.el("p", L.salutation));
    L.body.split(/\n\s*\n/).map(x => x.trim()).filter(Boolean)
      .forEach((p, i) => a.append(U.el("p", p, L.template === "schedule" && i === 0 ? "indent" : null)));
    if (L.template === "schedule") {
      a.append(U.el("br"));
      let total = 0;
      for (const r of L.rows) {
        const line = U.el("div", null, "prov-line");
        line.append(U.el("span", lineDate(r.session_date)), U.el("span", null, "lead"),
          U.el("span", (r.vials ?? "__") + "vials Brgy." + (r.barangay || "________")));
        a.append(line); total += r.vials || 0;
      }
      if (!L.rows.length) a.append(U.el("p", "(Add barangays to the schedule.)", "rq-note"));
      else a.append(U.el("p", "Total: " + total + " vials", "prov-total"));
    }
    const sig = U.el("div", null, "prov-sig");
    if (L.closing) sig.append(U.el("div", L.closing));
    if (L.include_signature && profile && profile.signature) { const img = U.el("img"); img.src = profile.signature; img.alt = "Signature"; sig.append(img); }
    else sig.append(U.el("div", null, "sig-space"));
    sig.append(U.el("div", (profile && profile.profile_name) || "Your printed name", "nm"),
      U.el("div", (profile && profile.profile_position) || "Your position"));
    a.append(sig);
    $("provPreview").replaceChildren(a);
    store.set("name", L.addressee_name); store.set("title", L.addressee_title); store.set("office", L.addressee_office);
  }

  function problems(L) {
    if (!profile || !profile.profile_name || !profile.profile_position) return "Set your printed name and position in My Account first.";
    if (!L.addressee_name || !L.addressee_title) return "Enter the addressee's name and title.";
    if (!L.letter_date) return "Choose the letter date.";
    if (L.template === "schedule") {
      if (!L.rows.length) return "Add at least one barangay to the schedule.";
      const bad = L.rows.findIndex(r => !r.barangay || !r.vials || r.vials < 1);
      if (bad >= 0) return "Schedule row " + (bad + 1) + " needs a barangay and a number of vials.";
    }
    return null;
  }

  async function loadRequests() {
    const list = $("provRequestList"); list.replaceChildren(U.el("p", "Loading.", "rq-note"));
    try {
      const items = [];
      for (let page = 1; page <= 10; page++) {
        const d = await U.api("/api/requests?category=ANTI_RABIES&page=" + page);
        items.push(...d.items); if (page * d.page_size >= d.total) break;
      }
      list.replaceChildren();
      const usable = items.filter(r => r.status !== "DECLINED" && r.unit === "vials");
      if (!usable.length) { list.append(U.el("p", "No anti-rabies requests yet.", "rq-note")); return; }
      for (const r of usable) {
        const label = U.el("label", null, "prov-pick"), box = U.el("input");
        box.type = "checkbox"; box.value = r.request_id; box.dataset.row = JSON.stringify({barangay: r.barangay, session_date: r.needed_by, vials: r.qty_requested});
        label.append(box, " #" + r.request_id + " · " + r.barangay + " · " + r.qty_requested + " vials · " + String(r.status || "submitted").replace("_", " ").toLowerCase() + (r.needed_by ? " · needed by " + r.needed_by : ""));
        list.append(label);
      }
    } catch (e) { list.replaceChildren(U.el("p", e.message, "rq-error")); }
  }

  $("provTemplate").onchange = () => { applyTemplate($("provTemplate").value); render(); };
  for (const id of ["provDate", "provSign", "provName", "provTitleField", "provOffice", "provSubject", "provSalutation", "provClosing", "provBody"])
    $(id).addEventListener("input", render);
  $("provSign").addEventListener("change", render);
  $("provAdd").onclick = () => { addRow(); render(); };
  $("provFromRequests").addEventListener("toggle", () => { if ($("provFromRequests").open) loadRequests(); });
  $("provUseRequests").onclick = () => {
    const picked = [...$("provRequestList").querySelectorAll("input:checked")];
    for (const box of picked) { addRow(JSON.parse(box.dataset.row)); box.checked = false; }
    U.message("provMessage", picked.length ? picked.length + " added. Check the session dates." : "Tick at least one request.", !picked.length);
    render();
  };
  $("provPrint").onclick = () => {
    const issue = problems(letterData());
    if (issue) { U.message("provMessage", issue, true); return; }
    U.message("provMessage", "");
    document.body.classList.add("print-prov"); window.print();
  };
  window.addEventListener("afterprint", () => document.body.classList.remove("print-prov"));
  $("provDocx").onclick = async () => {
    const L = letterData(), issue = problems(L);
    if (issue) { U.message("provMessage", issue, true); return; }
    $("provDocx").disabled = true;
    try {
      const r = await fetch("/api/provincial-letter/docx", U.json(L));
      if (!r.ok) { let d = {}; try { d = await r.json(); } catch {}
        throw Error(typeof d.detail === "string" ? d.detail : Array.isArray(d.detail) ? d.detail.map(e => e.msg).join("\n") : "The letter could not be generated."); }
      const url = URL.createObjectURL(await r.blob()), a = U.el("a");
      a.href = url; a.download = "provincial_letter_" + L.template + "_" + L.letter_date + ".docx"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      U.message("provMessage", "Word file downloaded. Review it before printing and signing.");
    } catch (e) { U.message("provMessage", e.message, true); }
    finally { $("provDocx").disabled = false; }
  };

  const now = new Date();
  $("provDate").value = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("-");
  $("provName").value = store.get("name") || ADDRESSEE.name;
  $("provTitleField").value = store.get("title") || ADDRESSEE.title;
  $("provOffice").value = store.get("office") ?? ADDRESSEE.office;
  applyTemplate("schedule");
  try {
    const [p, b] = await Promise.all([U.api("/api/profile"), U.api("/api/planner/barangays")]);
    profile = p; barangays = b.canonical || b.barangays;
  } catch (e) { U.message("provMessage", e.message, true); }
  if (!profile || !profile.profile_name || !profile.profile_position) {
    const n = $("provProfile"), link = U.el("a", "My Account"); link.href = "/account#profile";
    n.textContent = "Your printed name and position sign this letter. Set them (and optionally your signature) in "; n.append(link, "."); n.hidden = false;
  }
  addRow(); render();
});
