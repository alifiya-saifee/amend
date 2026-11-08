// One shared app layout for every studio and brand page: sidebar (desktop, collapsible), top bar with a search
// placeholder and a name chip menu (the Inbox count lives in the nav: conversations that need me); bottom tabs + More on mobile.
// Pages that aren't built yet are greyed "soon" (never a link, so never a 404). Icons: Lucide (see app.js).
const NAV = {
  creator: {
    home: "/studio", inbox: "/studio/inbox", unread: "/api/studio/inbox?page=0", search: "/studio/deals",
    items: [
      { key: "home", label: "Home", href: "/studio", icon: "house" },
      { key: "inbox", label: "Inbox", href: "/studio/inbox", icon: "inbox", badge: true },
      { key: "deals", label: "Deals", href: "/studio/deals", icon: "messages-square" },
      { key: "calendar", label: "Calendar", href: "/studio/calendar", icon: "calendar" },
      { key: "earnings", label: "Earnings", href: "/studio/earnings", icon: "wallet" },
      { key: "prices", label: "Price list", href: "/studio/prices", icon: "tag" },
      { key: "profile", label: "Profile & media kit", href: "/studio/profile", icon: "user-round" },
      { key: "brands", label: "Brands", href: "/studio/brands", icon: "building-2" },
      { key: "settings", label: "Settings", href: "/studio/settings", icon: "settings" },
    ],
    mobile: ["home", "inbox", "deals", "earnings"],
    menu: [{ label: "My studio", href: "/studio", icon: "house" }, { label: "Profile", href: "/studio/profile", icon: "user-round" },
           { label: "Settings", href: "/studio/settings", icon: "settings" }],
  },
  brand: {
    home: "/brand", inbox: "/brand/inbox", unread: "/api/brand/inbox", search: "/creators",
    items: [
      { key: "home", label: "Home", href: "/brand", icon: "house" },
      { key: "discover", label: "Discover", href: "/creators", icon: "search" },
      { key: "shortlist", label: "Shortlists", href: "/brand/shortlist", icon: "heart" },
      { key: "deals", label: "Deals", href: "/brand/deals", icon: "messages-square" },
      { key: "inbox", label: "Inbox", href: "/brand/inbox", icon: "inbox", badge: true },
      { key: "payments", label: "Payments", href: "/brand/payments", icon: "credit-card" },
      { key: "team", label: "Team", href: "/brand/team", icon: "users" },
      { key: "settings", label: "Settings", href: "/brand/settings", icon: "settings" },
    ],
    mobile: ["home", "discover", "deals", "inbox"],
    menu: [{ label: "My workspace", href: "/brand", icon: "house" }, { label: "Company profile", href: "/brand/settings", icon: "building-2" },
           { label: "Settings", href: "/brand/settings", icon: "settings" }],
  },
};
const SOON = new Set();  // keys of pages not built yet (greyed, not links)

