document.addEventListener("DOMContentLoaded", async () => {
  const U = RequestUI, $ = id => document.getElementById(id);
  const POSITIONS = {
    barangay: ["Punong Barangay", "Kagawad, Committee on Agriculture", "Kagawad, Committee on Health and Sanitation", "Barangay Secretary"],
    staff: ["Municipal Agriculturist", "OIC, Municipal Agriculture Office", "Agricultural Technologist", "Municipal Veterinarian"]
  };
  let profile;

  function preview() {
    const box = $("sigPreview"); box.replaceChildren();
    box.append(U.el("div", "stamp", new Date().toISOString().slice(0, 19).replace("T", " ")));
    if (profile.signature) { const img = U.el("img"); img.src = profile.signature; img.alt = "Your signature"; box.append(img); }
    else box.append(U.el("p", "No signature uploaded yet.", "rq-note"));
    box.append(U.el("div", profile.profile_name || "Your printed name", "nm"), U.el("div", profile.profile_position || "Your position"));
    $("sealPreview").replaceChildren();
    if (profile.seal) { const img = U.el("img"); img.src = profile.seal; img.alt = "Barangay seal"; $("sealPreview").append(img); }
    const missing = [];
    if (!profile.profile_name) missing.push("printed name");
    if (!profile.profile_position) missing.push("position");
    if (!profile.signature) missing.push("signature");
    $("profileMissing").hidden = !missing.length;
    $("profileMissing").textContent = missing.length ? "Still needed before you can " +
      (profile.role === "barangay" ? "submit requests" : "approve requests") + ": " + missing.join(", ") + "." : "";
  }

  async function upload(form, path, messageId, button) {
    const data = new FormData(form);
    if (form.elements.attest) data.set("attest", form.elements.attest.checked ? "true" : "false");
    $(button).disabled = true;
    try { profile = await U.api(path, {method: "POST", body: data}); form.reset(); U.message(messageId, "Saved."); preview(); }
    catch (e) { U.message(messageId, e.message, true); }
    finally { $(button).disabled = false; }
  }

  try { profile = await U.api("/api/profile"); }
  catch (e) { return; }   // e.g. still on a temporary password: change it first
  $("profileCard").hidden = false;
  const role = profile.role === "barangay" ? "barangay" : "staff";
  $("profileRoleNote").textContent = role === "barangay" ? " as Barangay " + profile.barangay : " as the approving MAO officer";
  for (const p of POSITIONS[role]) { const o = U.el("option"); o.value = p; $("positionList").append(o); }
  $("sealBlock").hidden = role !== "barangay";
  const f = $("profileForm");
  f.elements.profile_name.value = profile.profile_name || "";
  f.elements.profile_position.value = profile.profile_position || "";
  preview();
  if (location.hash === "#profile") $("profileCard").scrollIntoView();

  f.addEventListener("submit", async e => {
    e.preventDefault(); $("profileSave").disabled = true;
    try { profile = await U.api("/api/profile", U.json({profile_name: f.elements.profile_name.value, profile_position: f.elements.profile_position.value}));
      U.message("profileMessage", "Saved."); preview(); }
    catch (err) { U.message("profileMessage", err.message, true); }
    finally { $("profileSave").disabled = false; }
  });
  $("sigForm").addEventListener("submit", e => { e.preventDefault(); upload(e.currentTarget, "/api/profile/signature", "sigMessage", "sigSave"); });
  $("sealForm").addEventListener("submit", e => { e.preventDefault(); upload(e.currentTarget, "/api/profile/seal", "sealMessage", "sealSave"); });
});
