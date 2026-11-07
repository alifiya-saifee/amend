// Studio pages (Block 4–5): Home, Inbox (split), Deals (board / list), Earnings, Calendar, Brands, Settings.
// Every number comes from the API (real tables). Used by studio.html's router.
const I = (n, cls = "") => `<i data-lucide="${n}" class="${cls}" aria-hidden="true"></i>`;
const STAGE_LABEL = { brief: "Brief", accepted: "Accepted", held: "Held", production: "In production", delivered: "Delivered", paid: "Paid" };
const EV_LABEL = { draft: "Draft due", post: "Posting date", product: "Product", review: "Brand review due", holdback: "Holdback release", expiry: "Hold expires" };
const fmtDay = iso => new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
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
          : emptyState("circle-check", "All caught up", "Drafts to accept, change cards, delivery gaps and releases show up here.")}</section>
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
async function inboxSplit() {
  const r = await api(`/api/studio/inbox?filter=${IBF.filter}&page=0`);
  badge(r.unread);
  const items = r.items.filter(x => !IBF.q || (x.brand + " " + x.line).toLowerCase().includes(IBF.q.toLowerCase()));
  const c = r.counts || {};
  $("#view").innerHTML = `
    <div class="row between wrapx" style="gap:8px"><h1>Inbox</h1>
      <div class="row" style="gap:8px">${r.unread ? `<button class="btn small" id="allread">${I("check-check")} Mark all read</button>` : ""}</div></div>
    <div class="row wrapx" style="gap:8px;margin:8px 0 12px">
      <div class="chips">${[["all", "All"], ["needs_me", "Needs me"], ["messages", "Messages"], ["money", "Money"]]
        .map(([k, t]) => `<button data-f="${k}" class="${IBF.filter === k ? "on" : ""}">${t}${k === "needs_me" && c.needs_me ? `<span class="dot">${c.needs_me}</span>` : ""}</button>`).join("")}</div>
      <input id="ib-q" placeholder="Search the inbox" value="${esc(IBF.q)}" style="max-width:260px"></div>
    <div class="split">
      <div class="card" style="padding:6px">${items.length ? items.map(x => `
        <div class="inbox-row ${x.unread ? "unread" : ""} ${IBF.sel === x.deal ? "sel" : ""}" data-ev="${x.event_id}" data-deal="${x.deal}" tabindex="0" role="button">
          <span class="ic">${I(x.icon)}</span>
          <div class="grow"><div class="row between"><b>${esc(x.brand)}</b><span class="tiny muted">${ago(x.at)}</span></div>
            <div class="small">${esc(x.line)}</div>
            ${x.change ? `<div class="row" style="gap:6px;margin-top:6px"><button class="btn small primary" data-cc="${x.change}" data-cd="${x.deal}" data-a="confirm">${I("check")} Confirm</button>
              <button class="btn small" data-cc="${x.change}" data-cd="${x.deal}" data-a="reject">Reject</button></div>` : ""}</div>
          ${x.unread ? '<span class="udot" aria-label="unread"></span>' : ""}</div>`).join("")
        : emptyState("inbox", "Nothing new", "Messages, change cards and PayPal updates show up here.")}</div>
      <div class="pane hide-mobile" id="ib-pane">${IBF.sel ? "" : `<div class="card">${emptyState("messages-square", "Pick a conversation", "Its chat opens here.")}</div>`}</div>
    </div>`;
  $$(".chips button").forEach(b => b.onclick = () => { IBF.filter = b.dataset.f; inboxSplit(); });
  let tq; $("#ib-q").oninput = e => { clearTimeout(tq); tq = setTimeout(() => { IBF.q = e.target.value; inboxSplit().then(() => $("#ib-q").focus()); }, 250); };
  if ($("#allread")) $("#allread").onclick = e => busy(e.currentTarget, async () => {
    await api("/api/studio/inbox/read", { body: { event_ids: r.items.filter(i => i.unread).map(i => i.event_id) } }); inboxSplit(); });
  $$("[data-cc]").forEach(b => b.onclick = ev => { ev.stopPropagation(); busy(b, async () => {
    let reason = null;
    try { await api(`/api/deals/${b.dataset.cd}/changes/${b.dataset.cc}/${b.dataset.a}`, { body: { reason } }); toast(b.dataset.a === "confirm" ? "Confirmed" : "Rejected"); inboxSplit(); }
    catch (e) { if (/override/.test(e.message)) { location.href = `/studio/deals/${b.dataset.cd}`; } else toast(e.message, "bad"); }
  }); });
  $$(".inbox-row[data-deal]").forEach(row => row.onclick = async () => {
    try { await api("/api/studio/inbox/read", { body: { event_ids: [+row.dataset.ev] } }); } catch {}
    if (matchMedia("(min-width: 1025px)").matches) { IBF.sel = row.dataset.deal; await inboxSplit(); openPane(row.dataset.deal); }
    else location.href = `/studio/deals/${row.dataset.deal}`;
  });
  if (IBF.sel) openPane(IBF.sel);
}
async function openPane(dealId) {
  const pane = $("#ib-pane");
  pane.innerHTML = `<div class="card"><div class="row between"><h3 style="margin:0" id="pane-ttl">Conversation</h3>
    <a class="btn small" href="/studio/deals/${dealId}">${I("external-link")} Open deal</a></div><div id="pane-chat" style="margin-top:10px"><div class="skeleton"></div></div></div>`;
  try { const v = await api(`/api/deals/${dealId}`); $("#pane-ttl").textContent = v.deal.brand_org; } catch {}
  if (typeof Chat !== "undefined") Chat.mount($("#pane-chat"), { base: `/api/deals/${dealId}`, isBrand: false, token: "" });
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
        <a class="card dealcard hover" href="/studio/deals/${d.id}"><div class="row between"><b>${esc(d.brand)}</b>${d.is_demo ? '<span class="pill">Demo</span>' : ""}</div>
          <div class="row between" style="margin-top:6px"><span class="num">${usd(d.total_cents)}</span>${moneyPill(d.money)}</div>
          <div class="tiny muted" style="margin-top:6px">${d.needs_me ? `<b style="color:var(--held)">Needs you</b> · ` : ""}${ago(d.updated_at)}</div></a>`).join("")}</section>`; }).join("")}</div>`;
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