const Shell = (() => {
  let cfg = null, onNav = null, kind = null;
  const ic = n => `<i data-lucide="${n}" aria-hidden="true"></i>`;

  function linkHtml(it, active) {
  if (SOON.has(it.key)) return `<span class="navitem soon" aria-disabled="true" title="Coming soon">${ic(it.icon)}<span class="lbl">${esc(it.label)}</span><span class="soon-tag">soon</span></span>`;
    return `<a class="navitem ${it.key === active ? "on" : ""}" href="${it.href}" data-nav="${it.key}" ${it.key === active ? 'aria-current="page"' : ""}>${ic(it.icon)}<span class="lbl">${esc(it.label)}</span>${it.badge ? `<span class="badge" data-badge hidden></span>` : ""}</a>`;
  }

  function mount(k, active, { name = "", title = "", onNavigate = null } = {}) {
    kind = k; cfg = NAV[k]; onNav = onNavigate;
    document.body.classList.add("app", "studio");
    try { if (localStorage.getItem("amend.nav.collapsed") === "1") document.body.classList.add("nav-collapsed"); } catch {}
    const top = document.createElement("header");
    top.className = "top apptop";
  top.innerHTML = `<button class="iconbtn collapse" id="nav-collapse" aria-label="Collapse the menu">${ic("panel-left")}</button>
      <a class="logo" href="${cfg.home}"><span class="mark">${ic("repeat-2")}</span>Amend</a><span class="title" id="ttl">${esc(title)}</span>
      <form class="topsearch" id="topsearch" role="search"><label class="sr-only" for="topq">Search</label>${ic("search")}
    <input id="topq" placeholder="${kind === "creator" ? "Search deals and brands" : "Search creators"}"></form>

      <button class="chip-me" id="me" aria-haspopup="menu" aria-expanded="false">${esc(name || "Account")} ${ic("chevron-down")}</button>
      <div class="menu" id="mm" role="menu">
        ${cfg.menu.map(m => `<a role="menuitem" href="${m.href}">${ic(m.icon)} ${esc(m.label)}</a>`).join("")}
        <button role="menuitem" id="mm-out">${ic("log-out")} Sign out</button></div>`;
    const old = document.querySelector("header.top");
    if (old) old.replaceWith(top); else document.body.prepend(top);
    const nav = document.createElement("nav");
  nav.className = "tabs appnav"; nav.setAttribute("aria-label", "Main");
    const mob = cfg.items.filter(i => cfg.mobile.includes(i.key));
    nav.innerHTML = `<div class="side">${cfg.items.map(i => linkHtml(i, active)).join("")}
        <a class="navitem side-out" href="#" id="nav-out">${ic("log-out")}<span class="lbl">Sign out</span></a></div>
      <div class="bottom">${mob.map(i => linkHtml(i, active)).join("")}
    <button class="navitem" id="nav-more" aria-label="More">${ic("ellipsis")}<span class="lbl">More</span></button></div>`;
    const oldNav = document.querySelector("nav.tabs");
    if (oldNav) oldNav.replaceWith(nav); else document.body.appendChild(nav);
    const menu = $("#mm"), me = $("#me");
    me.onclick = e => { e.stopPropagation(); menu.classList.toggle("open"); me.setAttribute("aria-expanded", menu.classList.contains("open")); if (menu.classList.contains("open")) menu.querySelector("a,button").focus(); };
    menu.onkeydown = e => {
      const items = [...menu.querySelectorAll("a,button")]; const i = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      if (e.key === "Escape") { menu.classList.remove("open"); me.focus(); }
    };
    $("#mm-out").onclick = signOut;
    $("#nav-out").onclick = e => { e.preventDefault(); signOut(); };
    $("#nav-collapse").onclick = () => { document.body.classList.toggle("nav-collapsed");
      try { localStorage.setItem("amend.nav.collapsed", document.body.classList.contains("nav-collapsed") ? "1" : "0"); } catch {} };
    $("#topsearch").onsubmit = e => { e.preventDefault(); const q = $("#topq").value.trim(); location.href = cfg.search + (q ? "?q=" + encodeURIComponent(q) : ""); };
    $("#nav-more").onclick = () => sheet(`<h3>More</h3><div class="stack">${cfg.items.filter(i => !cfg.mobile.includes(i.key)).map(i =>
      SOON.has(i.key) ? `<div class="btn block soon" aria-disabled="true">${ic(i.icon)} ${esc(i.label)} · soon</div>`
        : `<a class="btn block" href="${i.href}" data-nav="${i.key}">${ic(i.icon)} ${esc(i.label)}</a>`).join("")}
      <button class="btn danger block" onclick="signOut()">${ic("log-out")} Sign out</button></div>`, { onOpen: sh => bindNav(sh) });
    bindNav(document);
    refreshBadge();
  }

  function bindNav(root) {
    if (!onNav) return;
    $$("a[data-nav]", root).forEach(a => a.onclick = e => {
      if (onNav(a.getAttribute("href"))) { e.preventDefault(); closeSheet(); }
    });
  }
  async function refreshBadge() {
    try { const r = await api(cfg.unread); setBadge(r.needs_threads ?? 0); } catch {}  // conversations that need me, not events
  }
  function setActive(key, title) {
    $$(".appnav a[data-nav]").forEach(a => { a.classList.toggle("on", a.dataset.nav === key); a.toggleAttribute("aria-current", a.dataset.nav === key); });
  if (title !== undefined && $("#ttl")) $("#ttl").textContent = title;
  }
  function setName(name) { const m = $("#me"); if (m) m.innerHTML = `${esc(name)} ${ic("chevron-down")}`; }
 function setBadge(n) { $$("[data-badge]").forEach(b => { b.hidden = !n; b.textContent = n > 99 ? "99+" : n; }); }
  return { mount, setActive, setName, setBadge, refreshBadge };
})();
