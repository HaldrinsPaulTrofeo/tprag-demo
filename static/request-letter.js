// Renders a service request as a barangay request letter. Every value goes in
// through textContent or an attribute, never innerHTML: names and notes are typed by users.
window.RequestLetter = (() => {
  const MONTHS = ["Enero","Pebrero","Marso","Abril","Mayo","Hunyo","Hulyo","Agosto","Setyembre","Oktubre","Nobyembre","Disyembre"];
  const WHAT = {
    ANTI_RABIES: "ANTI-RABIES VACCINE para sa mga alagang aso at pusa",
    LIVESTOCK: "gamot/bitamina para sa mga alagang hayop (livestock)",
    SEEDS: "binhi (seeds)", FINGERLINGS: "fingerlings", INPUTS: "agricultural inputs", OTHER: "tulong"
  };
  const CATEGORY = {ANTI_RABIES:"Anti-rabies vaccine", LIVESTOCK:"Livestock", SEEDS:"Seeds",
    FINGERLINGS:"Fingerlings", INPUTS:"Agricultural inputs", OTHER:"Other"};

  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function filDate(iso) {
    if (!iso) return "";
    const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
    return MONTHS[m - 1] + " " + d + ", " + y;
  }
  function stamp(iso) { return iso ? String(iso).replace("T", " ").slice(0, 19) : ""; }
  function para(cls, parts) {
    const p = el("p", cls);
    for (const part of parts) p.append(typeof part === "string" ? document.createTextNode(part) : part);
    return p;
  }
  const b = text => el("b", null, text);

  function signatureBlock(lead, signer, fallbackName, fallbackPosition, office, waiting) {
    const box = el("div", "sig");
    box.append(el("div", "lead", lead));
    if (signer) {
      box.append(el("div", "sig-stamp", signer.signed_at ? stamp(signer.signed_at) : ""));
      if (signer.signature) { const img = el("img", "sig-img"); img.src = signer.signature; img.alt = "Signature of " + (signer.name || ""); box.append(img); }
      else box.append(el("div", "sig-space"));
      box.append(el("div", "sig-name", signer.name || "—"), el("div", "sig-pos", signer.position || ""));
      if (office) box.append(el("div", "sig-pos", office));
    } else if (waiting) {
      box.append(el("div", "sig-wait", waiting));
    } else {
      box.append(el("div", "sig-stamp", ""), el("div", "sig-space"),
        el("div", "sig-name", fallbackName || "—"), el("div", "sig-pos", fallbackPosition || ""));
      if (office) box.append(el("div", "sig-pos", office));
    }
    return box;
  }

  function render(doc, target, opts = {}) {
    const a = el("article", "ltr" + (opts.preview ? " preview" : ""));
    const brgy = doc.barangay || "______";

    const head = el("header", "ltr-head");
    if (doc.seal) { const s = el("img", "ltr-seal"); s.src = doc.seal; s.alt = "Barangay " + brgy + " seal"; head.append(s); }
    else head.append(el("div", "ltr-seal blank", "Selyo ng Barangay"));
    const mid = el("div");
    for (const line of ["Republika ng Pilipinas", "Lalawigan ng Laguna", "Bayan ng Pagsanjan"]) mid.append(el("div", "gov", line));
    mid.append(el("div", "brgy", "BARANGAY " + brgy.toUpperCase()));
    head.append(mid);
    const town = el("img", "ltr-seal"); town.src = "/static/seal-pagsanjan.png"; town.alt = "Municipality of Pagsanjan seal"; head.append(town);
    a.append(head, el("hr", "ltr-rule"), el("div", "ltr-office", "TANGGAPAN NG PUNONG BARANGAY"));

    const meta = el("div", "ltr-meta");
    meta.append(el("span", "ref", doc.reference ? "Blg. " + doc.reference : "Blg. (ibibigay pag-submit)"), el("span", null, filDate(doc.request_date)));
    a.append(meta, el("h2", null, "KAHILINGAN"));

    const to = el("table", "ltr-to"), tr = el("tr");
    const lines = el("td"); lines.append(b("Ang Municipal Agriculturist / Officer-in-Charge"), el("br"),
      document.createTextNode("Tanggapan ng Pambayang Agrikultura (MAO)"), el("br"), document.createTextNode("Pagsanjan, Laguna"));
    tr.append(el("td", null, "Para kay:"), lines); to.append(tr); a.append(to, el("br"));

    a.append(el("p", null, "Magandang araw po!"));
    const what = WHAT[doc.category] || "tulong";
    const item = doc.item ? " (" + doc.item + ")" : "";
    const qty = (doc.qty_requested ?? "___") + " " + (doc.unit || "");
    const parts = ["Ang Sangguniang Barangay ng ", b(brgy), ", sa pamamagitan ng tanggapang ito, ay magalang na humihiling na mapagkalooban ng ",
      b(what + item), ", ", b(qty.trim())];
    const reach = [];
    if (doc.animals_estimated) reach.push(doc.animals_estimated + " na alagang hayop");
    if (doc.households_estimated) reach.push(doc.households_estimated + " na sambahayan");
    parts.push(reach.length ? ", para sa humigit-kumulang " + reach.join(" mula sa ") + " sa aming barangay." : ", para sa aming mga kabarangay.");
    a.append(para("indent", parts));
    if (doc.needed_by) a.append(para("indent", ["Inaasahan po naming ito ay matanggap bago o sa ", b(filDate(doc.needed_by)), "."]));
    a.append(el("p", "indent", "Umaasa po kami sa inyong positibong tugon sa kahilingang ito. Maraming salamat po."));

    const details = el("table", "ltr-details");
    const rows = [["Kategorya / Category", CATEGORY[doc.category] || doc.category],
      ["Hinihiling / Requested", qty.trim()]];
    if (doc.contact_no) rows.push(["Contact", doc.contact_no]);
    for (const [k, v] of rows) { const r = el("tr"); r.append(el("th", null, k), el("td", null, v)); details.append(r); }
    a.append(details);

    const sigs = el("div", "ltr-sigs");
    const office = "Barangay " + brgy;
    if (doc.requester) sigs.append(signatureBlock("Lubos na gumagalang,", doc.requester, null, null, office));
    else if (doc.source === "letter") sigs.append(signatureBlock("Lubos na gumagalang,", null, null, null, null,
      "Isinumite bilang liham na papel" + (doc.requested_by ? " ni " + doc.requested_by : "") + "; na-encode ng MAO" + (doc.created_at ? " noong " + stamp(doc.created_at) : "") + "."));
    else sigs.append(signatureBlock("Lubos na gumagalang,", null, doc.requested_by || "", "", office));

    const waiting = {pending: "Naghihintay ng pag-apruba ng MAO.\nAwaiting approval.",
      deferred: "Ipinagpaliban: naghihintay ng susunod na supply.\nDeferred to the next supply.",
      cancelled: "Hindi inaprubahan.\nNot approved."}[doc.state];
    sigs.append(signatureBlock("Inaprubahan ni / Approved by:", doc.state === "approved" ? doc.approver : null,
      null, null, "Municipal Agriculture Office, Pagsanjan", doc.state === "approved" ? null : waiting));
    a.append(sigs);

    if (doc.state === "approved") {
      const partial = doc.qty_granted != null && doc.qty_granted < doc.qty_requested;
      const box = el("div", "ltr-decision" + (partial ? " partial" : ""));
      box.append(b((partial ? "Bahagyang inaprubahan / Partly approved: " : "Inaprubahan / Approved: ") +
        doc.qty_granted + " " + doc.unit + (partial ? " sa " + doc.qty_requested + " na hiniling" : "")));
      if (doc.decision_note) box.append(el("br"), document.createTextNode("Puna ng MAO: " + doc.decision_note));
      if (doc.status === "FULFILLED") box.append(el("br"), document.createTextNode("Naipamahagi na / Fulfilled."));
      a.append(box);
    } else if (doc.state === "cancelled") {
      const box = el("div", "ltr-decision cancel");
      box.append(b("KINANSELA / CANCELLED" + (doc.decided_at ? " · " + stamp(doc.decided_at) : "")));
      if (doc.decision_note) box.append(el("br"), document.createTextNode("Dahilan / Reason: " + doc.decision_note));
      a.append(box);
      const wm = el("div", "ltr-watermark", "KINANSELA"); wm.append(el("small", null, "CANCELLED")); a.append(wm);
    } else if (doc.state === "deferred" && doc.decision_note) {
      a.append(para("ltr-decision partial", [b("Ipinagpaliban / Deferred. "), "Puna ng MAO: " + doc.decision_note]));
    }
    if (opts.preview) { const wm = el("div", "ltr-watermark", "PREVIEW"); a.append(wm); }

    a.append(el("div", "ltr-foot", opts.preview
      ? "Preview lamang. Lalagdaan ang liham gamit ang inyong e-signature pag-submit."
      : "Elektronikong nilagdaan sa T-PRAG system ng Municipal Agriculture Office ng Pagsanjan. " +
        "Ang lagda ng MAO at petsa ng pag-apruba ay lumalabas lamang kapag naaprubahan ang kahilingan." +
        (doc.reference ? " Ref. " + doc.reference + "." : "")));
    target.replaceChildren(a);
    return a;
  }
  return {render, filDate};
})();
