// Delivery, posting and money out (Phase 6) inside the deal room. Video never goes to the server:
// the browser takes 6–8 still frames (canvas) and uploads small JPEGs.
const Work = (() => {
  let ctx = null;
  async function mount(el, c) {
    ctx = c; el.innerHTML = `<div class="skeleton"></div>`;
    let w;
    try { w = await api(c.url("/work")); } catch (e) { el.innerHTML = ""; return; }
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
          <div class="list">${(d.result.checks || []).map(c => `<div class="line"><span>${c.ok ? "✅" : "⚠️"}</span><div class="grow">${esc(c.check)}
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
      parts.push(`<div class="card"><h3>Delivery check</h3><p class="small">Posted ${esc(p.posted_at || "")} · <a href="${esc(p.post_url)}" target="_blank" rel="noopener">open post</a>
        ${p.result.disclosure_ok === false ? ' · <span class="pill failed">no #ad in caption</span>' : p.result.disclosure_ok ? ' · <span class="pill collected">#ad found</span>' : ""}</p>
        ${gaps.length ? gaps.map(g => gapCard(g)).join("") : `<div class="banner ok">✅ The delivery matches the latest confirmed deal (version ${ctx.V.deal.version}).</div>`}
        ${w.gaps_open ? `<div class="banner bad small" style="margin-top:8px">No money is released until every gap is resolved.</div>` : ""}</div>`);
    }
    // release
    if (w.status === "delivered" || w.status === "completed" || (w.release.items || []).length) {
      const R = w.release.items || [];
      const mine = ctx.IS_BRAND ? "brand" : "creator";
      const waitingMe = R.some(i => i.status === "planned" && i.needs.includes(mine) && !i.approved_by.includes(mine));
      parts.push(`<div class="card"><h3>Release</h3>
        ${R.length ? `<div class="list">${R.map(i => `<div class="line"><div class="grow">${esc(niceNote(i.note))}<div class="tiny muted">needs ${i.needs.join(" + ")} · approved by ${i.approved_by.join(", ") || "nobody yet"}</div></div>
          <div class="amt">${usd(i.amount_cents)}</div>${moneyPill(i.status)}</div>`).join("")}</div>` : `<p class="small muted">Both sides approve, then PayPal collects the held money and pays ${esc(first())} (minus a 10% holdback paid on day N if the post stays live).</p>`}
        ${(w.status === "delivered" && (R.length === 0 || waitingMe) && (!ctx.IS_BRAND || main)) ? `<button class="btn primary block" id="w-release" ${w.gaps_open ? "disabled" : ""}>Approve release</button>` : ""}
        ${w.holdback_release_at ? `<p class="small">Holdback is paid on ${dateStr(w.holdback_release_at)} if the post is still live.${w.post_removed_at ? ` <b>Reported removed ${ago(w.post_removed_at)}: 48 hours to restore.</b>` : ""}</p>` : ""}
        ${main && w.holdback_release_at && !w.post_removed_at ? `<button class="btn small danger" id="w-removed">Report the post removed</button>` : ""}
        ${!ctx.IS_BRAND && w.post_removed_at ? `<button class="btn small primary" id="w-restored">It's live again</button>` : ""}</div>`);
    }
    if (!ctx.IS_BRAND && w.status === "in_progress") parts.push(`<details class="card"><summary>Editor's share (optional)</summary>
      <p class="small muted">Paid by PayPal Payouts from your payment at release.</p>
      <div class="row" style="gap:8px"><input id="w-ed-email" placeholder="editor's PayPal email" class="grow" value="${esc((w.editor || {}).email || "")}">
        <input id="w-ed-pct" type="number" min="1" max="50" value="${(w.editor || {}).pct || 15}" style="max-width:80px"><span>%</span></div>
      <button class="btn small" id="w-ed-save" style="margin-top:8px">Save</button></details>`);
    if (w.status === "completed") {
      parts.push(w.review ? `<div class="card"><h3>Review</h3><p>${"★".repeat(w.review.rating)}${"☆".repeat(5 - w.review.rating)} ${esc(w.review.text || "")}</p></div>`
        : main ? `<div class="card"><h3>How did it go?</h3><div class="stars" id="w-stars">${[1, 2, 3, 4, 5].map(n => `<button data-star="${n}" aria-label="${n} stars">☆</button>`).join("")}</div>
          <textarea id="w-rtext" maxlength="500" placeholder="A short review (shown on ${esc(first())}'s profile)" style="min-height:60px"></textarea>
          <button class="btn primary block" id="w-review" style="margin-top:8px">Leave review</button></div>` : "");
    }
    parts.push(`<p class="small"><a href="/story/${encodeURIComponent(location.pathname.split("/").pop())}${ctx.IS_BRAND ? "?b=1" : ""}">Open the money story →</a></p>`);
    return `<div class="stack">${parts.join("")}</div>`;
  }
  function draftPill(d) { return d.result.status === "approved" ? `<span class="pill collected">Approved${d.result.silent ? " (silent)" : ""}</span>` : `<span class="pill waiting">Waiting for review</span>`; }
  function niceNote(n) { return (n || "").replace("release:capture of", "Collect from hold").replace("release:", "").replace("holdback:", "Holdback: "); }
  function gapCard(g) {
    const btn = (r, t, who) => (who === (ctx.IS_BRAND ? "brand" : "creator")) && (!ctx.IS_BRAND || ctx.V.me.role === "brand_main") ? `<button class="btn small" data-gap="${g.id}" data-res="${r}">${t}</button>` : "";
    const done = g.status === "resolved";
    const choices = g.kind === "extra" ? btn("add", `Yes, add ${usd(g.amount_cents)}`, "brand") + btn("free", "Free extra", "creator") + btn("remove", "Remove it", "brand")
      : g.kind === "missing" ? btn("drop", `Remove from the deal (collect ${usd(g.amount_cents)} less)`, "brand") + btn("will_deliver", "I'll deliver it", "creator")
      : btn("accept", "Accept the new date", "brand");
    return `<div class="changecard ${done ? "applied" : ""}" style="margin-top:8px"><div>${esc(g.text)}</div>
      ${done ? `<div class="small">Resolved: ${esc(g.resolution)}</div>` : `<div class="row wrapx" style="gap:8px;margin-top:8px">${choices || '<span class="small muted">Waiting for the other side</span>'}</div>`}
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
    on("w-removed", b => { if (confirm("Report the post as removed? The creator gets 48 hours to restore it.")) go(b, () => api(ctx.url("/removed"), { method: "POST" })); });
    on("w-restored", b => go(b, () => api(ctx.url("/restored"), { method: "POST" }), "Thanks"));
    on("w-ed-save", b => go(b, () => api(ctx.url("/editor"), { body: { email: $("#w-ed-email", el).value, pct: +$("#w-ed-pct", el).value } }), "Saved"));
    let stars = 0;
    $$("[data-star]", el).forEach(s => s.onclick = () => { stars = +s.dataset.star; $$("[data-star]", el).forEach(x => x.textContent = +x.dataset.star <= stars ? "★" : "☆"); });
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
