/* ==========================================================================
   site.js — one navigation and one page frame for the whole portal.

   The five pages each grew their own header with a different link list:
   the charter page offered three destinations, the citizen page two, the
   dashboard six, and the checker page none at all. A citizen who landed on
   the checker had no way back. This builds the same frame everywhere from a
   single list, so adding a page means editing one array.

   USAGE — two lines in each page's <head>:
       <link rel="stylesheet" href="/static/gov.css">
       <script src="/static/site.js" defer></script>
   and one attribute on <body>:
       <body data-page="dashboard">

   Any <header> or <footer> already in the page is removed and replaced, so
   the pages don't need editing beyond those two lines.
   ========================================================================== */

(function () {
  "use strict";

  /* ---- Page registry -----------------------------------------------------
     `service` is the line under the office name. `audience` decides which nav
     the page gets before the session check completes, so a citizen page never
     flashes staff links. */
  var PAGES = {
    barangay: { service: "Barangay Portal", audience: "barangay" },
    request: { service: "Barangay Service Requests", audience: "barangay" },
    account: { service: "My Account", audience: "barangay" },
    accounts: { service: "Account Administration", audience: "staff" },
    dashboard: { service: "Companion Animal Services",       audience: "staff"  },
    registry:  { service: "Pet and Owner Registry",          audience: "staff"  },
    verify:    { service: "Vaccination Card Digitisation",   audience: "staff"  },
    checker:   { service: "Pagsusuri ng Aplikasyon · Application Check", audience: "public" },
    charter:   { service: "Citizen's Charter Q&A",           audience: "public" },
    citizen:   { service: "Pet Vaccination Lookup",          audience: "public" },
    login:     { service: "Sign In",                   audience: "public" }
  };

  /* Names are the ones citizens and staff would use out loud. "Card
     Digitisation" and "Application Checker" sat side by side reading as the
     same feature twice; they are different tools at different moments, so
     they are now named for what each one does. */
  var NAV = {
    barangay: [
      { href: "/barangay", label: "Home", page: "barangay" },
      { href: "/request", label: "Service Requests", page: "request" },
      { href: "/charter", label: "Charter Q&A", page: "charter" },
      { href: "/account", label: "My Account", page: "account" },
      { divider: true },
      { href: "#logout", label: "Log out", page: null, id: "logout" }
    ],
    public: [
      { href: "/charter", label: "Charter Q&A",         page: "charter" },
      { href: "/citizen", label: "Check a Pet",         page: "citizen" },
      { href: "/checker", label: "Application Checker", page: "checker" },
      { divider: true },
      { href: "/login",   label: "Sign In",       page: "login", cls: "signin" }
    ],
    staff: [
      { href: "/request", label: "Requests & Letters", page: "request" },
      { href: "/",        label: "Dashboard",           page: "dashboard" },
      // Records were split off the dashboard so the landing page carries the
      // decision surface -- needs attention, demand forecast, vial planner --
      // while pet and owner records sit one click away. Placed second because
      // it is where staff spend most of their working time.
      { href: "/registry", label: "Pet Registry",       page: "registry" },
      { href: "/verify",  label: "Card Digitisation",   page: "verify" },
      { href: "/checker", label: "Application Checker", page: "checker" },
      { href: "/charter", label: "Charter Q&A",         page: "charter" },
      { href: "/citizen", label: "Check a Pet",         page: "citizen" },
      { href: "/accounts", label: "Accounts",           page: "accounts", admin: true },
      { href: "/account", label: "My Account",          page: "account" },
      { divider: true },
      { href: "#logout",  label: "Log out",             page: null, id: "logout" }
    ]
  };

  var OFFICE = "Municipal Agriculture Office";
  var PLACE = "Pagsanjan, Laguna";

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  function currentPage() {
    var p = document.body.getAttribute("data-page");
    if (p && PAGES[p]) return p;
    // Fall back to the path so a page that forgot the attribute still works.
    var path = location.pathname.replace(/\/+$/, "") || "/";
    if (path === "/") return "dashboard";
    var guess = path.slice(1);
    return PAGES[guess] ? guess : "charter";
  }

  var ROLE = null;

  function buildNav(audience, page) {
    var nav = el("nav", "pmao-nav");
    nav.id = "govNav";
    NAV[audience].forEach(function (item) {
      if (item.admin && ROLE !== "admin") return;
      if (item.divider) { nav.appendChild(el("span", "divider")); return; }
      var a = el("a", item.cls || null, item.label);
      a.href = item.href;
      if (item.id) a.id = item.id;
      if (item.page && item.page === page) a.setAttribute("aria-current", "page");
      nav.appendChild(a);
    });
    return nav;
  }

  function buildChrome(audience) {
    var page = currentPage();
    var meta = PAGES[page] || PAGES.charter;
    var frag = document.createDocumentFragment();

    frag.appendChild((function () {
      var a = el("a", "pmao-skip", "Skip to main content");
      a.href = "#main";
      return a;
    })());

    var mast = el("header", "pmao-masthead");
    mast.appendChild(el("div", "in",
      '<span class="flag" aria-hidden="true"></span>' +
      "<b>Republic of the Philippines</b>" +
      '<span class="sep">·</span>' +
      "<span>All content is in the public domain unless otherwise stated</span>"
    ));
    frag.appendChild(mast);

    var head = el("header", "pmao-header");
    var inner = el("div", "in");

    var seals = el("div", "pmao-seals");
    seals.innerHTML =
      '<img src="/static/seal-mao.png" alt="Pagsanjan Municipal Agriculture Office (FITS Center) seal">' +
      '<img src="/static/seal-pagsanjan.png" alt="Municipality of Pagsanjan seal">';
    inner.appendChild(seals);

    var brand = el("div", "pmao-brand");
    brand.innerHTML =
      '<div class="office">' + OFFICE + "</div>" +
      '<div class="service">' +
        "<span>" + meta.service + " · " + PLACE + "</span>" +
        (audience === "staff" ? '<span class="pmao-chip">Staff view</span>' : "") +
      "</div>";
    inner.appendChild(brand);

    var toggle = el("button", "pmao-navtoggle", "Menu");
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", "govNav");
    inner.appendChild(toggle);

    var nav = buildNav(audience, page);
    inner.appendChild(nav);

    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    head.appendChild(inner);
    frag.appendChild(head);

    var rule = el("div", "pmao-rule");
    rule.setAttribute("aria-hidden", "true");
    rule.innerHTML = "<i></i><i></i><i></i>";
    frag.appendChild(rule);

    return frag;
  }

  function buildFooter() {
    var f = el("footer", "pmao-footer");
    f.innerHTML =
      '<div class="in">' +
        '<div><div class="ftitle">' + OFFICE + "</div>" +
          '<div class="fline">FITS Center — ' + PLACE + "</div>" +
          '<div class="fline">pagsanjanagricultureoffice@gmail.com</div>' +
          '<div class="fline">(0928) 912 3302 · (049) 539-3171</div></div>' +
        '<div><div class="ftitle">About this site</div>' +
          '<a href="#accessibility">Accessibility Statement</a>' +
          '<a href="#transparency">Transparency Seal</a>' +
          '<a href="#privacy">Privacy Notice</a>' +
          '<a href="#foi">Freedom of Information</a></div>' +
        '<div><div class="ftitle">Government Links</div>' +
          '<a href="https://www.da.gov.ph" target="_blank" rel="noopener">Department of Agriculture</a>' +
          '<a href="https://ati.da.gov.ph" target="_blank" rel="noopener">Agricultural Training Institute</a>' +
          '<a href="https://www.gov.ph" target="_blank" rel="noopener">GOV.PH Portal</a></div>' +
      "</div>" +
      '<div class="fbar">' +
        "<span>© " + new Date().getFullYear() + " " + OFFICE +
        " of Pagsanjan. All content is in the public domain unless otherwise stated.</span>" +
        "<span>Republic of the Philippines</span>" +
      "</div>";
    return f;
  }

  /* The five pages each named their chrome differently: charter and login use
     .gov-strip / .banner / .tricolor, dashboard and citizen use header.topbar,
     and checker uses a bare <header>. All of them are listed explicitly —
     matching on element type alone missed the div-based ones and left the
     charter page with two stacked headers. */
  var LEGACY_CHROME = [
    ".gov-strip",       // charter, login — national masthead
    ".banner",          // charter, login — seals and office name
    ".tricolor",        // charter, login — flag rule
    "header.topbar",    // dashboard, citizen
    "body > header",    // checker
    "body > footer"     // charter, login
  ].join(", ");

  function stripOldChrome() {
    Array.prototype.forEach.call(
      document.querySelectorAll(LEGACY_CHROME),
      function (n) { if (!/^pmao-/.test(n.className || "")) n.remove(); }
    );
    // Anything pmao-* is ours from a previous render; clear it so re-running
    // after the session check doesn't stack a second frame.
    Array.prototype.forEach.call(
      document.querySelectorAll(".pmao-masthead, .pmao-header, .pmao-rule, .pmao-footer, .pmao-skip"),
      function (n) { n.remove(); }
    );
  }

  function wireLogout() {
    var btn = document.getElementById("logout");
    if (!btn) return;
    // Bound here rather than left to each page: site.js replaces the header
    // after the page's own inline script has run, so a handler attached to the
    // old link would be discarded with it.
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      fetch("/api/logout", { method: "POST" })
        .catch(function () { /* sign out locally regardless */ })
        .then(function () { location.href = "/login"; });
    });
  }

  function markMain() {
    if (document.getElementById("main")) return;
    var target = document.querySelector(".wrap, .page, main") ||
                 document.querySelector("body > div");
    if (target) target.id = "main";
  }

  function render(audience) {
    stripOldChrome();
    document.body.insertBefore(buildChrome(audience), document.body.firstChild);
    document.body.appendChild(buildFooter());
    wireLogout();
    markMain();
  }

  function start() {
    var page = currentPage();
    var declared = (PAGES[page] || {}).audience || "public";

    // Draw immediately with the page's declared audience so nothing flashes,
    // then confirm against the session. A citizen browsing /charter and a
    // logged-in clerk browsing /charter need different links.
    render(declared);

    fetch("/api/me", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json().then(function (u) { ROLE = u.role; return u.role === "barangay" ? "barangay" : "staff"; }) : "public"; })
      .catch(function () { return declared; })
      .then(function (actual) {
        if (actual !== declared || ROLE === "admin") render(actual);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
