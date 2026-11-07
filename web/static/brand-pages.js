// Brand workspace pages (Block 6): Home, Deals board/list, Shortlists (named, shared with the team), Payments, Team, Settings.
// Loaded by /brand. Uses helpers from app.js. Every number comes from the API, never typed here.
const bI = (n, cls = "") => `<i data-lucide="${n}" class="${cls}" aria-hidden="true"></i>`;
const bEmpty = (icon, title, text, action = "") => `<div class="empty">${bI(icon)}<h2>${esc(title)}</h2><p>${esc(text)}</p>${action}</div>`;
const B_STAGE = { brief: "Brief", accepted: "Accepted", held: "Held", production: "In production", delivered: "Delivered", paid: "Paid" };
const FIND = `<a class="btn primary" href="/creators">${bI("search")} Find creators</a>`;
const bDay = d => new Date(d + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

/* ---------- Home (S93) ---------- */
async function brandHome() {
  const h = await api("/api/brand/home"), t = h.tiles;
  const goto = (go, text) => go ? `href="${go}"` : `href="/brand/deals" title="${esc(text)}"`;
  $("#view").innerHTML = `
    <div class="row between wrapx" style="gap:12px"><div><h1>Hi ${esc((h.name || "").split(" ")[0])}</h1>
      <p class="muted">${h.needs_count ? `<b>${h.needs_count} thing${h.needs_count === 1 ? "" : "s"} need${h.needs_count === 1 ? "s" : ""} you</b> · ` : "Nothing needs you right now · "}${t.active} active deal${t.active === 1 ? "" : "s"}${h.company ? " · " + esc(h.company) : ""}</p></div>
      ${FIND}</div>
    <div class="grid4" style="margin:16px 0">
      <a class="tile" href="/brand/payments"><span class="k">${bI("lock")} Money held</span><span class="v">${usd(t.held_cents)}</span><span class="aed">${aed(t.held_cents)}</span></a>
      <a class="tile" href="/brand/payments"><span class="k">${bI("wallet")} Paid to creators</span><span class="v">${usd(t.paid_cents)}</span><span class="aed">${aed(t.paid_cents)}</span></a>
      <a class="tile" href="/brand/payments"><span class="k">${bI("undo-2")} Refunded to you</span><span class="v">${usd(t.refunded_cents)}</span><span class="aed">${aed(t.refunded_cents)}</span></a>
      <a class="tile" href="/brand/deals"><span class="k">${bI("messages-square")} Deals</span><span class="v">${t.deals}</span><span class="small muted">${t.active} active</span></a>
    </div>
    <div class="grid2" style="align-items:start">
      <section class="card"><h2>Approvals needed</h2>
        ${h.needs_you.length ? `<div class="list">${h.needs_you.map(n => `<a class="inbox-row" ${goto(n.go, n.text)}>
          <span class="ic">${bI(n.icon)}</span><div class="grow"><b>${esc(n.creator)}</b><div class="small">${esc(n.text)}</div></div>${bI("chevron-right")}</a>`).join("")}</div>`
          : bEmpty("circle-check", "All caught up", "Drafts to check, payments to hold, change cards and drafts to review show up here.")}</section>
      <section class="card"><h2>Upcoming posts</h2>
        ${h.upcoming.length ? `<ul class="events" style="margin-top:8px">${h.upcoming.map(e => `<li><span class="ev post" style="margin:0">Post</span>
          <a class="grow" ${goto(e.go, e.label)} style="color:var(--ink);text-decoration:none">${esc(e.creator)}</a><span class="small muted">${bDay(e.date)}</span></li>`).join("")}</ul>`
          : bEmpty("calendar", "No posts coming up", "Posting dates from your deals appear here.")}</section>
    </div>
    <section style="margin-top:16px"><div class="row between"><h2 style="margin:0">Pipeline</h2><a class="small" href="/brand/deals?view=board">Board</a></div>
      <div class="pipeline" style="margin-top:10px">${h.pipeline.map(p => `<a href="/brand/deals?view=board#${p.key}"><b>${p.count}</b><span>${esc(p.label)}</span></a>`).join("")}</div></section>`;
  $$("#view a[href^='/brand']").forEach(a => a.onclick = e => { e.preventDefault(); go(a.getAttribute("href")); });
}

/* ---------- Deals board / list ---------- */
const BV = { view: new URLSearchParams(location.search).get("view") || "board", q: "" };
async function brandDeals() {
  const r = await api("/api/brand/deals");
  const q = BV.q.toLowerCase();
  const rows = r.deals.filter(d => !q || d.creator.toLowerCase().includes(q) || d.handle.includes(q) || d.id.includes(q));
  $("#view").innerHTML = `<div class="row between wrapx" style="gap:8px"><h1>Deals</h1>
      <div class="seg" role="tablist" style="width:200px"><button data-v="board" class="${BV.view === "board" ? "on" : ""}">${bI("kanban")} Board</button>
        <button data-v="list" class="${BV.view === "list" ? "on" : ""}">${bI("list")} List</button></div></div>
    <input id="b-q" placeholder="Search by creator or deal number" value="${esc(BV.q)}" style="max-width:320px;margin:8px 0 12px">
    <div id="b-body"></div>`;
  const body = $("#b-body");
  const href = d => d.go || "#";
  if (!rows.length) body.innerHTML = bEmpty("messages-square", r.deals.length ? "No deals match" : "No deals yet",
    r.deals.length ? "Try another search." : "Open a deal link a creator sent you while signed in, or request a deal from a creator's page.", r.deals.length ? "" : FIND);
  else if (BV.view === "board") {
    body.innerHTML = `<div class="board">${Object.keys(B_STAGE).map(k => { const c = rows.filter(d => d.stage === k);
      return `<section class="col" id="${k}"><h3><span>${B_STAGE[k]}</span><span>${c.length}</span></h3>${c.map(d => `
        <a class="card dealcard hover" href="${href(d)}"><div class="row between"><b>${esc(d.creator)}</b><span class="tiny muted">@${esc(d.handle)}</span></div>
          <div class="row between" style="margin-top:6px"><span class="num">${usd(d.total_cents)}</span>${moneyPill(d.money)}</div>
          <div class="tiny muted" style="margin-top:6px">${ago(d.updated_at)}</div></a>`).join("")}</section>`; }).join("")}</div>`;
  } else {
    body.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th>Creator</th><th class="n">Value</th><th>Status</th><th>Money</th><th>Post date</th><th>Last activity</th><th></th></tr></thead>
      <tbody>${rows.map(d => `<tr data-go="${href(d)}" style="cursor:pointer"><td><b>${esc(d.creator)}</b> <span class="tiny muted">@${esc(d.handle)}</span></td><td class="n">${usd(d.total_cents)}</td>
        <td>${esc(B_STAGE[d.stage] || DEAL_LABEL[d.status] || d.status)}</td><td>${moneyPill(d.money) || '<span class="muted small">–</span>'}</td><td>${esc(d.deadline || "–")}</td><td>${ago(d.updated_at)}</td>
        <td><a class="btn small" href="/api/brand/deals/${d.id}/receipt.pdf" aria-label="Receipt PDF">${bI("file-down")}</a></td></tr>`).join("")}</tbody></table></div>`;
    $$("tr[data-go]").forEach(tr => tr.onclick = e => { if (!e.target.closest("a")) location.href = tr.dataset.go; });
  }
  $$("[data-v]").forEach(b => b.onclick = () => { BV.view = b.dataset.v; history.replaceState({}, "", "/brand/deals?view=" + BV.view); brandDeals(); });
  let tq; $("#b-q").oninput = e => { clearTimeout(tq); tq = setTimeout(() => { BV.q = e.target.value; brandDeals().then(() => $("#b-q").focus()); }, 250); };
  if (location.hash) { const el = document.getElementById(location.hash.slice(1)); if (el) el.scrollIntoView({ inline: "center", block: "nearest" }); }
}

/* ---------- Shortlists (S94): named lists, shared with the team ---------- */
async function brandShortlists() {
  const [r, hearts] = await Promise.all([api("/api/brand/shortlists"), api("/api/brand/shortlist")]);
  const card = l => `<section class="card"><div class="row between wrapx" style="gap:8px"><div><h2 style="margin:0">${esc(l.name)}</h2>
      <div class="small muted">${l.items.length} creator${l.items.length === 1 ? "" : "s"} · ${l.mine ? (l.shared ? "shared with your team" : "only you") : "shared by " + esc(l.owner)}</div></div>
      <div class="row" style="gap:6px">${l.items.length >= 2 ? `<a class="btn small" href="/creators/compare?ids=${l.items.slice(0, 3).map(i => i.creator_id).join(",")}">${bI("columns-3")} Compare</a>` : ""}
        ${l.mine ? `<button class="btn small" data-share="${l.id}" data-on="${l.shared ? 0 : 1}">${bI(l.shared ? "lock" : "users")} ${l.shared ? "Make private" : "Share with team"}</button>
        <button class="btn small" data-del="${l.id}" aria-label="Delete list">${bI("trash-2")}</button>` : ""}</div></div>
    ${l.items.length ? `<div class="list" style="margin-top:8px">${l.items.map(i => `<div class="inbox-row"><div class="avatar">${initials(i.display_name)}</div>
      <div class="grow"><b>${esc(i.display_name)}</b><div class="small muted">@${esc(i.handle)}${i.note ? " · " + esc(i.note) : ""}</div></div>
      <a class="btn small" href="/c/${esc(i.handle)}">View</a><button class="btn small" data-rm="${l.id}|${i.creator_id}" aria-label="Remove from list">${bI("x")}</button></div>`).join("")}</div>`
      : '<p class="small muted">Add creators from your saved hearts below, or from a creator\'s quick view on Find creators.</p>'}</section>`;
  $("#view").innerHTML = `<div class="row between wrapx" style="gap:8px"><h1>Shortlists</h1>
      <form id="nl" class="row" style="gap:8px"><input name="name" required maxlength="60" placeholder="New list name, e.g. Ramadan coffee" style="width:240px"><button class="btn primary" id="nl-go">${bI("plus")} New list</button></form></div>
    <p class="muted">Lists you share are visible to everyone you add on the Team page.</p>
    ${r.lists.length ? `<div class="stack">${r.lists.map(card).join("")}</div>` : bEmpty("list-plus", "No lists yet", "Make a list for a campaign and share it with your team.")}
    <section class="card" style="margin-top:14px"><h2>Saved with a heart</h2>
      ${hearts.items.length ? `<div class="list">${hearts.items.map(i => `<div class="inbox-row"><div class="avatar">${initials(i.display_name)}</div>
        <div class="grow"><b>${esc(i.display_name)}</b><div class="small muted">@${esc(i.handle)}</div></div>
        ${r.lists.length ? `<select data-add="${i.creator_id}" style="width:auto" aria-label="Add to a list"><option value="">Add to list…</option>${r.lists.map(l => `<option value="${l.id}">${esc(l.name)}</option>`).join("")}</select>` : ""}
        <a class="btn small" href="/c/${esc(i.handle)}">View</a></div>`).join("")}</div>`
        : bEmpty("heart", "Nothing saved yet", "Tap the heart on a creator to save them here.", FIND)}</section>`;
  const call = (b, path, opts) => busy(b, async () => { try { await api(path, opts); brandShortlists(); } catch (e) { toast(e.message, "bad"); } });
  $("#nl").onsubmit = e => { e.preventDefault(); call($("#nl-go"), "/api/brand/shortlists", { body: { name: e.target.name.value, shared: true } }); };
  $$("[data-share]").forEach(b => b.onclick = () => call(b, `/api/brand/shortlists/${b.dataset.share}`, { method: "PUT", body: { shared: b.dataset.on === "1" } }));
  $$("[data-del]").forEach(b => b.onclick = () => { if (confirm("Delete this list? The creators stay saved.")) call(b, `/api/brand/shortlists/${b.dataset.del}`, { method: "DELETE" }); });
  $$("[data-rm]").forEach(b => b.onclick = () => { const [l, c] = b.dataset.rm.split("|"); call(b, `/api/brand/shortlists/${l}/items`, { body: { creator_id: c, on: false } }); });
  $$("[data-add]").forEach(s => s.onchange = async () => { if (!s.value) return;
    try { await api(`/api/brand/shortlists/${s.value}/items`, { body: { creator_id: s.dataset.add, on: true } }); toast("Added to list"); brandShortlists(); } catch (e) { toast(e.message, "bad"); } });
}

/* ---------- Payments ---------- */
async function brandPayments() {
  const r = await api("/api/brand/payments"), t = r.tiles;
  $("#view").innerHTML = `<div class="row between wrapx" style="gap:8px"><h1>Payments</h1>
      <a class="btn" href="/api/brand/payments.csv">${bI("download")} Download CSV</a></div>
    <p class="muted">Every PayPal payment on your deals, with what it was for. PayPal sandbox: no real money.</p>
    <div class="grid4" style="margin:12px 0 16px">
      <div class="tile"><span class="k">${bI("lock")} Held now</span><span class="v">${usd(t.held_cents)}</span><span class="aed">${aed(t.held_cents)}</span></div>
      <div class="tile"><span class="k">${bI("wallet")} Paid to creators</span><span class="v">${usd(t.paid_cents)}</span><span class="aed">${aed(t.paid_cents)}</span></div>
      <div class="tile"><span class="k">${bI("undo-2")} Refunded</span><span class="v">${usd(t.refunded_cents)}</span><span class="aed">${aed(t.refunded_cents)}</span></div>
      <div class="tile"><span class="k">${bI("messages-square")} Deals</span><span class="v">${t.deals}</span></div></div>
    ${r.items.length ? `<div class="table-wrap"><table class="data"><thead><tr><th>Date</th><th>Creator</th><th>What</th><th class="n">Amount</th><th>PayPal ID</th><th>Receipt</th></tr></thead>
      <tbody>${r.items.map(p => `<tr><td>${dateStr(p.at)}</td><td>${esc(p.creator)}</td><td>${esc(p.label)}</td>
        <td class="n">${p.kind === "refund" ? "−" : ""}${usd(p.amount_cents)}<div class="aed">${aed(p.amount_cents)}</div></td>
        <td class="tiny muted">${esc(p.paypal_id || "–")}</td><td><a class="btn small" href="/api/brand/deals/${p.deal}/receipt.pdf" aria-label="Receipt PDF for this deal">${bI("file-down")}</a></td></tr>`).join("")}</tbody></table></div>`
      : bEmpty("credit-card", "No payments yet", "When you pay to hold money on a deal, it shows up here.", FIND)}`;
}

/* ---------- Team: roles and who can confirm changes ---------- */
async function brandTeam() {
  const r = await api("/api/brand/team");
  $("#view").innerHTML = `<h1>Team</h1><p class="muted">People at ${esc(ME.company || "your company")} who review deals and see your shared shortlists.
      "Can confirm" marks who is allowed to confirm changes that move money; everyone else can comment and suggest.</p>
    ${r.items.length ? `<div class="card" style="padding:6px">${r.items.map(t => `<div class="inbox-row"><div class="avatar">${initials(t.name)}</div>
      <div class="grow"><b>${esc(t.name)}</b><div class="small muted">${esc(t.role)}${t.email ? " · " + esc(t.email) : ""}</div></div>
      <label class="row small" style="gap:6px;margin:0"><input type="checkbox" data-cc="${t.id}" ${t.can_confirm ? "checked" : ""} style="width:auto"> Can confirm</label>
      <button class="btn small" data-rm="${t.id}" aria-label="Remove ${esc(t.name)}">${bI("x")}</button></div>`).join("")}</div>`
      : bEmpty("users", "Only you so far", "Add legal or finance so they can review deals and see shared lists.")}
    <form id="tf" class="card" style="margin-top:14px"><h2>Add someone</h2>
      <div class="grid2"><div><label for="tf-n">Name</label><input id="tf-n" name="name" required maxlength="60"></div>
        <div><label for="tf-e">Email (so they see shared lists when they sign in)</label><input id="tf-e" name="email" type="email" maxlength="120"></div></div>
      <label for="tf-r">Role</label><select id="tf-r" name="role"><option>Marketing</option><option>Legal</option><option>Finance</option><option>Other</option></select>
      <label class="row small" style="gap:6px"><input type="checkbox" name="can_confirm" style="width:auto"> Can confirm changes that move money</label>
      <button class="btn primary block" id="ta" style="margin-top:12px">Add</button></form>`;
  $$("[data-rm]").forEach(b => b.onclick = () => busy(b, async () => { await api(`/api/brand/team/${b.dataset.rm}`, { method: "DELETE" }); brandTeam(); }));
  $$("[data-cc]").forEach(c => c.onchange = async () => { try { await api(`/api/brand/team/${c.dataset.cc}`, { method: "PUT", body: { can_confirm: c.checked } }); toast("Saved"); } catch (e) { toast(e.message, "bad"); } });
  $("#tf").onsubmit = e => { e.preventDefault(); busy($("#ta"), async () => { const f = Object.fromEntries(new FormData(e.target));
    f.can_confirm = !!f.can_confirm; if (!f.email) delete f.email;
    try { await api("/api/brand/team", { body: f }); brandTeam(); } catch (er) { toast(er.message, "bad"); } }); };
}

/* ---------- Settings: company profile, theme, sign out ---------- */
async function brandSettings() {
  let theme = "system"; try { theme = localStorage.getItem("amend.theme") || "system"; } catch {}
  $("#view").innerHTML = `<h1>Settings</h1><div class="grid2" style="align-items:start">
    <form id="cf" class="card"><h2>Company profile</h2>
      <label for="cf-c">Company name</label><input id="cf-c" name="company" required maxlength="120" value="${esc(ME.company || "")}">
      <label for="cf-w">Website</label><input id="cf-w" name="website" maxlength="200" value="${esc(ME.website || "")}" placeholder="https://">
      <label for="cf-a">About</label><textarea id="cf-a" name="about" maxlength="600">${esc(ME.about || "")}</textarea>
      <p class="small muted">Creators see this on your deal requests.</p>
      <button class="btn primary block" id="cs">Save</button></form>
    <section class="card"><h2>Account</h2><p class="small">Signed in as <b>${esc(ME.email)}</b></p>
      <label for="bs-theme">Theme</label><select id="bs-theme">${[["system", "Follow my device"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) => `<option value="${v}" ${theme === v ? "selected" : ""}>${l}</option>`).join("")}</select>
      <a class="btn block" style="margin-top:14px" href="/brand/team">${bI("users")} Team members</a>
      <button class="btn danger block" style="margin-top:10px" onclick="signOut()">${bI("log-out")} Sign out</button></section></div>`;
  $("#bs-theme").onchange = e => { applyTheme(e.target.value); toast("Theme saved on this device"); };
  $("#view a[href='/brand/team']").onclick = e => { e.preventDefault(); go("/brand/team"); };
  $("#cf").onsubmit = e => { e.preventDefault(); busy($("#cs"), async () => {
    try { ME = await api("/api/brand/company", { method: "PUT", body: Object.fromEntries(new FormData(e.target)) }); toast("Saved"); } catch (er) { toast(er.message, "bad"); } }); };
}
