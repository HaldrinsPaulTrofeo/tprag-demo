document.addEventListener("DOMContentLoaded", async () => {
  const U = RequestUI, form = document.getElementById("pwForm");
  try {
    const me = await U.api("/api/me");
    form.elements.username.value = me.username;
    document.getElementById("who").textContent = "Signed in as " + me.username + (me.barangay ? " · Barangay " + me.barangay : "");
    if (me.must_change || new URLSearchParams(location.search).has("first")) document.getElementById("firstNotice").hidden = false;
  } catch (e) { U.message("pwMessage", e.message, true); }

  form.addEventListener("submit", async e => {
    e.preventDefault();
    const b = form.elements;
    if (b.new_password.value !== b.confirm.value) { U.message("pwMessage", "The two new passwords do not match.", true); return; }
    const button = document.getElementById("pwSave"); button.disabled = true;
    try {
      const r = await U.api("/api/me/password", U.json({current_password: b.current_password.value, new_password: b.new_password.value}));
      form.reset();
      U.message("pwMessage", "Password changed. Opening your home page…");
      setTimeout(() => { location.href = r.redirect || "/"; }, 900);
    } catch (err) { U.message("pwMessage", err.message, true); button.disabled = false; }
  });
});
