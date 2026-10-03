document.addEventListener("DOMContentLoaded", () => {
  const U = RequestUI, $ = id => document.getElementById(id);
  if (!$("followUp")) return;
  const DUE_HEAD = {overdue: "Overdue since", due_soon: "Booster due", never: "Next due", vaccinated: "Next booster due"};
  let status = "overdue", page = 1, timer = null;

  function contactCell(r) {
    const td = U.el("td", null, "bp-contact");
    if (r.is_stray) { td.textContent = "—"; return td; }
    if (!r.contact_masked) { td.textContent = "No number on record"; return td; }
    td.append(r.contact_masked);
    const b = U.el("button", "Show"); b.type = "button";
    b.setAttribute("aria-label", "Show contact number for " + r.owner_name);
    b.onclick = async () => {
      b.disabled = true;
      try { const c = await U.api("/api/barangay/pets/" + encodeURIComponent(r.pet_id) + "/contact", {method: "POST"}); td.textContent = c.contact_no; }
      catch (e) { U.message("fuMessage", e.message, true); b.disabled = false; }
    };
    td.append(b);
    return td;
  }

  async function load() {
    const query = new URLSearchParams({status, page});
    if ($("fuSearch").value.trim()) query.set("q", $("fuSearch").value.trim());
    try {
      const data = await U.api("/api/barangay/pets?" + query);
      for (const tab of document.querySelectorAll(".bp-tabs button")) {
        tab.setAttribute("aria-selected", String(tab.dataset.status === status));
        tab.querySelector("span").textContent = "(" + (data.counts[tab.dataset.status] ?? 0) + ")";
      }
      $("fuDueHead").textContent = DUE_HEAD[status];
      $("fuRows").replaceChildren();
      for (const r of data.items) {
        const tr = U.el("tr");
        tr.append(U.el("td", r.owner_name),
          U.el("td", r.pet_name + " · " + (r.species || "—") + (r.breed ? " (" + r.breed + ")" : "") + (r.sex ? " · " + r.sex : "")),
          U.el("td", r.last_rabies_date || "No record"));
        const due = U.el("td", r.next_due || "As soon as possible", r.days_overdue ? "bp-late" : null);
        if (r.days_overdue) due.textContent = r.next_due + " (" + r.days_overdue + " days)";
        tr.append(due, contactCell(r));
        $("fuRows").append(tr);
      }
      if (!data.items.length) {
        const tr = U.el("tr"), td = U.el("td", $("fuSearch").value.trim() ? "No matches for that name." :
          status === "vaccinated" ? "No registered pets are up to date yet." : "None — no registered pets in this group.");
        td.colSpan = 5; tr.append(td); $("fuRows").append(tr);
      }
      $("fuPage").textContent = "Page " + page + " · " + data.total + " pets";
      $("fuPrev").disabled = page <= 1; $("fuNext").disabled = page * data.page_size >= data.total;
      U.message("fuMessage", "");
    } catch (e) { U.message("fuMessage", e.message, true); }
  }

  for (const tab of document.querySelectorAll(".bp-tabs button"))
    tab.onclick = () => { status = tab.dataset.status; page = 1; load(); };
  $("fuSearch").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { page = 1; load(); }, 300); });
  $("fuPrev").onclick = () => { page--; load(); };
  $("fuNext").onclick = () => { page++; load(); };
  load();
});
