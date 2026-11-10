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
    <label>Post link</label><input id="w-url" placeholder="https://www.instagram.com/p/…">
        <label>Posted on</label><input id="w-date" type="date" value="${new Date().toISOString().slice(0, 10)}">
        <label>What you delivered</label>${ctx.V.terms.map(t => `<div class="row between"><span>${esc(t.name)}</span><input type="number" min="0" max="20" value="${t.qty}" data-deliv="${esc(t.code)}" style="max-width:80px"></div>`).join("")}
        <label>Caption as posted</label><textarea id="w-pcap" style="min-height:60px"></textarea>
        <button class="btn primary block" id="w-post" style="margin-top:10px">Submit post for the delivery check</button></div>`);
    }
    if (p) {
      const gaps = p.result.gaps || [];
      ctx._cap = p.result.caption || "";
      parts.push(`<div class="card"><h3>Delivery check</h3><p class="small">Posted ${esc(p.posted_label || fmtDate(p.posted_at) || "")} · <a href="${esc(p.post_url)}" target="_blank" rel="noopener">open post</a>
        ${p.result.disclosure_ok === false ? ` · <span class="pill failed">no ${esc(p.result.disclosure_tag || "#ad")} in caption</span>` : p.result.disclosure_ok ? ` · <span class="pill collected">${esc(p.result.disclosure_tag || "#ad")} found</span>` : ""}</p>
        ${gaps.length ? gaps.map(g => gapCard(g)).join("") : `<div class="banner ok"><i data-lucide='circle-check' aria-hidden='true'></i> The delivery matches the latest confirmed deal (version ${ctx.V.deal.version}).</div>`}
        ${w.gaps_open ? `<div class="banner bad small" style="margin-top:8px">No money is released until every gap is resolved.</div>` : ""}</div>`);
    }
    // release
    const R0 = (w.release && w.release.items) || [], mine0 = ctx.IS_BRAND ? "brand" : "creator";
    const canTap = w.status === "delivered" && (R0.length === 0 || R0.some(i => i.status === "planned" && i.needs.includes(mine0) && !i.approved_by.includes(mine0)))
      && (!ctx.IS_BRAND || main);
    if (w.verdict) parts.push(verdictHtml(w.verdict, canTap));
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
    if (!ctx.IS_BRAND && w.status === "in_progress") parts.push(`<details class="card"><summary>Editor's share (optional)</summary>
      <p class="small muted">Paid by PayPal Payouts from your payment at release.</p>
   <div class="row" style="gap:8px"><input id="w-ed-email" placeholder="editor's PayPal email" class="grow" value="${esc((w.editor || {}).email || "")}">
        <input id="w-ed-pct" type="number" min="1" max="50" value="${(w.editor || {}).pct || 15}" style="max-width:80px"><span>%</span></div>
      <button class="btn small" id="w-ed-save" style="margin-top:8px">Save</button></details>`);
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
          ${c.ai_read ? `<div class="vlab"><span class="vtag ai">AI read</span><span class="small">${c.ai_read.what ? `${esc(c.ai_read.what)}${c.ai_read.quote ? ` <span class="tiny muted">“${esc(c.ai_read.quote)}”</span>` : ""}` : `<span class="muted">${esc(c.ai_read.note || "Not read by AI")}</span>`}</span></div>` : ""}
          <div class="vlab"><span class="vtag code ${c.ok ? "ok" : c.advisory ? "" : "bad"}">Code decided</span><span class="small">${esc(c.decided || ((c.ok ? "Pass: " : "Fail: ") + c.reason))}</span></div>
          ${(c.quotes && c.quotes.length ? c.quotes : c.quote ? [c.quote] : []).map(q => `<div class="tiny muted quote">“${esc(q)}”</div>`).join("")}</div></div>`).join("")}</div>
      <p class="tiny muted" style="margin:6px 0 0">The AI only reads the caption. Code decides every pass or fail against the confirmed deal; the AI never decides money.</p>
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
  // a release line's chip in words for what it is: a collection, a payout, or a holdback still waiting for its day
  function releasePill(i) {
    if (i.kind === "payout" && i.status === "paid") return `<span class="pill collected">Paid</span>`;
    if ((i.note || "").startsWith("holdback:creator") && i.status === "approved") return `<span class="pill held">Scheduled</span>`;
    return moneyPill(i.status);
  }
  function draftPill(d) { return d.result.status === "approved" ? `<span class="pill collected">Approved${d.result.silent ? " (silent)" : ""}</span>` : `<span class="pill waiting">Waiting for review</span>`; }
  function gapCard(g) {
    const btn = (r, t, who) => (who === (ctx.IS_BRAND ? "brand" : "creator")) && (!ctx.IS_BRAND || ctx.V.me.role === "brand_main") ? `<button class="btn small" data-gap="${g.id}" data-res="${r}">${t}</button>` : "";
    const done = g.status === "resolved";
    const choices = g.kind === "extra" ? btn("add", `Yes, add ${usd(g.amount_cents)}`, "brand") + btn("free", "Free extra", "creator") + btn("remove", "Remove it", "brand")
      : g.kind === "missing" ? btn("drop", `Remove from the deal (collect ${usd(g.amount_cents)} less)`, "brand") + btn("will_deliver", "I'll deliver it", "creator")
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
      delivered: Object.fromEntries($$("[data-deliv]", el).map(i => [i.dataset.deliv, +i.value])) } }), "Delivery checked"));
    $$("[data-gap]", el).forEach(b => b.onclick = () => go(b, () => api(ctx.url(`/gaps/${b.dataset.gap}`), { body: { resolution: b.dataset.res } }), "Resolved"));
    on("w-release", b => go(b, () => api(ctx.url("/release/approve"), { method: "POST" }), "Release approved"));
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
