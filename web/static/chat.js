// Deal chat with inline change cards (Phase 3). Used by deal.html for both sides.
// Needs: api(), esc(), usd(), ago(), toast(), busy(), sheet(), closeSheet() from app.js.
const Chat = (() => {
  let base = "", isBrand = false, token = "", timer = null, lastSig = "", onApplied = null;

  function mount(el, opts) {
    base = opts.base; isBrand = opts.isBrand; token = opts.token || ""; onApplied = opts.onApplied;
    el.innerHTML = `
      <div class="chat card">
        <div class="row between"><h3 style="margin:0">Deal chat</h3><span class="tiny muted" id="chat-state"></span></div>
        <div id="chat-list" class="chat-list" aria-live="polite"></div>
        <div id="chat-ai" class="busy" hidden>Checking the message for deal changes…</div>
        <form id="chat-form" class="composer">
          <button type="button" class="btn small" id="chat-attach" aria-label="Attach">📎</button>
          <textarea id="chat-in" rows="1" maxlength="4000" placeholder="Message… e.g. “Can we add one more Story and post Monday?”"></textarea>
          <button class="btn primary small" id="chat-send">Send</button>
        </form>
        <input type="file" id="chat-file" hidden>
      </div>`;
    $("#chat-form").onsubmit = e => { e.preventDefault(); send(); };
    $("#chat-in").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
    $("#chat-attach").onclick = attachMenu;
    load();
    clearInterval(timer);
    timer = setInterval(() => { if (!document.hidden) load(true); }, 6000);
  }

  async function load(quiet = false) {
    try { draw(await api(`${base}/chat`)); }
    catch (e) { if (!quiet) toast(e.message, "bad", load); }
  }

  function draw(t) {
    const sig = JSON.stringify(t.items.map(i => [i.id || i.at, i.status, i.brand_ok, i.creator_ok]));
    if (sig === lastSig) return;
    const atBottom = isNearBottom();
    lastSig = sig;
    const list = $("#chat-list");
    list.innerHTML = t.items.length ? t.items.map(item).join("") :
      `<div class="empty small">No messages yet. Changes typed here become change cards that both of you confirm.</div>`;
    $$("[data-act]", list).forEach(b => b.onclick = () => act(b));
    $$("[data-payhold]", list).forEach(b => b.onclick = () => busy(b, async () => {
      try { const r = await api(`/api/d/${token}/pay-hold/${b.dataset.payhold}`, { method: "POST" }); location.href = r.approve_url; }
      catch (e) { toast(e.message, "bad"); }
    }));
    $$("[data-quote]", list).forEach(b => b.onclick = () => quoteSheet(b.dataset.quote, b.dataset.who || "", b.dataset.where || "the chat", ""));
    if (atBottom) list.scrollTop = list.scrollHeight;
    $("#chat-state").textContent = t.unread ? `${t.unread} new` : "";
  }
  function isNearBottom() { const l = $("#chat-list"); return !l || l.scrollHeight - l.scrollTop - l.clientHeight < 80; }

  function item(i) {
    if (i.type === "system") return `<div class="sysline">${esc(i.body)} · ${time(i.at)}</div>`;
    if (i.type === "change") return changeCard(i);
    const media = i.media_url ? (i.kind === "image"
      ? `<a href="${mediaUrl(i.media_url)}" target="_blank" rel="noopener"><img class="chat-img" src="${mediaUrl(i.media_url)}" alt="${esc(i.meta.name || "image")}"></a>`
      : `<a class="filechip" href="${mediaUrl(i.media_url)}" target="_blank" rel="noopener">📄 ${esc(i.meta.name || "file")}</a>`) : "";
    return `<div class="bubble ${i.mine ? "mine" : ""}"><div class="tiny muted">${esc(i.mine ? "You" : i.from)} · ${time(i.at)}</div>
      ${i.body ? `<div>${esc(i.body)}</div>` : ""}${media}</div>`;
  }
  function mediaUrl(u) { return isBrand ? `${u}?t=${encodeURIComponent(token)}` : u; }
  function time(iso) { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }

  function changeCard(c) {
    const open = c.status === "previewed" || c.status === "detected";
    const title = c.suggestion ? "💡 Suggestion" : c.kind === "revision" ? "✏️ Revision" : c.kind === "new_work" ? "🆕 New work detected" : "💡 Change detected";
    const status = { applied: "✅ Confirmed by both · applied", rejected: "Rejected", expired: "Expired · the last confirmed version stays" }[c.status] || "";
    const exp = open ? Math.max(0, Math.round((new Date(c.expires_at) - Date.now()) / 3600000)) : 0;
    const iOk = isBrand ? c.brand_ok : c.creator_ok;
    const hold = c.status === "applied" && isBrand && c.pending_hold;
    return `<div class="changecard ${c.status}">
      <div class="row between"><b>${title}</b>${c.source && c.source !== "chat" ? `<span class="pill">${esc(c.source.split(":")[0])}</span>` : ""}</div>
      ${c.suggestion ? `<p class="small muted">From ${esc(c.proposed_by || "a teammate")}. Suggestions can't move money until the brand's main contact proposes them.</p>` : ""}
      <div class="list">${c.lines.map(l => `<div class="line"><div class="grow">${esc(l.label)}
          ${l.source ? `<div class="tiny muted">${esc(l.source)}</div>` : ""}</div>
          <div class="amt">${l.amount_cents ? (l.amount_cents > 0 ? "+" : "−") + usd(Math.abs(l.amount_cents)) : "free"}</div>
          <button class="q" data-quote="${esc(l.quote)}" data-who="${esc(c.proposed_by || "")}" title="The exact words">❝</button></div>`).join("")}</div>
      ${c.conflicts.map(x => `<div class="conflict">⚠️ ${esc(x)}</div>`).join("")}
      ${c.override_reason ? `<div class="tiny muted">Creator's override: “${esc(c.override_reason)}”</div>` : ""}
      <div class="small muted" style="margin-top:6px">${c.untouched} other item${c.untouched === 1 ? "" : "s"} unchanged</div>
      <div class="small"><b>Money:</b> ${c.money.map(esc).join(" · ")}</div>
      ${open ? `<div class="row wrapx" style="margin-top:10px;gap:8px">
          ${c.suggestion ? (isBrand ? `<button class="btn primary small" data-act="propose" data-id="${c.id}">Propose this change</button>` : "")
            : (iOk ? `<span class="pill held">You confirmed</span>` : `<button class="btn primary small" data-act="confirm" data-id="${c.id}" data-conflict="${c.conflicts.length && !isBrand && !c.override_reason ? 1 : 0}">Confirm</button>`)}
          <button class="btn small" data-act="discuss" data-id="${c.id}">Discuss</button>
          <button class="btn small danger" data-act="reject" data-id="${c.id}">Reject</button>
        </div>
        <div class="tiny muted" style="margin-top:6px">${isBrand ? "You" : "Brand"} ${c.brand_ok ? "✅" : "⏳"} · ${isBrand ? "Creator" : "You"} ${c.creator_ok ? "✅" : "⏳"} · expires in ${exp} h</div>`
      : `<div class="small" style="margin-top:6px">${status}</div>`}
      ${hold ? `<button class="btn primary block" style="margin-top:10px" data-payhold="${c.pending_hold.id}">Pay ${usd(c.pending_hold.amount_cents)} hold with PayPal</button>` : ""}
    </div>`;
  }

  async function act(b) {
    const action = b.dataset.act, id = b.dataset.id;
    let reason = null;
    if (action === "confirm" && b.dataset.conflict === "1") {
      reason = prompt("This breaks one of your limits. Give a reason to override it (the brand sees it):");
      if (!reason) return;
    }
    if (action === "discuss") { $("#chat-in").focus(); }
    await busy(b, async () => {
      try {
        const r = await api(`${base}/changes/${id}/${action}`, { body: { reason } });
        lastSig = ""; draw(r);
        if (r.change && r.change.status === "applied") { toast("Confirmed by both · applied"); if (onApplied) onApplied(); }
      } catch (e) { toast(e.message, "bad"); }
    });
  }

  async function send() {
    const text = $("#chat-in").value.trim();
    if (!text) return;
    $("#chat-ai").hidden = false;
    await busy($("#chat-send"), async () => {
      try {
        const r = await api(`${base}/messages`, { body: { body: text } });
        $("#chat-in").value = ""; lastSig = ""; draw(r);
        if (r.ai_error) toast(r.ai_error + " Your message was sent.", "bad");
        else if (r.change) toast("Change card added · confirm it together");
      } catch (e) { toast(e.message, "bad"); }
    });
    $("#chat-ai").hidden = true;
  }

  function attachMenu() {
    sheet(`<h3>Add to the chat</h3><div class="stack">
      <button class="btn block" data-up="image">📷 Photo</button>
      <button class="btn block" data-up="screenshot">🧾 Screenshot of a chat (Amend reads the changes)</button>
      <button class="btn block" data-up="whatsapp">💬 WhatsApp "Export chat" file (.txt)</button>
      <button class="btn block" data-up="file">📄 File (up to 2 MB)</button></div>
      <p class="hint">Only your and ${isBrand ? "the creator's" : "the brand's"} words can change money. Other people's words are ignored.</p>`);
    $$("[data-up]").forEach(b => b.onclick = () => pick(b.dataset.up));
  }
  function pick(kind) {
    const inp = $("#chat-file");
    inp.accept = kind === "image" || kind === "screenshot" ? "image/png,image/jpeg,image/webp" : kind === "whatsapp" ? ".txt,text/plain" : "";
    inp.onchange = async () => {
      const f = inp.files[0]; inp.value = "";
      if (!f) return;
      if (f.size > 2_000_000) { toast("That file is too big (2 MB max)", "bad"); return; }
      closeSheet();
      const data = await new Promise(res => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1]); r.readAsDataURL(f); });
      $("#chat-ai").hidden = kind !== "screenshot" && kind !== "whatsapp";
      try {
        const r = await api(`${base}/upload`, { body: { kind, name: f.name, mime: f.type || "text/plain", data_b64: data } });
        lastSig = ""; draw(r);
        if (r.change) toast("Change card added from the import"); else if (r.ai_error) toast(r.ai_error, "bad");
      } catch (e) { toast(e.message, "bad"); }
      $("#chat-ai").hidden = true;
    };
    inp.click();
  }
  return { mount, reload: () => { lastSig = ""; load(); } };
})();
