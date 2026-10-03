document.addEventListener("DOMContentLoaded", () => {
  const U = RequestUI, $ = id => document.getElementById(id), form = $("acForm");
  let me = null;

  function showTemp(r) {
    $("acTempUser").textContent = r.username; $("acTempValue").textContent = r.temporary_password;
    $("acTemp").hidden = false; $("acTemp").scrollIntoView({behavior: "smooth", block: "center"});
  }
  $("acTempHide").onclick = () => { $("acTempValue").textContent = ""; $("acTemp").hidden = true; };

  async function act(path, body, confirmText) {
    if (confirmText && !confirm(confirmText)) return;
    try { const r = await U.api(path, U.json(body || {})); if (r.temporary_password) showTemp(r); else U.message("acMessage", "Saved."); await load(); }
    catch (e) { U.message("acMessage", e.message, true); }
  }

  async function load() {
    try {
      const data = await U.api("/api/accounts");
      $("acRows").replaceChildren();
      for (const a of data.accounts) {
        const tr = U.el("tr", null, a.is_active ? "" : "bp-inactive");
        tr.append(U.el("td", a.username + (a.full_name ? "\n" + a.full_name : "")),
          U.el("td", a.role + (a.barangay ? " · " + a.barangay : "")),
          U.el("td", (a.is_active ? "Active" : "Deactivated") + (a.must_change_password ? " · temporary password" : "")),
          U.el("td", a.last_login || "Never"));
        const td = U.el("td");
        if (me && a.username === me.username) td.append(U.el("span", "You", "rq-badge"));
        else {
          const reset = U.el("button", "Reset password", "secondary"); reset.type = "button";
          reset.onclick = () => act("/api/accounts/" + encodeURIComponent(a.username) + "/reset", null,
            "Reset the password for " + a.username + "? Their current password stops working immediately.");
          const toggle = U.el("button", a.is_active ? "Deactivate" : "Activate", "secondary"); toggle.type = "button";
          toggle.onclick = () => act("/api/accounts/" + encodeURIComponent(a.username) + "/active", {active: !a.is_active},
            a.is_active ? "Deactivate " + a.username + "? They will not be able to sign in." : null);
          td.append(reset, " ", toggle);
        }
        tr.append(td); $("acRows").append(tr);
      }
    } catch (e) { U.message("acMessage", e.message, true); }
  }

  form.elements.role.onchange = () => { $("acBrgyField").hidden = form.elements.role.value !== "barangay"; };
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const b = form.elements, body = {username: b.username.value, full_name: b.full_name.value, role: b.role.value};
    if (body.role === "barangay") body.barangay = b.barangay.value;
    $("acCreate").disabled = true;
    try { showTemp(await U.api("/api/accounts", U.json(body))); form.reset(); $("acBrgyField").hidden = false; await load(); }
    catch (err) { U.message("acMessage", err.message, true); }
    finally { $("acCreate").disabled = false; }
  });
  $("acRefresh").onclick = load;

  Promise.all([U.api("/api/me"), U.api("/api/planner/barangays")]).then(([m, b]) => {
    me = m;
    for (const name of b.canonical || b.barangays) { const o = U.el("option", name); o.value = name; form.elements.barangay.append(o); }
    load();
  }).catch(e => U.message("acMessage", e.message, true));
});
