// Delivery, posting and money out (Phase 6) inside the deal room. Video never goes to the server:
// the browser takes 6–8 still frames (canvas) and uploads small JPEGs.
const Work = (() => {
  let ctx = null;
  async function mount(el, c) {
    ctx = c;
    if (!el.firstElementChild) {  // first load: two card-sized placeholders (draft, post) so nothing below jumps
      const card = `<div class="card" style="margin-bottom:12px"><div class="skeleton" style="width:30%;height:18px;margin:4px 0 12px"></div>
        <div class="skeleton" style="height:120px;margin:0"></div></div>`;
      el.innerHTML = `<div aria-busy="true" aria-label="Loading delivery">${card}${card}</div>`;
    }
    let w;
    try { w = await api(c.url("/work")); }
    catch (e) {
      el.innerHTML = `<div class="card" role="alert"><p class="small">Couldn't load the draft and post. ${esc(friendlyError(e))}</p>
        <button class="btn small" id="w-retry">Try again</button></div>`;
      el.querySelector("#w-retry").onclick = () => mount(el, c);
      return;
    }
    el.innerHTML = render(w);
    bind(el, w);
  }
  const first = () => ctx.V.creator.name.split(" ")[0];

  function render(w) {
    const parts = [];
    const d = w.draft, p = w.post, brand = ctx.IS_BRAND, main = brand && ctx.V.me.role === "brand_main";
    // draft
    if (w.status === "in_progress" || d) {
      let h = `<div class="card"><div class="row between"><h3 style="margin:0">Draft</h3>${d ? draftPill(d) : ""}</div>`;
      if (d) {
        h += `<div class="frames">${d.frames.map(f => `<figure><img src="${ctx.IS_BRAND ? f.url + "?t=" + encodeURIComponent(location.pathname.split("/")[2]) : f.url}" alt="frame at ${f.t.toFixed(1)} s"><figcaption>${f.t.toFixed(1)} s</figcaption></figure>`).join("")}</div>
          <div class="list">${(d.result.checks || []).map(c => `<div class="line"><span>${c.ok ? "<i data-lucide='circle-check' aria-hidden='true'></i>" : "<i data-lucide='triangle-alert' aria-hidden='true'></i>"}</span><div class="grow">${esc(c.check)}
            <div class="tiny muted">${esc(c.note || "")}${c.time != null ? ` · frame at ${c.time.toFixed(1)} s` : ""}</div></div></div>`).join("")}</div>
          ${d.result.caption ? `<p class="small muted">Caption: ${esc(d.result.caption)}</p>` : ""}`;
        if (main && d.result.status === "submitted") h += `<div class="row" style="gap:8px;margin-top:8px"><button class="btn primary grow" id="w-approve">Approve draft</button>
            <button class="btn grow" id="w-feedback">Ask for changes</button></div>
          ${w.silent_approval_days ? `<p class="hint">If you don't review within ${w.silent_approval_days} days, the draft counts as approved (agreed at acceptance).</p>` : ""}`;
      } else if (!brand) h += `<p class="small muted">Upload the draft video: Amend takes 6–8 still frames in your browser and checks them against the brief.</p>`;
      else h += `<p class="small muted">Waiting for ${esc(first())}'s draft.</p>`;
   if (!brand && w.status === "in_progress") h += `<div class="stack" style="margin-top:8px"><textarea id="w-caption" placeholder="Caption (include #ad)" style="min-height:60px"></textarea>
          <button class="btn ${d ? "" : "primary"} block" id="w-upload">${d ? "Upload a new draft" : "Upload draft video"}</button><input type="file" id="w-file" accept="video/*" hidden>
          <div class="hint">Requirements: ${w.requirements.map(esc).join(" · ")}</div></div>`;
      parts.push(h + `</div>`);
    }
    // posting
    if (!brand && w.status === "in_progress" && d && d.result.status === "approved") {
      parts.push(`<div class="card"><h3>Mark posted</h3>
    <label>Post link</label><input id="w-url" placeholder="https://www.instagram.com/reel/…">
        ${w.ig && w.ig.on && !w.ig.demo ? `<label>Your Instagram account</label><input id="w-ig" placeholder="@yourhandle" value="${esc(w.ig.handle ? "@" + w.ig.handle : "")}">
        <div class="hint">Amend reads the post from Instagram (professional accounts) and checks it against the latest confirmed deal. Stories can't be read for other accounts, so they come from what you enter.</div>` : ""}
        <label>Posted on</label><input id="w-date" type="date" value="${new Date().toISOString().slice(0, 10)}">
        <label>What you delivered</label>${ctx.V.terms.map(t => `<div class="row between"><span>${esc(t.name)}</span><input type="number" min="0" max="20" value="${t.qty}" data-deliv="${esc(t.code)}" style="max-width:80px"></div>`).join("")}
        <label>Caption as posted</label><textarea id="w-pcap" style="min-height:60px"></textarea>
        <button class="btn primary block" id="w-post" style="margin-top:10px">Submit post for the delivery check</button></div>`);
    }
    if (p) {
      const gaps = p.result.gaps || [];
      ctx._cap = p.result.caption || ""; ctx._igFound = (p.result.ig || {}).status === "found";
      const ig = p.result.ig;
      const igLine = !ig ? "" : ig.status === "found"
        ? `<div class="banner ok small" style="margin-top:8px">${icon("camera")} Read from Instagram: ${esc(igKind(ig))} · posted ${esc(ig.posted_label)} · <a href="${esc(ig.permalink)}" target="_blank" rel="noopener">@${esc(ig.handle)}</a></div>`
        : `<div class="banner small" style="margin-top:8px">${icon("info")} ${esc(ig.message)}. The check uses what ${esc(first())} entered.</div>`;
      const canRe = w.status === "delivered" && w.ig && w.ig.on && (!ctx.IS_BRAND || main);
      ctx._igLine = igLine + (canRe ? `<button class="btn small" id="w-recheck" style="margin-top:8px">${icon("refresh-cw")} Re-check on Instagram</button>` : "");
      parts.push(`<div class="card"><h3>Delivery check</h3><p class="small">Posted ${esc(p.posted_label || fmtDate(p.posted_at) || "")} · <a href="${esc(p.post_url)}" target="_blank" rel="noopener">open post</a>
        ${p.result.disclosure_ok === false ? ` · <span class="pill failed">no ${esc(p.result.disclosure_tag || "#ad")} in caption</span>` : p.result.disclosure_ok ? ` · <span class="pill collected">${esc(p.result.disclosure_tag || "#ad")} found</span>` : ""}</p>
        ${ctx._igLine || ""}
        ${gaps.length ? gaps.map(g => gapCard(g)).join("") : `<div class="banner ok"><i data-lucide='circle-check' aria-hidden='true'></i> The delivery matches the latest confirmed deal (version ${ctx.V.deal.version}).</div>`}
        ${w.gaps_open ? `<div class="banner bad small" style="margin-top:8px">No money is released until every gap is resolved.</div>` : ""}</div>`);
    }
    // release
    const R0 = (w.release && w.release.items) || [], mine0 = ctx.IS_BRAND ? "brand" : "creator";
    const canTap = w.status === "delivered" && (R0.length === 0 || R0.some(i => i.status === "planned" && i.needs.includes(mine0) && !i.approved_by.includes(mine0)))
      && (!ctx.IS_BRAND || main);
    const bh = bonusHtml(w.bonus, w, main);
    if (bh) parts.unshift(bh);
    if (w.verdict) parts.push(verdictHtml(w.verdict, canTap));
    const sh = settleHtml(w.settle, main);
    if (sh) parts.push(sh);
    if (w.results) parts.push(resultsHtml(w.results));
    if (w.competitor && w.competitor.state !== "no_exclusivity") parts.push(competitorHtml(w.competitor));
    if (w.status === "delivered" || w.status === "completed" || (w.release.items || []).length) {
      const R = w.release.items || [];
      const mine = ctx.IS_BRAND ? "brand" : "creator";
      const waitingMe = R.some(i => i.status === "planned" && i.needs.includes(mine) && !i.approved_by.includes(mine));
      parts.push(`<div class="card"><h3>Release</h3>
        ${R.length ? `<div class="list">${R.map(i => `<div class="line"><div class="grow">${esc(i.label)}${i.approval ? `<div class="tiny muted">${esc(i.approval)}</div>` : ""}</div>
          <div class="amt">${usd(i.amount_cents)}</div>${releasePill(i)}</div>`).join("")}</div>` : `<p class="small muted">Both sides approve, then PayPal collects the held money and pays ${esc(first())} (minus a 10% holdback, paid ${w.release.holdback_date ? "on " + fmtDate(w.release.holdback_date) : "30 days after the post"} if the post is still live).</p>`}
        ${!w.verdict && (w.status === "delivered" && (R.length === 0 || waitingMe) && (!ctx.IS_BRAND || main)) ? `<button class="btn primary block" id="w-release" ${w.gaps_open ? "disabled" : ""}>Approve release</button>` : ""}
        ${w.post_removed_at ? `<p class="small"><b>Reported removed ${ago(w.post_removed_at)}: 48 hours to restore, or the holdback returns to the brand.</b></p>` : ""}
        ${main && w.holdback_release_at && !w.post_removed_at ? `<button class="btn small danger" id="w-removed">Report the post removed</button>` : ""}
        ${!ctx.IS_BRAND && w.post_removed_at ? `<button class="btn small primary" id="w-restored">It's live again</button>` : ""}</div>`);
    }
    if (!ctx.IS_BRAND && w.team) parts.push(teamHtml(w.team, w));
    if (w.status === "completed") {
      parts.push(w.review ? `<div class="card"><h3>Review</h3><p>${"<i data-lucide='star' aria-hidden='true'></i>".repeat(w.review.rating)}${"<i data-lucide='star' aria-hidden='true'></i>".repeat(5 - w.review.rating)} ${esc(w.review.text || "")}</p></div>`
    : main ? `<div class="card"><h3>How did it go?</h3><div class="stars" id="w-stars">${[1, 2, 3, 4, 5].map(n => `<button data-star="${n}" aria-label="${n} stars"><i data-lucide='star' aria-hidden='true'></i></button>`).join("")}</div>
     <textarea id="w-rtext" maxlength="500" placeholder="A short review (shown on ${esc(first())}'s profile)" style="min-height:60px"></textarea>
          <button class="btn primary block" id="w-review" style="margin-top:8px">Leave review</button></div>` : "");
    }
    parts.push(`<p class="small"><a href="/story/${encodeURIComponent(location.pathname.split("/").pop())}${ctx.IS_BRAND ? "?b=1" : ""}">Open the money story →</a></p>`);
    return `<div class="stack">${parts.join("")}</div>`;
  }
  // Signed delivery verdict: pass/fail per check (reason + the confirmed deal's own words), the post hash, the proposed
  // release, and the exact PayPal calls next to the Confirm button. Nothing moves until a person taps it.
  function verdictHtml(v, canTap) {
    const pass = v.result === "pass", P = v.proposal;
    const meTapped = ctx.IS_BRAND ? v.confirmed_brand_at : v.confirmed_creator_at;
    const other = ctx.IS_BRAND ? v.confirmed_creator_at : v.confirmed_brand_at;
    const otherName = ctx.IS_BRAND ? first() : "the brand";
    const row = (l, c) => c ? `<div class="line"><span class="grow">${l}</span><b class="amt">${usd(c)}</b></div>` : "";
    return `<div class="card verdict ${pass ? "pass" : "fail"}"><div class="row between"><h3 style="margin:0">${icon(pass ? "badge-check" : "badge-x")} Delivery verdict</h3>
        <span class="pill ${pass ? "collected" : "failed"}">${pass ? "Pass" : "Fail"}</span></div>
      <p class="tiny muted" style="margin:4px 0 8px">Checked by code against the confirmed version ${v.version} · signed by Amend (Ed25519, key ${esc(v.key_id || "")}) ·
        verdict <code>${esc(v.hash.slice(0, 12))}…</code> · post <code>${esc(v.post.hash.slice(0, 12))}…</code> ·
        <a href="${ctx.url("/verdict.json")}" target="_blank" rel="noopener">signed JSON</a></p>
      <div class="list">${v.checks.map(c => `<div class="line"><span>${icon(c.ok ? "circle-check" : c.advisory ? "info" : "triangle-alert")}</span><div class="grow">
          <b>${esc(c.check)}</b>${c.advisory ? ' <span class="tiny muted">(advisory: doesn\'t hold money)</span>' : ""}
          ${c.ai_read ? `<div class="vlab"><span class="vtag ai">${c.ai_read.source === "instagram" ? "Instagram read" : c.ai_read.source === "amend" ? "Amend record" : c.ai_read.source === "creator" ? `From ${esc(first())}` : "AI read"}</span><span class="small">${c.ai_read.what ? `${esc(c.ai_read.what)}${c.ai_read.quote ? ` <span class="tiny muted">“${esc(c.ai_read.quote)}”</span>` : ""}` : `<span class="muted">${esc(c.ai_read.note || "Not read by AI")}</span>`}</span></div>` : ""}
          <div class="vlab"><span class="vtag code ${c.ok ? "ok" : c.advisory ? "" : "bad"}">Code decided</span><span class="small">${esc(c.decided || ((c.ok ? "Pass: " : "Fail: ") + c.reason))}</span></div>
          ${(c.quotes && c.quotes.length ? c.quotes : c.quote ? [c.quote] : []).map(q => `<div class="tiny muted quote">“${esc(q)}”</div>`).join("")}</div></div>`).join("")}</div>
      <p class="tiny muted" style="margin:6px 0 0">${v.checks.some(c => c.ai_read && c.ai_read.source === "instagram") ? "The post's type, time and caption were read from Instagram." : "The AI only reads the caption."} Code decides every pass or fail against the confirmed deal; the AI never decides money.</p>
      ${pass && P ? `<div class="verdict-go"><div class="verdict-prop"><div class="tiny muted">Proposed release</div>
          ${row("PayPal collects", P.capture_cents)}${row(`Paid to ${esc(first())}`, P.creator_cents)}${row("Owed from a past refund", P.owed_deducted_cents)}
          ${row("Editor's share", P.editor_cents)}${row("Holdback (paid later if the post stays live)", P.holdback_cents)}
          ${row(ctx.IS_BRAND ? "Unused hold back to you" : "Unused hold back to the brand", P.released_back_cents)}</div>
        <div class="verdict-calls"><div class="tiny muted">PayPal calls on Confirm</div><ol class="tiny">${v.paypal_calls.map(c =>
          `<li><code>${esc(c.call)}</code> ${usd(c.cents)} · ${esc(c.what)}${c.later ? " <i>(later)</i>" : ""}</li>`).join("")}</ol>
          ${canTap && !meTapped ? `<button class="btn primary block" id="w-verdict" data-hash="${esc(v.hash)}">Confirm verdict and release</button>
            <p class="hint">Your tap approves exactly these calls. ${other ? `${esc(otherName)} already confirmed, so PayPal runs them now.` : `PayPal runs them once ${esc(otherName)} confirms too.`}</p>`
          : meTapped ? `<p class="small">${icon("circle-check")} You confirmed${other ? "" : `. Waiting for ${esc(otherName)}.`}</p>` : ""}</div></div>`
      : `<p class="small" style="margin-top:8px">${icon("lock")} No money moves on a failed verdict. Resolve what it flags and a new verdict is signed.</p>`}</div>`;
  }
  // Settle before a dispute: the AI summarises both sides (quoted), code proposes the split, both tap, then PayPal.
  function settleHtml(s, main) {
    if (!s || (!s.why && !s.current)) return "";
    const can = !ctx.IS_BRAND || main;
    const c = s.current, sp = (c && c.split) || s.preview;
    const lines = sp ? `<div class="list">${sp.lines.map(l => `<div class="line"><div class="grow small"><b>${esc(l.name)}</b>
        ${l.licence ? `<span class="muted">· ${l.creator_cents ? "paid, because something was delivered" : "not paid: nothing was delivered"}</span>`
          : `<span class="muted">· delivered ${l.delivered} of ${l.agreed}</span>`}${l.quote ? `<div class="tiny muted quote">“${esc(l.quote)}”</div>` : ""}</div>
        <div class="amt small">${l.creator_cents ? `${usd(l.creator_cents)} to ${esc(first())}` : ""}${l.brand_cents ? `<div class="tiny muted">${usd(l.brand_cents)} back</div>` : ""}</div></div>`).join("")}</div>
      <p class="small" style="margin:8px 0 0"><b>${usd(sp.creator_cents)} to ${esc(first())} · ${usd(sp.brand_cents)} back to the brand</b> <span class="tiny muted">(worked out by code from what was delivered vs version ${ctx.V.deal.version})</span></p>` : "";
    if (!c) return `<div class="card"><h3>${icon("scale")} Settle before a dispute</h3>
      <p class="small muted">This deal has ${esc(s.why)}. Instead of a PayPal dispute, settle it here: the AI summarises each side in their own words, code proposes a split from what was delivered, and nothing moves until you both confirm.</p>
      ${lines}${can ? `<button class="btn block" id="w-settle" style="margin-top:8px">Propose this settlement</button>` : ""}</div>`;
    const side = x => x ? `<div class="small"><b>${esc(x.label)}:</b> ${esc(x.v.summary)}${(x.v.quotes || []).map(q => `<div class="tiny muted quote">“${esc(q)}”</div>`).join("")}</div>` : "";
    const sm = c.summary || {};
    const meTapped = ctx.IS_BRAND ? c.confirmed_brand_at : c.confirmed_creator_at;
    const other = ctx.IS_BRAND ? c.confirmed_creator_at : c.confirmed_brand_at;
    return `<div class="card settle"><div class="row between"><h3 style="margin:0">${icon("scale")} Settlement</h3><span class="pill ${c.status === "settled" ? "collected" : "waiting"}">${c.status === "settled" ? "Settled" : "Proposed"}</span></div>
      ${sm.brand || sm.creator ? `<div class="stack" style="margin-top:8px;gap:6px"><div class="tiny muted">Each side, summarised by the AI (their own words quoted; no blame, no money)</div>
        ${side(sm.brand && { label: "The brand", v: sm.brand })}${side(sm.creator && { label: first(), v: sm.creator })}</div>` : sm.note ? `<p class="tiny muted">${esc(sm.note)}</p>` : ""}
      ${lines}
      ${c.status === "settled" ? `<p class="small" style="margin-top:8px">${icon("circle-check")} Both confirmed. PayPal collected ${usd(c.split.creator_cents)} from the hold (the rest went back to the brand) and paid ${esc(first())}.</p>`
        : can && !meTapped ? `<button class="btn primary block" id="w-settle-ok" data-hash="${esc(c.hash)}" style="margin-top:8px">Confirm this settlement</button>
          <p class="hint">PayPal then collects ${usd(c.split.creator_cents)} from the hold (final_capture: the rest goes back to the brand) and pays ${esc(first())}. ${other ? "The other side already confirmed." : "Nothing moves until both of you confirm; it never happens on silence."}</p>`
        : `<p class="small" style="margin-top:8px">${icon("circle-check")} You confirmed. Waiting for the other side; nothing moves until they do.</p>`}</div>`;
  }
  // Team splits: up to 4 people, shares of her payout (≤ 50%), one Payouts batch, a receipt link each, the refund rule.
  function teamHtml(t, w) {
    const m = t.members || [];
    const pill = p => !p ? "" : p.status === "paid" ? '<span class="pill collected">Paid</span>' : p.status === "failed" ? '<span class="pill failed">Failed</span>'
      : p.status === "sent" ? '<span class="pill held">Sent to PayPal</span>' : moneyPill(p.status);
    const list = m.length ? `<div class="list">${m.map(x => `<div class="line"><div class="grow"><b>${esc(x.role)}</b> · ${x.pct}%
        <div class="tiny muted">${esc(x.email)} · <a href="${esc(x.receipt)}" target="_blank" rel="noopener">receipt link</a></div></div>
        ${x.payout ? `<div class="amt">${usd(x.payout.amount_cents)}</div>${pill(x.payout)}${x.payout.status === "failed" ? `<button class="btn small" data-retry="${esc(x.payout.id)}">Retry</button>` : ""}` : ""}</div>`).join("")}</div>`
      : `<p class="small muted">No team on this deal. Add an editor, a photographer or anyone else you pay from this deal.</p>`;
    const rule = t.refund_rule === "shared" ? "Refunds after payout are shared by share (each person's future Amend payouts)" : "You cover refunds after payout (as today)";
    if (t.locked || !["accepted", "in_progress", "delivered"].includes(w.status)) return `<div class="card"><h3>${icon("users")} Team</h3>${list}
      <p class="tiny muted" style="margin:6px 0 0">${esc(rule)}. Paid with you in one PayPal Payouts batch.</p></div>`;
    const row = (x, i) => `<div class="team-row"><input class="t-role" placeholder="Role, e.g. Editor" value="${esc((x || {}).role || "")}" aria-label="Role ${i + 1}">
      <input class="t-email" type="email" placeholder="PayPal email" value="${esc((x || {}).email || "")}" aria-label="PayPal email ${i + 1}">
      <input class="t-pct" type="number" min="1" max="50" placeholder="%" value="${(x || {}).pct || ""}" aria-label="Share ${i + 1}"></div>`;
    return `<details class="card" ${m.length ? "open" : ""}><summary><b>${icon("users")} Team</b> <span class="small muted">(optional · up to 4 people)</span></summary>
      ${list}
      <p class="small muted" style="margin:8px 0 4px">Shares are a % of your payout (the deal minus the holdback), ${t.total_pct ? `now ${t.total_pct}% in all, ` : ""}up to 50% in all.
        Everyone is paid with you in one PayPal Payouts batch, and each person gets a receipt link (no login).</p>
      <div id="w-team">${[0, 1, 2, 3].map(i => row(m[i], i)).join("")}</div>
      <label style="margin-top:8px">If the brand gets a refund after you're paid</label>
      <select id="w-team-rule"><option value="creator" ${t.refund_rule !== "shared" ? "selected" : ""}>I cover refunds (default)</option>
        <option value="shared" ${t.refund_rule === "shared" ? "selected" : ""}>Shared by share: each person's future payouts are reduced by their share</option></select>
      <button class="btn small primary" id="w-team-save" style="margin-top:8px">Save team</button></details>`;
  }
  // Performance bonus: held by PayPal, read from Instagram insights on day D, decided by code, both tap.
  function bonusHtml(b, w, main) {
    const canOffer = ctx.IS_BRAND && main && ["accepted", "in_progress"].includes(ctx.V.deal.status) && !ctx.V.deal.posted_at;
    const n = v => v == null ? "–" : Number(v).toLocaleString("en-US");
    const rules = `<p class="tiny muted" style="margin:6px 0 0">Held by PayPal as its own hold. On day D after the post, Amend reads the views from Instagram insights and code decides. No screenshots as proof: if Instagram can't read the views by day D + 2, you both decide by hand. If neither of you acts by day 7 after the deadline, the ${b ? usd(b.amount_cents) : "bonus"} goes back to the brand. Both of you confirm before PayPal moves it.</p>`;
    if (!b || b.status === "withdrawn") {
      if (!canOffer) return "";
      return `<details class="card"><summary><b>${icon("trophy")} Add a performance bonus</b> <span class="small muted">(optional)</span></summary>
        <div class="grid3" style="gap:8px;margin-top:8px">
          <label>Views target<input id="w-bn-t" type="number" min="1000" step="1000" value="50000"></label>
          <label>Bonus (USD)<input id="w-bn-a" type="number" min="10" step="10" value="150"></label>
          <label>Read on day<input id="w-bn-d" type="number" min="1" max="21" value="7"></label></div>
        ${rules}<button class="btn primary block" id="w-bn-offer" style="margin-top:8px">Offer the bonus to ${esc(first())}</button></details>`;
    }
    const head = `<div class="row between"><h3 style="margin:0">${icon("trophy")} Performance bonus</h3>${bonusPill(b)}</div>
      ${b.tiers && b.tiers.length > 1 ? `<div class="list" style="margin-top:6px">${b.tiers.map(t => `<div class="line"><span class="grow small">at ${n(t.at)} views</span><b class="amt">+${usd(t.cents)}</b>
        ${b.tier && b.tier.at === t.at ? '<span class="pill collected">reached</span>' : ""}</div>`).join("")}</div>
        <p class="tiny muted" style="margin:4px 0 0">The highest tier reached is paid; read on day ${b.read_day} after posting.</p>`
      : `<p class="small" style="margin:6px 0 0"><b>${esc(b.terms)}</b></p>`}
      ${b.via_mandate ? `<p class="tiny muted" style="margin:4px 0 0">${icon("pen-line")} Pre-signed in ${esc(b.brand)}'s mandate <code>${esc(b.via_mandate.slice(0, 12))}…</code>: only ${esc(first())} taps to release it.</p>` : ""}`;
    let body = "";
    if (b.status === "offered") body = ctx.IS_BRAND ? `<p class="small muted">Waiting for ${esc(first())} to confirm.</p>`
      : `<button class="btn primary block" id="w-bn-confirm" style="margin-top:8px">Confirm the bonus</button><p class="hint">Then ${esc(b.brand)} holds ${usd(b.amount_cents)} with PayPal.</p>`;
    else if (b.status === "agreed") {
      const held = b.hold && b.hold.status === "authorized";
      body = `<p class="small" style="margin-top:6px">${held ? `${icon("lock")} ${usd(b.amount_cents)} held by PayPal` : `Waiting for ${esc(b.brand)} to hold ${usd(b.amount_cents)} with PayPal`}
        ${b.due ? ` · read on <b>${esc(fmtDate(b.due))}</b>` : " · read on day " + b.read_day + " after the post"}</p>
        ${b.hold_too_short ? `<div class="banner bad small">The PayPal hold expires before day ${b.read_day}: PayPal holds last 29 days.</div>` : ""}
        ${b.last_try ? `<p class="tiny muted">Last try: ${esc(b.last_try.why || "")}. Amend tries again; after day ${b.read_day} + 2 with no reading, you both decide by hand.</p>` : ""}
        ${held && b.due && new Date(b.due) <= new Date() ? `<button class="btn small" id="w-bn-read" style="margin-top:6px">${icon("refresh-cw")} Read from Instagram now</button>` : ""}`;
    } else if (b.status === "unverifiable") {
      const mine = (b.by_hand || {})[ctx.IS_BRAND ? "brand" : "creator"], theirs = (b.by_hand || {})[ctx.IS_BRAND ? "creator" : "brand"];
      const label = c => c === "release" ? `release it back to ${esc(b.brand)}` : `pay ${usd(+c.slice(4))}`;
      body = `<div class="banner bad small" style="margin-top:8px">${icon("circle-alert")}<div><b>Results can't be verified from Instagram.</b>${b.reading && b.reading.why ? ` <span>Why: ${esc(b.reading.why)}.</span>` : ""}</div></div>
        <p class="small" style="margin:6px 0 0">You can agree by hand: you both pick the same choice, then PayPal runs it. Screenshots aren't proof here. If you haven't agreed by <b>${esc(fmtDate(b.hand_deadline))}</b>, the bonus hold goes back to ${esc(b.brand)}.</p>
        ${theirs ? `<p class="small">${ctx.IS_BRAND ? esc(first()) : esc(b.brand)} picked: <b>${label(theirs)}</b></p>` : ""}
        ${mine ? `<p class="small">You picked: <b>${label(mine)}</b>${theirs && theirs !== mine ? " (different: nothing moves until you both pick the same)" : ""}</p>` : ""}
        ${!ctx.IS_BRAND || main ? `<div class="row wrapx" style="gap:8px;margin-top:8px">${(b.choices || []).map(c => `<button class="btn small ${mine === "pay:" + c ? "primary" : ""}" data-bn-hand="pay:${c}">Pay ${usd(c)}</button>`).join("")}
          <button class="btn small ${mine === "release" ? "primary" : ""}" data-bn-hand="release">Release it back</button></div>` : ""}`;
    } else {
      const r = b.reading || {};
      const met = b.status === "met" || b.status === "paid", decided = ["met", "missed", "unproven"].includes(b.status);
      const meTapped = ctx.IS_BRAND ? b.confirmed_brand_at : b.confirmed_creator_at;
      const pay = b.tier ? b.tier.cents : b.amount_cents;
      body = `<div class="vlab" style="margin-top:8px"><span class="vtag ai">Instagram read</span><span class="small">${r.views != null ? `${n(r.views)} views` : esc(r.why || "no reading")}
          ${r.fetched_at ? ` <span class="tiny muted">· ${esc(r.source || "Instagram insights")} · ${esc(ago(r.fetched_at))}</span>` : ""}</span></div>
        <div class="vlab"><span class="vtag code ${met ? "ok" : "bad"}">Code decided</span><span class="small">${b.status === "unproven" ? "Not proven: no Instagram reading, so it goes back to the brand"
          : met ? `Met: ${n(r.views)} ≥ ${n(b.tier ? b.tier.at : b.threshold)} views${b.tiers && b.tiers.length > 1 ? ` · tier +${usd(pay)}` : ""}` : `Missed: ${n(r.views)} < ${n(b.threshold)} views`}</span></div>
        ${b.status === "paid" ? `<p class="small" style="margin:6px 0 0">${icon("circle-check")} PayPal collected ${usd(pay)} from the bonus hold and paid ${esc(first())} by Payouts${pay < b.amount_cents ? `; ${usd(b.amount_cents - pay)} went back to ${esc(b.brand)}` : ""}.</p>`
          : b.status === "released" ? `<p class="small" style="margin:6px 0 0">${icon("undo-2")} The ${usd(b.amount_cents)} bonus hold was voided: all of it went back to ${esc(b.brand)}.</p>` : ""}
        <p class="tiny muted" style="margin:6px 0 0" ${decided ? "" : "hidden"}>PayPal on confirm: ${met ? `collect ${usd(pay)} from the ${usd(b.amount_cents)} bonus hold (final_capture${pay < b.amount_cents ? `: ${usd(b.amount_cents - pay)} goes back to ${esc(b.brand)}` : ""}), then pay ${esc(first())} by Payouts` : `void the ${usd(b.amount_cents)} bonus hold: all of it goes back to ${esc(b.brand)}`}</p>
        ${decided && !meTapped && (!ctx.IS_BRAND || main) ? `<button class="btn primary block" id="w-bn-tap" data-hash="${esc(b.decision_hash)}" style="margin-top:8px">${met ? `Confirm: pay the ${usd(pay)} bonus` : "Confirm: release the bonus hold back"}</button>`
          : decided ? `<p class="small">${icon("circle-check")} ${ctx.IS_BRAND && b.via_mandate ? "Pre-signed in your mandate" : "You confirmed"}. Waiting for ${ctx.IS_BRAND ? esc(first()) : esc(b.brand)}.</p>` : ""}`;
    }
    return `<div class="card bonus">${head}${body}${b.status === "offered" || b.status === "agreed" ? rules : ""}</div>`;
  }
  function bonusPill(b) {
    return { offered: '<span class="pill waiting">Offered</span>', agreed: b.hold && b.hold.status === "authorized" ? '<span class="pill held">Held</span>' : '<span class="pill waiting">Agreed</span>',
      met: '<span class="pill collected">Met</span>', missed: '<span class="pill failed">Missed</span>', unproven: '<span class="pill failed">Not proven</span>',
      unverifiable: '<span class="pill waiting">Can\'t be verified</span>', paid: '<span class="pill collected">Paid</span>', released: '<span class="pill">Released back</span>' }[b.status] || "";
  }
  // Results report: Instagram's numbers (with their source and time) and the cost per 1,000 views, worked out by code.
  const srcLine = (src, at, stale) => `<p class="tiny muted" style="margin:6px 0 0">${icon("clock")} ${esc(src)} · updated ${esc(ago(at))}${stale ? ' <span class="pill waiting">Stale: older than 7 days</span>' : ""}</p>`;
  function resultsHtml(r) {
    const n = v => v == null ? "–" : Number(v).toLocaleString("en-US");
    const tools = `<div class="row wrapx" style="gap:8px;margin-top:10px">${r.state !== "no_post" && r.state !== "not_connected" ? `<button class="btn small" id="w-res-refresh">${icon("refresh-cw")} Refresh</button>` : ""}
      ${r.state === "ok" ? `<a class="btn small" href="${ctx.url("/results.csv")}" download>${icon("download")} Download CSV</a>` : ""}</div>`;
    if (r.state !== "ok") return `<div class="card"><h3>${icon("chart-column")} Results</h3><p class="small muted">${esc(r.message)}</p>${tools}</div>`;
    return `<div class="card results"><div class="row between"><h3 style="margin:0">${icon("chart-column")} Results</h3>
        ${r.permalink ? `<a class="small" href="${esc(r.permalink)}" target="_blank" rel="noopener">open post</a>` : ""}</div>
      <div class="grid4" style="margin-top:10px">${[["Views", r.views], ["Reach", r.reach], ["Saves", r.saves], ["Shares", r.shares]]
        .map(([k, v]) => `<div class="tile"><span class="k">${k}</span><span class="v">${n(v)}</span></div>`).join("")}</div>
      <p class="small" style="margin:10px 0 0"><b>Cost per 1,000 views: ${r.cpm_cents == null ? "–" : usd(r.cpm_cents, true)}</b>
        <span class="muted">= ${usd(r.paid_cents)} paid ÷ ${n(r.views)} views × 1,000 (${esc(r.paid_basis)}; worked out by Amend, not the AI)</span></p>
      ${srcLine(r.source, r.fetched_at, r.stale)}
      ${r.next_check ? `<p class="tiny muted" style="margin:2px 0 0">Next check ${esc(fmtDate(r.next_check))} (every 6 h for 7 days after the post, then daily until the usage rights end)</p>` : ""}
      ${tools}</div>`;
  }
  // Exclusivity: recent captions that mention a named competitor (found by code), with the quote and the date.
  function competitorHtml(c) {
    const canSet = ctx.IS_BRAND && ctx.V.me.role === "brand_main";
    const names = (c.names || []).join(", ");
    const form = canSet ? `<div class="row wrapx" style="gap:8px;margin-top:8px"><input id="w-comp" class="grow" placeholder="e.g. Bean Bros, Kahwa House" value="${esc(names)}" aria-label="Competitors the exclusivity covers">
      <button class="btn small" id="w-comp-save">Save</button></div>` : "";
    let body = "";
    if (c.state === "ok") body = (c.flags.length
      ? `<div class="banner bad small" style="margin-top:8px">${icon("triangle-alert")} ${c.flags.length} recent post${c.flags.length === 1 ? "" : "s"} mention a competitor</div>
         <div class="list">${c.flags.map(f => `<div class="line"><div class="grow"><b>${esc(f.competitor)}</b> · ${esc(fmtDate(f.date))}
           <div class="tiny muted quote">“${esc(f.quote)}”</div></div>${f.permalink ? `<a class="small" href="${esc(f.permalink)}" target="_blank" rel="noopener">post</a>` : ""}</div>`).join("")}</div>`
      : `<p class="small" style="margin-top:8px">${icon("circle-check")} No mention of ${esc(names)} in the last ${c.posts} posts.</p>`) + srcLine(c.source, c.fetched_at, c.stale);
    else body = `<p class="small muted" style="margin-top:8px">${esc(c.message || "")}</p>`;
    return `<div class="card"><h3>${icon("shield")} Exclusivity check</h3><p class="tiny muted" style="margin:0">Recent captions are checked by code for the competitors named here. A flag is for people to discuss; it never moves money.</p>${form}${body}</div>`;
  }
  // a release line's chip in words for what it is: a collection, a payout, or a holdback still waiting for its day
  function releasePill(i) {
    if (i.kind === "payout" && i.status === "paid") return `<span class="pill collected">Paid</span>`;
    if ((i.note || "").startsWith("holdback:creator") && i.status === "approved") return `<span class="pill held">Scheduled</span>`;
    return moneyPill(i.status);
  }
  function igKind(ig) { const p = (ig.media_product_type || "").toUpperCase(), t = (ig.media_type || "").toUpperCase();
    return p === "REELS" ? "Reel" : t === "CAROUSEL_ALBUM" ? "Carousel post" : t === "VIDEO" ? "Video post" : t === "IMAGE" ? "Photo post" : "Post"; }
  function draftPill(d) { return d.result.status === "approved" ? `<span class="pill collected">Approved${d.result.silent ? " (silent)" : ""}</span>` : `<span class="pill waiting">Waiting for review</span>`; }
  function gapCard(g) {
    const btn = (r, t, who) => (who === (ctx.IS_BRAND ? "brand" : "creator")) && (!ctx.IS_BRAND || ctx.V.me.role === "brand_main") ? `<button class="btn small" data-gap="${g.id}" data-res="${r}">${t}</button>` : "";
    const done = g.status === "resolved";
    const choices = g.kind === "extra" ? btn("add", `Yes, add ${usd(g.amount_cents)}`, "brand") + btn("free", "Free extra", "creator") + btn("remove", "Remove it", "brand")
      : g.kind === "missing" ? btn("drop", `Remove from the deal (collect ${usd(g.amount_cents)} less)`, "brand") + btn("will_deliver", "I'll deliver it", "creator")
      : g.kind === "disclosure" && ctx._igFound ? (ctx.IS_BRAND ? "" : `<div class="stack grow"><b class="small">${esc(g.fix || "Add #ad at the start of the caption")}</b>
          <span class="small">Edit the caption on Instagram, then tap <b>Re-check on Instagram</b>. Amend reads it again and signs a new verdict.</span></div>`)
      : g.kind === "disclosure" ? (ctx.IS_BRAND ? "" : `<div class="stack grow"><b class="small">${esc(g.fix || "Add #ad at the start of the caption")}</b>
          <textarea id="w-fixcap" style="min-height:60px">${esc(((g.tag || "#ad") + " " + (ctx._cap || "")).trim())}</textarea>
          <button class="btn small primary" id="w-fixcap-go">Update caption and re-check</button><span class="tiny muted">No money is released until the caption has ${esc(g.tag || "#ad")}: the brand's signed mandate requires it.</span></div>`)
      : btn("accept", "Accept the new date", "brand");
    return `<div class="changecard ${done ? "applied" : ""}" style="margin-top:8px"><div>${esc(g.text)}</div>
      ${done ? `<div class="small"><i data-lucide='circle-check' aria-hidden='true'></i> ${esc(g.resolution_text || "Resolved")}</div>` : `<div class="row wrapx" style="gap:8px;margin-top:8px">${choices || '<span class="small muted">Waiting for the other side</span>'}</div>`}
      ${g.note ? `<div class="tiny muted">${esc(g.note)}</div>` : ""}</div>`;
  }

  function bind(el, w) {
  const go = (b, fn, msg) => busy(b, async () => { try { await fn(); if (msg) toast(msg); ctx.reload(); } catch (e) { toast(e.message, "bad"); } });
    const on = (id, fn) => { const b = $("#" + id, el); if (b) b.onclick = () => fn(b); };
    on("w-approve", b => go(b, () => api(ctx.url("/draft/approve"), { method: "POST" }), "Draft approved"));
  on("w-feedback", () => { const i = $("#chat-in"); if (i) { i.focus(); i.placeholder = "What should change? e.g. “Brighter colours” or “Can you also show the kitchen?”"; } });
    on("w-upload", () => $("#w-file", el).click());
    const f = $("#w-file", el);
    if (f) f.onchange = async () => {
      const file = f.files[0]; f.value = ""; if (!file) return;
      const b = $("#w-upload", el);
      await busy(b, async () => {
        try {
          const frames = await extractFrames(file, 7);
          await api(ctx.url("/draft"), { body: { frames, caption: $("#w-caption", el).value } });
     toast("Draft uploaded and checked"); ctx.reload();
    } catch (e) { toast(e.message || "Couldn't read that video", "bad"); }
      });
    };
    on("w-post", b => go(b, () => api(ctx.url("/post"), { body: { post_url: $("#w-url", el).value, posted_on: $("#w-date", el).value, caption: $("#w-pcap", el).value,
      ...($("#w-ig", el) ? { ig_handle: $("#w-ig", el).value } : {}),
      delivered: Object.fromEntries($$("[data-deliv]", el).map(i => [i.dataset.deliv, +i.value])) } }), "Delivery checked"));
    $$("[data-gap]", el).forEach(b => b.onclick = () => go(b, () => api(ctx.url(`/gaps/${b.dataset.gap}`), { body: { resolution: b.dataset.res } }), "Resolved"));
    on("w-release", b => go(b, () => api(ctx.url("/release/approve"), { method: "POST" }), "Release approved"));
    on("w-settle", b => go(b, () => api(ctx.url("/settle"), { method: "POST" }), "Settlement proposed"));
    on("w-settle-ok", b => go(b, () => api(ctx.url("/settle/confirm"), { body: { hash: b.dataset.hash } }), "Confirmed"));
    on("w-team-save", b => go(b, () => api(ctx.url("/team"), { method: "PUT", body: { refund_rule: $("#w-team-rule", el).value,
      members: $$("#w-team .team-row", el).map(r => ({ role: r.querySelector(".t-role").value.trim(), email: r.querySelector(".t-email").value.trim(),
        pct: Math.round(+r.querySelector(".t-pct").value) })).filter(x => x.role || x.email || x.pct) } }), "Team saved"));
    $$("[data-retry]", el).forEach(b => b.onclick = () => go(b, () => api(ctx.url(`/payouts/${b.dataset.retry}/retry`), { method: "POST" }), "Sent to PayPal again"));
    on("w-bn-offer", b => go(b, () => api(ctx.url("/bonus"), { body: { threshold: +$("#w-bn-t", el).value, amount_cents: Math.round(+$("#w-bn-a", el).value * 100), read_day: +$("#w-bn-d", el).value } }), "Bonus offered"));
    on("w-bn-confirm", b => go(b, () => api(ctx.url("/bonus/confirm"), { method: "POST" }), "Bonus confirmed"));
    on("w-bn-read", b => go(b, () => api(ctx.url("/bonus/read"), { method: "POST" }), "Read from Instagram"));
    $$("[data-bn-hand]", el).forEach(b => b.onclick = () => go(b, () => api(ctx.url("/bonus/by-hand"), { body: { choice: b.dataset.bnHand } }), "Saved"));
    on("w-bn-tap", b => go(b, () => api(ctx.url("/bonus/approve"), { body: { decision_hash: b.dataset.hash } }), "Confirmed"));
    on("w-res-refresh", b => go(b, () => api(ctx.url("/results/refresh"), { method: "POST" }), "Refreshed from Instagram"));
    on("w-comp-save", b => go(b, () => api(ctx.url("/competitors"), { body: { names: $("#w-comp", el).value.split(",").map(x => x.trim()).filter(Boolean) } }), "Saved"));
    on("w-recheck", b => go(b, () => api(ctx.url("/post/recheck"), { method: "POST" }), "Re-checked on Instagram"));
    on("w-fixcap-go", b => go(b, () => api(ctx.url("/post/caption"), { body: { caption: $("#w-fixcap", el).value } }), "Caption re-checked"));
    on("w-verdict", b => go(b, () => api(ctx.url("/release/approve"), { body: { verdict_hash: b.dataset.hash } }), "Verdict confirmed"));
  on("w-removed", b => { if (confirm("Report the post as removed? The creator gets 48 hours to restore it.")) go(b, () => api(ctx.url("/removed"), { method: "POST" })); });
    on("w-restored", b => go(b, () => api(ctx.url("/restored"), { method: "POST" }), "Thanks"));
    on("w-ed-save", b => go(b, () => api(ctx.url("/editor"), { body: { email: $("#w-ed-email", el).value, pct: +$("#w-ed-pct", el).value } }), "Saved"));
    let stars = 0;
  $$("[data-star]", el).forEach(s => s.onclick = () => { stars = +s.dataset.star; $$("[data-star]", el).forEach(x => x.classList.toggle("on", +x.dataset.star <= stars)); });
  on("w-review", b => { if (!stars) { toast("Pick 1 to 5 stars", "bad"); return; } go(b, () => api(ctx.url("/review"), { body: { rating: stars, text: $("#w-rtext", el).value } }), "Thanks for the review"); });
  }

  // 6–8 frames from a video, in the browser (canvas), as small JPEGs (~640 px wide)
  function extractFrames(file, n) {
    return new Promise((resolve, reject) => {
      const v = document.createElement("video");
      v.muted = true; v.playsInline = true; v.preload = "auto";
      v.src = URL.createObjectURL(file);
      v.onerror = () => reject(new Error("That video couldn't be read in this browser"));
      v.onloadedmetadata = async () => {
        const dur = v.duration || 1, out = [];
        const c = document.createElement("canvas"), scale = Math.min(1, 640 / (v.videoWidth || 640));
        c.width = Math.round((v.videoWidth || 640) * scale); c.height = Math.round((v.videoHeight || 1136) * scale);
        const g = c.getContext("2d");
        for (let i = 0; i < n; i++) {
          const t = Math.min(dur - 0.05, (dur * (i + 0.5)) / n);
          await new Promise(r => { v.onseeked = r; v.currentTime = t; });
          g.drawImage(v, 0, 0, c.width, c.height);
          let q = 0.7, data = c.toDataURL("image/jpeg", q);
          while (data.length * 0.75 > 280_000 && q > 0.3) { q -= 0.15; data = c.toDataURL("image/jpeg", q); }
          out.push({ data_b64: data.split(",")[1], t });
        }
        URL.revokeObjectURL(v.src);
        resolve(out);
      };
    });
  }
  return { mount };
})();
