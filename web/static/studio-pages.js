// Studio pages (Block 4–5): Home, Inbox (split), Deals (board / list), Earnings, Calendar, Brands, Settings.
// Every number comes from the API (real tables). Used by studio.html's router.
const I = (n, cls = "") => `<i data-lucide="${n}" class="${cls}" aria-hidden="true"></i>`;
const STAGE_LABEL = { brief: "Brief", accepted: "Accepted", held: "Held", production: "In production", delivered: "Delivered", paid: "Paid" };
const EV_LABEL = { draft: "Draft due", post: "Posting date", product: "Product", review: "Brand review due", holdback: "Holdback release", expiry: "Hold expires" };
const fmtDay = fmtDate;  // one formatter (app.js)
function emptyState(icon, title, text, action = "") { return `<div class="empty">${I(icon)}<h2>${esc(title)}</h2><p>${esc(text)}</p>${action}</div>`; }
function errorState(e, retry) { return `<div class="empty">${I("triangle-alert")}<h2>Something went wrong</h2><p>${esc(e.message)}</p><button class="btn" onclick="${retry}">${I("rotate-cw")} Try again</button></div>`; }

/* ---------- Home ---------- */
async function homeTab() {
  const h = await api("/api/studio/home");
  const t = h.tiles;
  const first = h.name.split(" ")[0];
  const setupDone = h.setup.done === h.setup.total;
  $("#view").innerHTML = `
    <div class="row between wrapx" style="gap:12px"><div><h1>Hi ${esc(first)}</h1>
      <p class="muted">${h.needs_count ? `<b>${h.needs_count} thing${h.needs_count === 1 ? "" : "s"} need${h.needs_count === 1 ? "s" : ""} you</b> · ` : "Nothing needs you right now · "}${h.active} active deal${h.active === 1 ? "" : "s"}</p></div>
      <button class="btn primary" id="h-new">${I("plus")} New deal link</button></div>
    ${!setupDone ? `<div class="card" style="margin:16px 0"><div class="row between"><h2 style="margin:0">Get set up</h2><span class="small muted">${h.setup.done} of ${h.setup.total}</span></div>
      <div class="progress" style="margin:10px 0"><span style="width:${100 * h.setup.done / h.setup.total}%"></span></div>
      <ul class="checklist">${h.setup.steps.map(s => `<li class="${s.done ? "done" : ""}">${I(s.done ? "circle-check" : "circle")}<a href="${s.href}" class="grow" style="color:inherit">${esc(s.label)}</a></li>`).join("")}</ul></div>` : ""}
    <div class="grid4" style="margin:16px 0">
      <a class="tile" href="/studio/deals"><span class="k">${I("lock")} Held for you</span><span class="v">${usd(t.held_cents)}</span><span class="aed">${aed(t.held_cents)}</span></a>
      <a class="tile" href="/studio/earnings"><span class="k">${I("hourglass")} To be released</span><span class="v">${usd(t.to_release_cents)}</span><span class="aed">${aed(t.to_release_cents)}</span></a>
      <a class="tile" href="/studio/earnings"><span class="k">${I("wallet")} Paid out this month</span><span class="v">${usd(t.paid_month_cents)}</span><span class="aed">${aed(t.paid_month_cents)}</span></a>
      <a class="tile hero" href="/studio/earnings"><span class="k">${I("sparkles")} Extras earned with Amend</span><span class="v">${usd(t.extras_cents)}</span>
        <span class="small" style="opacity:.8">Changes and extra revisions you were paid for</span></a>
    </div>
    <div class="grid2" style="align-items:start">
      <section class="card"><h2>Needs you</h2>
        ${h.needs_you.length ? `<div class="list">${h.needs_you.map(n => `<a class="inbox-row" href="/studio/deals/${n.deal}">
          <span class="ic">${I(n.icon)}</span><div class="grow"><b>${esc(n.brand)}</b><div class="small">${esc(n.text)}</div></div>${I("chevron-right")}</a>`).join("")}</div>`
          : emptyState("circle-check", "All caught up", "Offers to accept, change cards, delivery gaps and releases show up here.")}</section>
      <section class="card"><div class="row between"><h2 style="margin:0">Upcoming</h2><a class="small" href="/studio/calendar">Calendar</a></div>
        ${h.upcoming.length ? `<ul class="events" style="margin-top:8px">${h.upcoming.map(e => `<li><span class="ev ${e.kind}" style="margin:0">${esc(EV_LABEL[e.kind])}</span>
          <a class="grow" href="/studio/deals/${e.deal}" style="color:var(--ink);text-decoration:none">${esc(e.brand)}</a><span class="small muted">${fmtDay(e.date)}</span></li>`).join("")}</ul>`
          : emptyState("calendar", "Nothing coming up", "Drafts due, posting dates and holdback releases appear here.")}</section>
    </div>
    <section style="margin-top:16px"><div class="row between"><h2 style="margin:0">Pipeline</h2><a class="small" href="/studio/deals?view=board">Board</a></div>
      <div class="pipeline" style="margin-top:10px">${h.pipeline.map(p => `<a href="/studio/deals?view=board#${p.key}"><b>${p.count}</b><span>${esc(p.label)}</span></a>`).join("")}</div></section>`;
  $("#h-new").onclick = () => newDeal();
}

