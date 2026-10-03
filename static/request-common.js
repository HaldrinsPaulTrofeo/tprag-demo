// Small shared helpers: textContent prevents request text from becoming HTML.
window.RequestUI = {
  async api(path, options) {
    const response = await fetch(path, options);
    if (response.status === 401) { location.href="/login"; throw Error("Please sign in again."); }
    let data;
    try { data = await response.json(); }
    catch { throw Error(response.ok ? "The server sent an unreadable reply." :
      "The server had a problem (error " + response.status + "). Please try again or contact the MAO."); }
    if (response.status === 403 && /temporary password/i.test(data.detail || "") && location.pathname !== "/account") {
      location.href = "/account?first=1"; throw Error(data.detail);
    }
    if (!response.ok) {
      let detail=data.detail;
      if (Array.isArray(detail)) detail=detail.map(e => e.loc.slice(1).join(".")+": "+e.msg).join("\n");
      throw Error(typeof detail==="string" ? detail : "Unable to complete this request.");
    }
    return data;
  },
  el(tag, text, cls) { const e=document.createElement(tag); if(text!=null)e.textContent=text; if(cls)e.className=cls; return e; },
  message(id, text, error=false) { const e=document.getElementById(id); if(e){e.textContent=text;e.className="rq-message "+(error?"rq-error":"rq-success");} },
  json(data) { return {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)}; }
};