/* ---------- Inbox: split view on desktop, change cards actionable inline ---------- */
let IBF = { filter: "all", q: "", sel: null };
/* ---------- Inbox: list | conversation | deal panel (full height; each pane scrolls on its own) ---------- */
const IB_TYPE_ICON = { message: "message-circle", eye: "eye", "file-pen": "file-pen", "pen-line": "file-pen", pencil: "pencil", wallet: "wallet",
  handshake: "handshake", lightbulb: "lightbulb", "circle-check": "circle-check", hourglass: "hourglass" };
const ibDealLabel = d => d.title || `${d.total_cents ? usd(d.total_cents) + " deal" : "New deal"} · ${fmtDate(d.created_at)}`;
async function inboxSplit() {
  const r = await api(`/api/studio/inbox?filter=${IBF.filter}&page=0`);
  badge(r.needs_threads);  // conversations that need me, not events
  const items = (r.threads || []).filter(x => !IBF.q || (x.brand + " " + x.line).toLowerCase().includes(IBF.q.toLowerCase()));
  IBF.threads = Object.fromEntries((r.threads || []).map(x => [x.brand, x]));
  if (IBF.selBrand && !IBF.threads[IBF.selBrand]) { IBF.selBrand = null; IBF.sel = null; }
  if (!IBF.selBrand && items.length && matchMedia("(min-width: 1024px)").matches) { IBF.selBrand = items[0].brand; IBF.sel = items[0].deal; }
  const c = r.counts || {};
  $("#view").innerHTML = `<div class="ibx ${IBF.mobileConv ? "conv-open" : ""}" id="ibx">
    <aside class="ibx-list" aria-label="Conversations">
      <div class="ibx-head"><h1>Inbox</h1>${r.unread ? `<button class="btn small ghost" id="allread">${I("check-check")} Mark all read</button>` : ""}</div>
      <div class="ibx-tools"><div class="chips">${[["all", "All"], ["needs_me", "Needs me"], ["messages", "Messages"], ["money", "Money"]]
        .map(([k, t]) => `<button data-f="${k}" class="${IBF.filter === k ? "on" : ""}">${t}${k === "needs_me" && c.needs_me ? `<span class="dot">${c.needs_me}</span>` : ""}</button>`).join("")}</div>
        <input id="ib-q" placeholder="Search" aria-label="Search the inbox" value="${esc(IBF.q)}"></div>
      <div class="ibx-rows">${items.length ? items.map(x => `
        <button class="ibx-row ${x.unread ? "unread" : ""} ${IBF.selBrand === x.brand ? "sel" : ""}" data-brand="${esc(x.brand)}" data-deal="${x.deal}" data-ids="${x.unread_ids.join(",")}">
          <span class="avatar sm">${initials(x.brand)}</span>
          <span class="ibx-main"><span class="ibx-top"><b>${esc(x.brand)}</b><span class="tiny muted">${ago(x.at)}</span></span>
            <span class="ibx-prev">${I(x.kind === "message" ? "message-circle" : (IB_TYPE_ICON[x.icon] || "bell"))}<span class="txt">${esc(x.line)}</span>
              ${x.unread ? `<span class="udot" aria-label="${x.unread} unread"></span>` : ""}</span></span></button>`).join("")
        : emptyState("inbox", IBF.q || IBF.filter !== "all" ? "Nothing matches" : "Nothing new", "Messages, change cards and PayPal updates show up here.")}</div>
    </aside>
    <section class="ibx-conv" id="ibx-conv" aria-label="Conversation"></section>
    <aside class="ibx-deal" id="ibx-deal" aria-label="Deal details"></aside>
  </div>`;
  $$(".chips button").forEach(b => b.onclick = () => { IBF.filter = b.dataset.f; inboxSplit(); });
  let tq; $("#ib-q").oninput = e => { clearTimeout(tq); tq = setTimeout(() => { IBF.q = e.target.value; inboxSplit().then(() => { const q = $("#ib-q"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }); }, 250); };
  if ($("#allread")) $("#allread").onclick = e => busy(e.currentTarget, async () => {
    await api("/api/studio/inbox/read", { body: { event_ids: (r.threads || []).flatMap(t => t.unread_ids) } }); inboxSplit(); });
  // Opening a conversation is instant: select the row and open its chat straight away (no reload of the whole list);
  // marking its updates read happens in the background.
  $$(".ibx-row").forEach(row => row.onclick = () => {
    const ids = row.dataset.ids ? row.dataset.ids.split(",").map(Number) : [];
    IBF.selBrand = row.dataset.brand; IBF.sel = row.dataset.deal; IBF.mobileConv = true;
    $$(".ibx-row").forEach(r => r.classList.toggle("sel", r === row));
    row.classList.remove("unread"); row.querySelector(".udot")?.remove(); row.dataset.ids = "";
    $("#ibx").classList.add("conv-open");
    openPane(IBF.sel);
    if (ids.length) api("/api/studio/inbox/read", { body: { event_ids: ids } }).catch(() => {});
  });
  if (IBF.sel) openPane(IBF.sel); else $("#ibx-conv").innerHTML = `<div class="ibx-empty">${emptyState("messages-square", "Pick a conversation", "Choose a brand on the left to see its chat.")}</div>`;
}

const IB_ACT = (d, V) => {  // the next step on this deal, worked out from its status and money (never from the AI)
  const href = (h = "") => `/studio/deals/${d.id}${h}`;
  const pend = (V.extra_holds || []).some(h => ["planned", "approved", "sent", "failed"].includes(h.status));
  const draftSent = (V.events || []).some(e => e.type === "draft.uploaded");
  switch (d.status) {
    case "draft": return ["Waiting for the brand's brief", "They write it from your deal link; you'll see the priced offer here.", "Open the deal", href()];
    case "offered": return ["Check and accept the offer", `Priced from your list: ${usd(V.total_cents)}.`, "Review the offer", href()];
    case "accepted": return V.money_held ? ["Start the work", "The money is held by PayPal.", "Open the deal", href()] : ["Waiting for the brand to pay", "Work starts once PayPal holds the money.", "Open the deal", href()];
    case "paused": return ["Paused", "Two people at the brand gave different instructions. Money waits until they pick one.", "See both", href()];
    case "in_progress": return pend ? ["Waiting for the extra hold", "A confirmed change needs more money held.", "Open the deal", href("#money")]
      : draftSent ? ["Waiting for the brand's review", "They approve the draft, then you post.", "Open the deal", href("#delivery")] : ["Send your draft", "The delivery check runs against the latest confirmed deal.", "Upload the draft", href("#delivery")];
    case "delivered": return ["Approve the release", "The delivery matches the deal. Approve so you get paid.", "Review the release", href("#delivery")];
    case "completed": return ["Done · paid", "Every payment is in the ledger with the words behind it.", "See the ledger", "/studio/ledger"];
    case "cancelled": return ["Cancelled", "The split was paid as agreed.", "Open the deal", href()];
  }
  return ["Open the deal", "", "Open the deal", href()];
};
async function openPane(dealId) {
  const conv = $("#ibx-conv"), panel = $("#ibx-deal"), t = (IBF.threads || {})[IBF.selBrand] || { deals: [] };
  const cur = t.deals.find(d => d.id === dealId) || t.deals[0] || { id: dealId };
  conv.innerHTML = `<header class="ibx-convhead">
      <button class="iconbtn ibx-back" id="ib-back" aria-label="Back to the list">${I("arrow-left")}</button>
      <span class="avatar sm">${initials(IBF.selBrand || "")}</span>
      <div class="grow" style="min-width:0"><div class="row" style="gap:8px;flex-wrap:wrap"><b class="ibx-brand">${esc(IBF.selBrand || "")}</b>
        <span class="pill status" id="ib-status">${esc(DEAL_LABEL[cur.status] || "")}</span></div>
        ${t.deals.length > 1 ? `<label class="ibx-switch"><span>Deal:</span> <select id="pane-deal">${t.deals.map(d => `<option value="${d.id}" ${d.id === dealId ? "selected" : ""}>${esc(ibDealLabel(d))}</option>`).join("")}</select></label>`
          : `<div class="tiny muted">${esc(ibDealLabel(cur))}</div>`}</div>
      <button class="btn small ibx-paneltoggle" id="ib-panel" aria-label="Deal details">${I("panel-right")}<span class="lbl-long"> Deal details</span><span class="lbl-short"> Deal</span></button>
    </header>
    <div class="ibx-chat" id="pane-chat"><div class="skeleton"></div></div>`;
  $("#ib-back").onclick = () => { IBF.mobileConv = false; $("#ibx").classList.remove("conv-open"); };
  $("#ib-panel").onclick = () => $("#ibx").classList.toggle("panel-open");
  if ($("#pane-deal")) $("#pane-deal").onchange = e => { IBF.sel = e.target.value; openPane(IBF.sel); };
  panel.innerHTML = `<div class="skeleton"></div>`;
  if (typeof Chat !== "undefined") Chat.mount($("#pane-chat"), { base: `/api/deals/${dealId}`, isBrand: false, token: "", fill: true, onApplied: () => openPane(dealId) });
  let V; try { V = await api(`/api/deals/${dealId}`); } catch (e) { panel.innerHTML = `<p class="small muted">${esc(e.message)}</p>`; return; }
  const d = V.deal, [title, why, act, href] = IB_ACT(d, V);
  $("#ib-status").textContent = DEAL_LABEL[d.status] || d.status;
  panel.innerHTML = `<button class="iconbtn ibx-panelclose" id="ib-close" aria-label="Close deal details">${I("x")}</button>
    <div class="row" style="gap:10px"><span class="avatar">${initials(d.brand_org)}</span><div style="min-width:0"><b>${esc(d.brand_org)}</b>
      <div class="tiny muted">${esc(d.title || ibDealLabel({ ...cur, ...d }))}</div></div></div>
    <dl class="ibx-facts">
      <div><dt>Deal amount</dt><dd><b>${usd(V.total_cents)}</b> <span class="aed">${aed(V.total_cents)}</span></dd></div>
      <div><dt>Money</dt><dd>${V.hold ? moneyPill(V.hold.status) : '<span class="pill">Nothing held yet</span>'}${V.held_cents ? ` <span class="small">${usd(V.held_cents)} held</span>` : ""}</dd></div>
      ${d.deadline ? `<div><dt>Post date</dt><dd>${esc(fmtDate(d.deadline))}</dd></div>` : ""}
    </dl>
    <div class="ibx-next"><div class="tiny muted">Next step</div><b>${esc(title)}</b><p class="small muted">${esc(why)}</p>
      <a class="btn primary block" href="${href}">${esc(act)}</a></div>
    <a class="small" href="/studio/deals/${d.id}">${I("external-link")} Open the deal</a>`;
  $("#ib-close").onclick = () => $("#ibx").classList.remove("panel-open");
  // phones: the next step sits in a bar just above the composer
  const chat = $("#pane-chat .chat"), form = $("#chat-form");
  if (chat && form && !$("#ibx-nextbar")) form.insertAdjacentHTML("beforebegin", `<a class="ibx-nextbar" id="ibx-nextbar" href="${href}"><span>Next: <b>${esc(act)}</b></span><span aria-hidden="true">→</span></a>`);
}

/* ---------- Deals: board (kanban) and list (sortable) ---------- */
let DV = { view: new URLSearchParams(location.search).get("view") || "board", q: "", sort: "updated_at", dir: -1, status: "" };
async function dealsBoard() {
  const r = await api("/api/studio/deals?filter=all&page=0&q=" + encodeURIComponent(DV.q));
  let rows = r.deals.filter(d => !DV.status || d.stage === DV.status || d.status === DV.status);
  $("#view").innerHTML = `
    <div class="row between wrapx" style="gap:8px"><h1>Deals</h1>
      <div class="row" style="gap:8px"><div class="seg" role="tablist" style="width:200px"><button data-v="board" class="${DV.view === "board" ? "on" : ""}">${I("kanban")} Board</button>
        <button data-v="list" class="${DV.view === "list" ? "on" : ""}">${I("list")} List</button></div>
        <button class="btn primary" id="d-new">${I("plus")} New deal link</button></div></div>
    <p class="muted">${r.counts.all} deal${r.counts.all === 1 ? "" : "s"} · ${usd(r.held_cents)} held · ${r.counts.needs_me} waiting for you</p>
    <div class="row wrapx" style="gap:8px;margin-bottom:12px"><input id="d-q" placeholder="Search by brand or deal number" value="${esc(DV.q)}" style="max-width:320px">
      <select id="d-st" style="width:auto"><option value="">All stages</option>${Object.entries(STAGE_LABEL).map(([k, l]) => `<option value="${k}" ${DV.status === k ? "selected" : ""}>${l}</option>`).join("")}
        <option value="cancelled" ${DV.status === "cancelled" ? "selected" : ""}>Cancelled</option></select></div>
    <div id="d-body"></div>`;
  const body = $("#d-body");
  if (!rows.length) body.innerHTML = emptyState("link", r.counts.all ? "No deals match" : "No deals yet", r.counts.all ? "Try another search or stage." : "Send a brand your deal link to start.",
    `<button class="btn primary" onclick="newDeal()">${I("plus")} New deal link</button>`);
  else if (DV.view === "board") {
    const cols = Object.keys(STAGE_LABEL);
    body.innerHTML = `<div class="board">${cols.map(k => { const c = rows.filter(d => d.stage === k);
      return `<section class="col" id="${k}"><h3><span>${STAGE_LABEL[k]}</span><span>${c.length}</span></h3>${c.map(d => `
        <a class="card dealcard hover ${d.needs_me ? "needs" : ""}" href="/studio/deals/${d.id}"><div class="row between"><b>${esc(d.brand)}</b>${d.is_demo ? '<span class="pill">Demo</span>' : ""}</div>
          <div class="row between" style="margin-top:6px"><span class="num">${usd(d.total_cents)}</span>${moneyPill(d.money)}</div>
          <div class="tiny muted" style="margin-top:6px">${d.needs_me ? `<span class="needs-pill">${I("circle-alert")} Needs you</span> ` : ""}${ago(d.updated_at)}</div></a>`).join("")}</section>`; }).join("")}</div>`;
  } else {
    const cols = [["brand", "Brand"], ["total_cents", "Value", "n"], ["stage", "Status"], ["money", "Money"], ["deadline", "Next deadline"], ["updated_at", "Last activity"]];
    rows = rows.slice().sort((a, b) => (a[DV.sort] > b[DV.sort] ? 1 : a[DV.sort] < b[DV.sort] ? -1 : 0) * DV.dir);
    body.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr>${cols.map(([k, l, n]) => `<th class="${n || ""}" data-sort="${k}" aria-sort="${DV.sort === k ? (DV.dir > 0 ? "ascending" : "descending") : "none"}">${l} ${DV.sort === k ? I(DV.dir > 0 ? "arrow-up" : "arrow-down") : ""}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(d => `<tr data-go="/studio/deals/${d.id}" style="cursor:pointer"><td><b>${esc(d.brand)}</b> ${d.is_demo ? '<span class="pill">Demo</span>' : ""}</td><td class="n">${usd(d.total_cents)}</td>
        <td>${esc(STAGE_LABEL[d.stage] || d.status)}</td><td>${moneyPill(d.money) || '<span class="muted small">–</span>'}</td><td>${esc(d.deadline || "–")}</td><td>${ago(d.updated_at)}</td></tr>`).join("")}</tbody></table></div>`;
    $$("th[data-sort]").forEach(th => th.onclick = () => { DV.dir = DV.sort === th.dataset.sort ? -DV.dir : 1; DV.sort = th.dataset.sort; dealsBoard(); });
    $$("tr[data-go]").forEach(tr => tr.onclick = () => location.href = tr.dataset.go);
  }
  $$("[data-v]").forEach(b => b.onclick = () => { DV.view = b.dataset.v; history.replaceState({}, "", "/studio/deals?view=" + DV.view); dealsBoard(); });
  $("#d-new").onclick = () => newDeal();
  let tq; $("#d-q").oninput = e => { clearTimeout(tq); tq = setTimeout(() => { DV.q = e.target.value; dealsBoard().then(() => $("#d-q").focus()); }, 250); };
  $("#d-st").onchange = e => { DV.status = e.target.value; dealsBoard(); };
  if (location.hash) { const el = document.getElementById(location.hash.slice(1)); if (el) el.scrollIntoView({ inline: "center", block: "nearest" }); }
}

/* ---------- Earnings ---------- */
async function earningsTab(ledgerView = false) {
  if (ledgerView) return ledger();
  const e = await api("/api/studio/earnings");
  const t = e.totals;
  $("#view").innerHTML = `
    <div class="row between wrapx" style="gap:8px"><h1>Earnings</h1>
      <div class="row" style="gap:8px"><a class="btn small" href="/studio/ledger">${I("table")} Full ledger</a>
        <button class="btn small" id="e-csv">${I("download")} CSV</button>
        ${e.months.length ? `<select id="e-month" style="width:auto">${e.months.map(m => `<option>${m}</option>`).join("")}</select>
          <a class="btn small primary" id="e-pdf" href="/api/studio/earnings/statement.pdf?month=${e.months[0]}">${I("file-text")} Monthly statement</a>` : ""}</div></div>
    <div class="grid4" style="margin:16px 0">
      <div class="tile"><span class="k">Lifetime</span><span class="v">${usd(t.lifetime_cents)}</span></div>
      <div class="tile"><span class="k">This month</span><span class="v">${usd(t.month_cents)}</span></div>
      <div class="tile"><span class="k">Held for you</span><span class="v">${usd(t.held_cents)}</span></div>
      <div class="tile"><span class="k">To be released</span><span class="v">${usd(t.to_release_cents)}</span></div>
    </div>
    <p class="small muted">PayPal fees so far: <b>${usd(t.fees_cents)}</b> · Extras earned with Amend: <b>${usd(t.extras_cents)}</b></p>
    <section style="margin-top:16px"><h2>Payout history</h2>
      ${e.rows.length ? `<div class="table-wrap"><table class="data"><thead><tr><th>Date</th><th>Brand</th><th class="n">Gross</th><th class="n">Fee</th><th class="n">Editor</th><th class="n">Net to you</th><th>PayPal ID</th><th>Status</th><th></th></tr></thead>
        <tbody>${e.rows.map(r => `<tr><td>${esc(r.date)}</td><td><a href="/studio/deals/${r.deal}">${esc(r.brand)}</a></td><td class="n">${usd(r.gross_cents)}</td><td class="n">${usd(r.fee_cents)}</td>
          <td class="n">${usd(r.editor_cents)}</td><td class="n"><b>${usd(r.net_cents)}</b></td><td class="tiny">${esc(r.paypal_id || "–")}</td>
          <td>${r.status === "paid" ? '<span class="pill collected">Paid</span>' : `<span class="pill held">${esc(r.status)}</span>`}</td>
          <td><a class="btn small ghost" href="/api/deals/${r.deal}/receipt.pdf" aria-label="Receipt PDF">${I("receipt")}</a></td></tr>`).join("")}</tbody></table></div>`
        : emptyState("wallet", "No payouts yet", "When a deal is released, PayPal pays you and it shows up here.")}</section>
    <section class="card" style="margin-top:16px"><h2>Holdbacks</h2>
      ${e.holdbacks.length ? `<div class="list">${e.holdbacks.map(h => `<div class="line"><div class="grow"><b>${esc(h.brand)}</b><div class="small muted">${esc(h.why)}</div></div>
        <div class="amt">${usd(h.amount_cents)}<div class="tiny muted">until ${h.until ? fmtDay(h.until.slice(0, 10)) : "–"}</div></div></div>`).join("")}</div>`
        : '<p class="muted small">Nothing held back right now.</p>'}</section>
    ${e.owed_cents ? `<section class="card" style="margin-top:16px"><div class="row between"><h2>Owed to Amend</h2><b>${usd(e.owed_cents)}</b></div>
      <p class="small muted">A refund to a brand after you were paid, more than that deal's holdback covered. It comes off your next payout.</p>
      <div class="list">${e.owed.map(o => `<div class="line"><div class="grow"><a href="/studio/deals/${o.deal}"><b>${esc(o.brand || "Deal")}</b></a>
        <div class="tiny muted">since ${esc(fmtDate(o.since))}${o.left_cents < o.amount_cents ? ` · ${usd(o.amount_cents - o.left_cents)} already taken` : ""}</div></div>
        <div class="amt">${usd(o.left_cents)}</div></div>`).join("")}</div></section>` : ""}
    <p class="small muted" style="margin-top:16px">Payouts go to your PayPal email (${esc(ME.paypal_email_masked || "not set")}). Change it in <a href="/studio/settings">Settings</a>.</p>`;
  const sel = $("#e-month");
  if (sel) sel.onchange = () => { $("#e-pdf").href = "/api/studio/earnings/statement.pdf?month=" + sel.value; };
  $("#e-csv").onclick = () => {
    const head = ["date", "brand", "gross_usd", "fee_usd", "editor_usd", "net_usd", "paypal_id", "status"];
    const csv = [head.join(",")].concat(e.rows.map(r => [r.date, `"${(r.brand || "").replace(/"/g, '""')}"`, r.gross_cents / 100, r.fee_cents / 100,
      r.editor_cents / 100, r.net_cents / 100, r.paypal_id || "", r.status].join(","))).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "amend-payouts.csv"; a.click();
  };
}

/* ---------- Price list: packages, terms template, brand preview (Block 5) ---------- */
async function pricesPlus() {
  await prices();
  const t = await api("/api/studio/terms");
  const f = (k, label, unit, step = 1) => `<div><label>${label}</label><div class="row"><input type="number" min="0" step="${step}" data-t="${k}" value="${k === "date_change_fee_cents" ? t[k] / 100 : t[k]}"><span class="small muted">${unit}</span></div></div>`;
  $("#view").insertAdjacentHTML("beforeend", `
    <section class="card" style="margin-top:14px"><h2>Terms template</h2>
      <p class="small muted">Your defaults for every new deal. Brands see them in the brief; you can still change a deal's terms before you accept.</p>
      <div class="grid2">${f("revisions_included", "Revisions included", "rounds")}${f("cancellation_min_pct", "Minimum if cancelled after work starts", "%")}
        ${f("date_change_free_hours", "Date change free with notice of", "hours")}${f("date_change_fee_cents", "Date change fee otherwise", "$")}
        ${f("silent_approval_days", "Silent approval after", "days without review")}${f("holdback_pct", "Holdback", "% until days live")}
        ${f("days_live", "Days live", "days")}</div>
      <button class="btn primary block" id="t-save" style="margin-top:14px">Save terms template</button></section>
    <section class="card" style="margin-top:14px"><div class="row between"><h2 style="margin:0">How brands see your prices</h2>
      <a class="btn small" href="/c/${esc(ME.handle)}" target="_blank" rel="noopener">${I("external-link")} Open</a></div>
      <div id="t-preview" style="margin-top:10px"></div></section>`);
  $("#t-save").onclick = e => busy(e.currentTarget, async () => {
    const body = Object.fromEntries($$("[data-t]").map(i => [i.dataset.t, i.dataset.t === "date_change_fee_cents" ? Math.round(+i.value * 100) : Math.round(+i.value)]));
    try { await api("/api/studio/terms", { method: "PUT", body }); toast("Terms template saved"); } catch (er) { toast(er.message, "bad"); }
  });
  const pub = await api(`/api/c/${encodeURIComponent(ME.handle)}`);
  $("#t-preview").innerHTML = `<div class="list">${pub.items.filter(p => p.standard_cents != null).map(p => `<div class="line"><div class="grow"><b>${esc(p.name)}</b>
    ${p.kind === "package" ? '<span class="pill held">Package</span>' : ""}${p.rules && p.rules.note ? `<div class="small muted">${esc(p.rules.note)}</div>` : ""}</div>
    <div class="amt">${usd(p.standard_cents)}<div class="aed">${p.aed}</div></div></div>`).join("")}</div>`;
}

/* ---------- Profile & media kit: QR code, link-in-bio, media kit PDF (Block 5) ---------- */
function loadQR() {
  if (window.qrcode) return Promise.resolve();
  return new Promise((res, rej) => { const s = document.createElement("script"); s.src = "https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js";
    s.onload = res; s.onerror = () => rej(new Error("QR code couldn't load")); document.head.appendChild(s); });
}
async function profilePlus() {
  await profile();
  const url = location.origin + "/c/" + ME.handle;
  $("#view").insertAdjacentHTML("afterbegin", `<section class="card" style="margin-bottom:14px"><div class="row between wrapx" style="gap:12px">
      <div class="grow"><h2 style="margin:0">Your link and media kit</h2><p class="small muted" style="margin:4px 0 0">Put the link in your bio. Brands see your prices and can book you with money held by PayPal.</p>
        <input readonly value="${esc(url)}" style="margin-top:10px" onclick="this.select()">
        <div class="row wrapx" style="gap:8px;margin-top:10px"><button class="btn small primary" id="pk-copy">${I("copy")} Copy link-in-bio</button>
          <a class="btn small" href="/api/studio/mediakit.pdf">${I("file-down")} Download media kit PDF</a>
          <a class="btn small" href="/c/${esc(ME.handle)}" target="_blank" rel="noopener">${I("eye")} Preview public page</a></div></div>
      <div id="pk-qr" aria-label="QR code for your link" style="background:#fff;padding:8px;border-radius:12px;width:148px;height:148px"></div></div></section>`);
  $("#pk-copy").onclick = async () => { try { await navigator.clipboard.writeText(url); } catch {} toast("Link copied"); };
  try { await loadQR(); const q = qrcode(0, "M"); q.addData(url); q.make(); $("#pk-qr").innerHTML = q.createSvgTag({ cellSize: 4, margin: 0 }); }
  catch { $("#pk-qr").innerHTML = '<p class="tiny muted">QR code unavailable offline</p>'; }
}

/* ---------- Brands (mini-CRM) ---------- */
async function brandsTab() {
  const r = await api("/api/studio/brands");
  $("#view").innerHTML = `<div class="row between"><h1>Brands</h1></div>
    <p class="muted">Every brand you've worked with on Amend.</p>
    ${r.brands.length ? `<div class="grid2">${r.brands.map((b, i) => `<section class="card"><div class="row between"><div class="row"><div class="avatar">${initials(b.brand)}</div>
        <div><b>${esc(b.brand)}</b> ${b.is_demo ? '<span class="pill">Demo</span>' : ""}<div class="small muted">${esc(b.contact || "")}</div></div></div>
        <button class="btn small primary" data-again="${i}">${I("link")} New deal link</button></div>
      <div class="stats" style="grid-template-columns:repeat(3,1fr)"><div><b>${b.deals}</b><span>deals</span></div><div><b>${usd(b.value_cents)}</b><span>total value</span></div>
        <div><b>${b.avg_rating ? b.avg_rating + " / 5" : "–"}</b><span>review score</span></div></div>
      <p class="small muted">Last deal ${b.last_deal ? ago(b.last_deal) : "–"}</p>
      <label for="note-${i}">Notes (only you see these)</label><textarea id="note-${i}" data-note="${i}" style="min-height:70px" maxlength="2000">${esc(b.notes || "")}</textarea>
      <button class="btn small" data-save="${i}" style="margin-top:6px">Save notes</button></section>`).join("")}</div>`
      : emptyState("building-2", "No brands yet", "Brands you work with show up here, with their deals and your notes.", `<button class="btn primary" onclick="newDeal()">${I("plus")} New deal link</button>`)}`;
  $$("[data-again]").forEach(b => b.onclick = () => { const x = r.brands[+b.dataset.again]; newDeal();
    setTimeout(() => { const s = $("#sheet"); $("input[name=brand_org]", s).value = x.brand; $("input[name=contact_name]", s).value = x.contact || "";
      if (x.contact_email) $("input[name=contact_email]", s).value = x.contact_email; }, 30); });
  $$("[data-save]").forEach(b => b.onclick = () => busy(b, async () => { const i = +b.dataset.save;
    await api("/api/studio/brands/notes", { method: "PUT", body: { brand: r.brands[i].brand, notes: $(`[data-note="${i}"]`).value } }); toast("Notes saved"); }));
}

/* ---------- Settings ---------- */
async function settingsTab() {
  const s = await api("/api/studio/settings");
  const sel = (k, v) => `<select data-n="${k}">${[["whatsapp", "WhatsApp + in-app"], ["in-app", "In-app only"], ["off", "Off"]].map(([x, l]) => `<option value="${x}" ${v === x ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  $("#view").innerHTML = `<h1>Settings</h1>
    <div class="grid2" style="align-items:start">
      <section class="card"><h2>Account</h2>
        <label>Name</label><input id="s-name" value="${esc(s.account.name)}" maxlength="80">
        <label>Email</label><input value="${esc(s.account.email)}" disabled>
        ${s.account.demo ? '<p class="hint">Demo account: it uses the shared demo password, which can\'t be changed here.</p>'
          : `<label>Current password</label><input id="s-cur" type="password" autocomplete="current-password"><label>New password</label><input id="s-new" type="password" autocomplete="new-password">
             <button class="btn small" id="s-pw" style="margin-top:8px">Change password</button>`}
        <label>PayPal payout email</label><input id="s-pp" type="email" value="${esc(s.paypal_email || "")}" placeholder="your PayPal email">
        <p class="hint">Payouts from released deals go here (PayPal sandbox in this demo).</p>
        <label>UAE Advertiser Permit</label><p class="small">${esc(s.permit.label)} · <a href="/studio/prices">Edit in Price list</a></p></section>
      <section class="card"><h2>Notifications</h2>
        ${[["change", "Change cards"], ["money", "Money updates (held, paid)"], ["message", "New messages"], ["delivery", "Drafts, gaps and delivery"]].map(([k, l]) => `<label>${l}</label>${sel(k, s.notify[k])}`).join("")}
        <p class="hint">WhatsApp is sent from Amend's own number once the template is approved; in-app is always on in your Inbox.</p>
        <h2 style="margin-top:16px">Language and theme</h2>
        <label>Language</label><select id="s-lang"><option value="en" ${s.language === "en" ? "selected" : ""}>English</option><option value="ar" ${s.language === "ar" ? "selected" : ""}>العربية (Arabic, coming soon)</option></select>
        <label>Theme</label><select id="s-theme">${[["system", "Follow my device"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) => `<option value="${v}" ${s.theme === v ? "selected" : ""}>${l}</option>`).join("")}</select></section>
    </div>
    <button class="btn primary" id="s-save" style="margin-top:14px">Save settings</button>
    <section class="card" style="margin-top:14px"><h2>Your data</h2>
      <div class="row wrapx" style="gap:8px"><a class="btn" href="/api/studio/export">${I("download")} Export my data (JSON)</a>
        <button class="btn danger" id="s-del">${I("trash-2")} Delete my recordings and screenshots</button></div>
      <p class="hint">Deleting keeps a record that the files were deleted, as the deal history requires.</p></section>`;
  $("#s-save").onclick = e => busy(e.currentTarget, async () => {
    try {
      await api("/api/studio/settings", { method: "PUT", body: { name: $("#s-name").value, paypal_email: $("#s-pp").value, language: $("#s-lang").value,
        theme: $("#s-theme").value, notify: Object.fromEntries($$("[data-n]").map(x => [x.dataset.n, x.value])) } });
      applyTheme($("#s-theme").value); toast("Settings saved");
    } catch (er) { toast(er.message, "bad"); }
  });
  if ($("#s-pw")) $("#s-pw").onclick = e => busy(e.currentTarget, async () => {
    try { await api("/api/account/password", { body: { current: $("#s-cur").value, new: $("#s-new").value } }); toast("Password changed"); } catch (er) { toast(er.message, "bad"); } });
  $("#s-del").onclick = e => { if (confirm("Delete all your voice notes, call transcripts, screenshots and files on every deal?")) busy(e.currentTarget, async () => {
    const r = await api("/api/studio/media/delete-all", { method: "POST" }); toast(`Deleted ${r.deleted} file${r.deleted === 1 ? "" : "s"}`); }); };
}

/* ---------- Calendar ---------- */
let CAL = { month: new Date(), view: "month" };
async function calendarTab() {
  const r = await api("/api/studio/calendar");
  const ev = r.events;
  const y = CAL.month.getFullYear(), m = CAL.month.getMonth();
  const todayIso = new Date().toISOString().slice(0, 10);
  const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  let days = [];
  if (CAL.view === "month") {
    const first = new Date(y, m, 1), start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));
    for (let i = 0; i < 42; i++) { const d = new Date(start); d.setDate(start.getDate() + i); days.push(d); }
  } else {
    const start = new Date(CAL.month); start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    for (let i = 0; i < 7; i++) { const d = new Date(start); d.setDate(start.getDate() + i); days.push(d); }
  }
  const title = CAL.view === "month" ? CAL.month.toLocaleDateString("en-GB", { month: "long", year: "numeric" })
    : `Week of ${days[0].toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
  $("#view").innerHTML = `
    <div class="row between wrapx" style="gap:8px"><h1>Calendar</h1>
      <div class="row" style="gap:8px"><div class="seg" style="width:180px"><button data-cv="month" class="${CAL.view === "month" ? "on" : ""}">Month</button><button data-cv="week" class="${CAL.view === "week" ? "on" : ""}">Week</button></div>
        <a class="btn small" href="/api/studio/calendar.ics">${I("calendar-plus")} Export .ics</a></div></div>
    <div class="row between" style="margin:12px 0"><button class="iconbtn" id="c-prev" aria-label="Previous">${I("chevron-left")}</button>
      <h2 style="margin:0">${esc(title)}</h2><button class="iconbtn" id="c-next" aria-label="Next">${I("chevron-right")}</button></div>
    <div class="legend" style="margin-bottom:10px">${Object.entries(EV_LABEL).map(([k, l]) => `<span class="ev ${k}">${l}</span>`).join("")}</div>
    <div class="cal">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(d => `<div class="dow">${d}</div>`).join("")}
      ${days.map(d => { const k = iso(d); const es = ev.filter(e => e.date === k);
        return `<div class="cell ${d.getMonth() !== m && CAL.view === "month" ? "other" : ""} ${k === todayIso ? "today" : ""}" ${CAL.view === "week" ? 'style="min-height:180px"' : ""}>
          <div class="d">${d.getDate()}</div>${es.map(e => `<a class="ev ${e.kind}" href="/studio/deals/${e.deal}" title="${esc(e.label)}">${esc(CAL.view === "week" ? e.label : e.brand)}</a>`).join("")}</div>`; }).join("")}</div>
    <section class="card" style="margin-top:16px"><h2>Next up</h2>${(() => { const up = ev.filter(e => e.date >= todayIso).slice(0, 8);
      return up.length ? `<ul class="events">${up.map(e => `<li><span class="ev ${e.kind}" style="margin:0">${esc(EV_LABEL[e.kind])}</span><a class="grow" href="/studio/deals/${e.deal}" style="color:var(--ink);text-decoration:none">${esc(e.brand)}</a><span class="small muted">${fmtDay(e.date)}</span></li>`).join("")}</ul>`
        : '<p class="muted small">Nothing coming up.</p>'; })()}</section>`;
  $$("[data-cv]").forEach(b => b.onclick = () => { CAL.view = b.dataset.cv; calendarTab(); });
  $("#c-prev").onclick = () => { CAL.view === "month" ? CAL.month.setMonth(CAL.month.getMonth() - 1) : CAL.month.setDate(CAL.month.getDate() - 7); calendarTab(); };
  $("#c-next").onclick = () => { CAL.view === "month" ? CAL.month.setMonth(CAL.month.getMonth() + 1) : CAL.month.setDate(CAL.month.getDate() + 7); calendarTab(); };
}
