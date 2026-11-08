// Deal chat with inline change cards (Phase 3). Used by deal.html for both sides.
// Needs: api(), esc(), usd(), ago(), toast(), busy(), sheet(), closeSheet() from app.js.
const Chat = (() => {
  let base = "", isBrand = false, token = "", timer = null, lastSig = "", onApplied = null;

  function mount(el, opts) {
    base = opts.base; isBrand = opts.isBrand; token = opts.token || ""; onApplied = opts.onApplied;
    // fill: the Inbox gives the chat a fixed-height box; the list scrolls and the composer stays pinned at the bottom
    el.innerHTML = `
      <div class="chat ${opts.fill ? "fill" : "card"}">
        ${opts.fill ? '<span id="chat-state" hidden></span>' : '<div class="row between"><h3 style="margin:0">Deal chat</h3><span class="tiny muted" id="chat-state"></span></div>'}
        <div id="chat-list" class="chat-list" aria-live="polite"></div>
        <div id="chat-ai" class="busy" hidden>Checking the message for deal changes…</div>
        <form id="chat-form" class="composer">
     <button type="button" class="btn small" id="chat-attach" aria-label="Attach"><i data-lucide='paperclip' aria-hidden='true'></i></button>
     <button type="button" class="btn small" id="chat-mic" aria-label="Record a voice note"><i data-lucide='mic' aria-hidden='true'></i></button>
     <textarea id="chat-in" rows="1" maxlength="4000" placeholder="Message…"></textarea>
          <button class="btn primary small" id="chat-send" disabled>Send</button>
        </form>
        <input type="file" id="chat-file" hidden>
      </div>`;
    $("#chat-form").onsubmit = e => { e.preventDefault(); send(); };
    $("#chat-in").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
    $("#chat-in").oninput = () => { $("#chat-send").disabled = !$("#chat-in").value.trim(); };  // nothing to send yet
    $("#chat-attach").onclick = attachMenu;
    $("#chat-mic").onclick = voice;
    if (!window.MediaRecorder) $("#chat-mic").hidden = true;
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
    list.innerHTML = t.items.length ? withDays(t.items) :
      `<div class="empty small">No messages yet. Changes typed here become change cards that both of you confirm.</div>`;
    $$("[data-act]", list).forEach(b => b.onclick = () => act(b));
    $$("[data-nudge]", list).forEach(b => b.onclick = () => busy(b, async () => {
      try { const r = await api(`${base}/nudge/${b.dataset.nudge}`, { body: { answer: b.dataset.ans } }); lastSig = ""; draw(r);
    if (b.dataset.ans === "something") voice(); } catch (e) { toast(e.message, "bad"); }
    }));
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
    if (i.type === "system") return `<div class="sysline">${i.icon ? `<i data-lucide='${i.icon}' aria-hidden='true'></i>` : ""}${esc(i.body)} · ${time(i.at)}</div>`;
    if (i.type === "change") return changeCard(i);
    if (i.type === "brief") return briefCard(i);
    const media = i.media_url ? (i.kind === "image"
      ? `<a href="${mediaUrl(i.media_url)}" target="_blank" rel="noopener"><img class="chat-img" src="${mediaUrl(i.media_url)}" alt="${esc(i.meta.name || "image")}"></a>`
      : `<a class="filechip" href="${mediaUrl(i.media_url)}" target="_blank" rel="noopener"><i data-lucide='file-text' aria-hidden='true'></i> ${esc(i.meta.name || "file")}</a>`) : "";
    if (i.meta && i.meta.nudge) return `<div class="changecard"><b><i data-lucide='phone' aria-hidden='true'></i> ${esc(i.body)}</b><div class="row" style="gap:8px;margin-top:8px">
      <button class="btn small" data-nudge="${i.id}" data-ans="nothing">Nothing changed <i data-lucide='circle-check' aria-hidden='true'></i></button>
      <button class="btn small primary" data-nudge="${i.id}" data-ans="something">Something changed <i data-lucide='mic' aria-hidden='true'></i></button></div></div>`;
    return `<div class="bubble ${i.mine ? "mine" : ""}"><div class="tiny muted">${esc(i.mine ? "You" : i.from)} · ${time(i.at)}</div>
      ${i.body ? `<div>${esc(i.body)}</div>` : ""}${media}${i.meta && i.meta.transcript ? "<div class='tiny muted'><i data-lucide='mic' aria-hidden='true'></i> voice note · transcribed</div>" : ""}</div>`;
  }
  // day headers: Today, Yesterday, or the date
  function dayLabel(iso) {
    const d = new Date(iso), t = new Date(); const k = x => x.toDateString();
    if (k(d) === k(t)) return "Today";
    const y = new Date(t); y.setDate(t.getDate() - 1); if (k(d) === k(y)) return "Yesterday";
    return fmtDate(iso);  // one formatter (app.js): "Sat 21 Nov"
  }
  // the brief as a card: what was asked for, priced from the creator's list, with the words behind each line
  function briefCard(b) {
    return `<div class="briefcard"><div class="bc-head"><span class="bc-ic"><i data-lucide='file-text' aria-hidden='true'></i></span>
        <b>Brief from ${esc(b.from)}</b><span class="tiny muted">${time(b.at)}</span></div>
      <div class="bc-lines">${(b.lines || []).map(l => `<div class="bc-line"><span class="grow">${esc(l.name)}${l.qty > 1 ? ` × ${l.qty}` : ""}</span>
        ${l.quote ? `<button class="q-chip" data-quote="${esc(l.quote)}" data-who="${esc(b.from)}" data-where="the brief" title="The words this came from"><i data-lucide='quote' aria-hidden='true'></i> Quote</button>` : ""}
        <b>${l.amount_cents == null ? '<span class="small muted">On request</span>' : usd(l.amount_cents)}</b></div>`).join("") || '<p class="small muted">No priced lines yet.</p>'}</div>
      <div class="bc-foot">${b.post_date ? `<span><i data-lucide='calendar' aria-hidden='true'></i> Post ${esc(fmtDate(b.post_date))}</span>` : "<span></span>"}<span>Total <b>${b.total_cents == null ? "on request" : usd(b.total_cents)}</b></span></div>
      <div class="bc-src">${isBrand ? "Priced from the creator's list" : "Priced from your list"} · the brand's words are on the Quote chips</div></div>`;  // prices are the creator's, not the brand's
  }
  function withDays(items) {
    let last = "";
    return items.map(i => { const lbl = dayLabel(i.at); const head = lbl !== last ? `<div class="dayline"><span>${esc(lbl)}</span></div>` : ""; last = lbl; return head + item(i); }).join("");
  }
  function mediaUrl(u) { return isBrand ? `${u}?t=${encodeURIComponent(token)}` : u; }
  function time(iso) { return fmtTime(iso); }  // one formatter (app.js): "2:00 PM"

  function changeCard(c) {
    const open = c.status === "previewed" || c.status === "detected";
    const title = c.suggestion ? "<i data-lucide='lightbulb' aria-hidden='true'></i> Suggestion" : c.kind === "revision" ? "<i data-lucide='pencil' aria-hidden='true'></i> Revision" : c.kind === "new_work" ? "<i data-lucide='sparkle' aria-hidden='true'></i> New work detected" : "<i data-lucide='lightbulb' aria-hidden='true'></i> Change detected";
    const status = { applied: "<i data-lucide='circle-check' aria-hidden='true'></i> Confirmed by both · applied", rejected: "Rejected", expired: "Expired · the last confirmed version stays" }[c.status] || "";
    const exp = open ? Math.max(0, Math.round((new Date(c.expires_at) - Date.now()) / 3600000)) : 0;
    const iOk = isBrand ? c.brand_ok : c.creator_ok;
    const hold = c.status === "applied" && isBrand && c.pending_hold;
    return `<div class="changecard ${c.status}">
      <div class="row between"><b>${title}</b>${c.source && c.source !== "chat" ? `<span class="pill">${esc(c.source.split(":")[0])}</span>` : ""}</div>
      ${c.suggestion ? `<p class="small muted">From ${esc(c.proposed_by || "a teammate")}. Suggestions can't move money until the brand's main contact proposes them.</p>` : ""}
      <div class="list">${c.lines.map(l => `<div class="line"><div class="grow">${esc(l.label)}
          ${l.source ? `<div class="tiny muted">${esc(l.source)}${l.second != null ? ` · at ${Math.floor(l.second / 60)}:${String(Math.round(l.second % 60)).padStart(2, "0")} in the call` : ""}</div>` : ""}
          ${l.choices && open && !c.suggestion ? `<div class="row wrapx" style="gap:6px;margin-top:6px">${l.choices.map(ch =>
            `<button class="btn small" data-act="choose" data-qty="${ch.qty}" data-id="${c.id}">${esc(ch.label)} · −${usd(Math.abs(ch.amount_cents))}</button>`).join("")}</div>` : ""}</div>
          <div class="amt cc-amt ${l.amount_cents > 0 ? "plus" : l.amount_cents < 0 ? "minus" : ""}">${l.choices ? "?" : l.amount_cents ? (l.amount_cents > 0 ? "+" : "−") + usd(Math.abs(l.amount_cents)) : "free"}</div>
     <button class="q" data-quote="${esc(l.quote)}" data-who="${esc(c.proposed_by || "")}" title="The exact words" aria-label="Show the exact words"><i data-lucide='quote' aria-hidden='true'></i></button></div>`).join("")}</div>
      ${c.conflicts.map(x => `<div class="conflict"><i data-lucide='triangle-alert' aria-hidden='true'></i> ${esc(x)}</div>`).join("")}
      ${c.override_reason ? `<div class="tiny muted">Creator's override: “${esc(c.override_reason)}”</div>` : ""}
      <div class="cc-foot"><span><i data-lucide='lock' aria-hidden='true'></i> ${c.untouched} other item${c.untouched === 1 ? "" : "s"} unchanged</span>
        <span><i data-lucide='wallet' aria-hidden='true'></i> ${c.money.map(esc).join(" · ")}</span></div>
      ${open ? `<div class="row wrapx" style="margin-top:10px;gap:8px">
          ${c.suggestion ? (isBrand ? `<button class="btn primary small" data-act="propose" data-id="${c.id}">Propose this change</button>` : "")
            : c.lines.some(l => l.choices) ? `<span class="pill waiting">Pick one above · nothing moves until you both confirm it</span>`
            : (iOk ? `<span class="pill held">You confirmed</span>` : `<button class="btn primary small" data-act="confirm" data-id="${c.id}" data-conflict="${c.conflicts.length && !isBrand && !c.override_reason ? 1 : 0}">Confirm</button>`)}
          <button class="btn small" data-act="discuss" data-id="${c.id}">Discuss</button>
          <button class="btn small danger" data-act="reject" data-id="${c.id}">Reject</button>
        </div>
        <div class="tiny muted" style="margin-top:6px">${isBrand ? "You" : "Brand"} ${c.brand_ok ? "<i data-lucide='circle-check' aria-hidden='true'></i>" : "<i data-lucide='hourglass' aria-hidden='true'></i>"} · ${isBrand ? "Creator" : "You"} ${c.creator_ok ? "<i data-lucide='circle-check' aria-hidden='true'></i>" : "<i data-lucide='hourglass' aria-hidden='true'></i>"} · expires in ${exp} h</div>`
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
        const r = await api(`${base}/changes/${id}/${action}`, { body: { reason, qty: b.dataset.qty ? +b.dataset.qty : null } });
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
        $("#chat-in").value = ""; $("#chat-send").disabled = true; lastSig = ""; draw(r);
    if (r.ai_error) toast(r.ai_error + " Your message was sent.", "bad");
    else if (r.change) toast("Change card added · confirm it together");
   } catch (e) { toast(e.message, "bad"); }
    });
    $("#chat-send").disabled = !$("#chat-in").value.trim();  // busy() re-enables it; keep it off while the box is empty
    $("#chat-ai").hidden = true;
  }

  // ---- voice notes (S45): recorded in the browser, transcribed by Groq Whisper ----
  let rec = null, chunks = [];
  async function voice() {
    if (rec) { rec.stop(); return; }
    let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { toast("Microphone not available", "bad"); return; }
    chunks = []; rec = new MediaRecorder(stream);
    rec.ondataavailable = e => chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" }); const mime = (rec.mimeType || "audio/webm").split(";")[0]; rec = null;
   $("#chat-mic").innerHTML = "<i data-lucide='mic' aria-hidden='true'></i>"; $("#chat-ai").hidden = false;
      const data = await new Promise(r => { const f = new FileReader(); f.onload = () => r(String(f.result).split(",")[1]); f.readAsDataURL(blob); });
   try { const r = await api(`${base}/voice`, { body: { data_b64: data, mime } }); lastSig = ""; draw(r); if (r.change) toast("Change card added from your voice note"); }
   catch (e) { toast(e.message, "bad"); }
      $("#chat-ai").hidden = true;
    };
  rec.start(); $("#chat-mic").innerHTML = "<i data-lucide='square' aria-hidden='true'></i> Stop";
  }

  // ---- call upload (S46, S47): consent tick, then tag who is who ----
  // The AI reads only WAV or MP3, and the server never processes audio (512 MB plan), so the browser decodes any
  // recording (m4a, webm, mp3…) and sends 16 kHz mono 16-bit WAV: about 1.9 MB a minute.
  const CALL_MAX_S = 600;
  async function toWav(file, rate = 16000) {
    const AC = window.AudioContext || window.webkitAudioContext;
    const ac = new AC();
    const decoded = await ac.decodeAudioData(await file.arrayBuffer());
    if (ac.close) ac.close();
    if (decoded.duration > CALL_MAX_S) return { seconds: decoded.duration };
    const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * rate), rate);
    const src = off.createBufferSource(); src.buffer = decoded; src.connect(off.destination); src.start();
    const pcm = (await off.startRendering()).getChannelData(0);
    const v = new DataView(new ArrayBuffer(44 + pcm.length * 2));
    const str = (o, s) => [...s].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)));
    str(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
    const b64 = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(String(fr.result).split(",")[1]); fr.readAsDataURL(new Blob([v], { type: "audio/wav" })); });
    return { b64, seconds: decoded.duration };
  }
  function callSheet() {
    sheet(`<h3>Upload a call recording</h3><p class="small muted">Zoom's audio-only .m4a, a phone voice memo or a WhatsApp voice note (25 MB max).
      Only your and ${isBrand ? "the creator's" : "the brand's"} words can change money. The audio isn't kept; only the transcript.</p>
      <label class="row" style="gap:8px;color:var(--ink)"><input type="checkbox" id="call-consent" style="width:auto"> Everyone on the call agreed to the recording</label>
      <input type="file" id="call-file" accept="audio/*,.m4a" style="margin-top:8px"><button class="btn primary block" id="call-go" style="margin-top:10px">Upload and transcribe</button>`);
    $("#call-go").onclick = e => busy(e.currentTarget, async () => {
      const f = $("#call-file").files[0];
   if (!f) { toast("Choose the recording", "bad"); return; }
      let wav;
      try { wav = await toWav(f); }
      catch (er) { toast("That file couldn't be read as audio. Try the .m4a or .mp3 export.", "bad"); return; }
      if (wav.seconds > CALL_MAX_S) { toast(`Calls up to ${CALL_MAX_S / 60} minutes for now (this one is ${Math.round(wav.seconds / 60)}). Trim it or upload it in parts.`, "bad"); return; }
      try {
        const r = await api(`${base}/call`, { body: { data_b64: wav.b64, mime: "audio/wav", name: f.name, consent: $("#call-consent").checked } });
        tagSheet(r);
   } catch (er) { toast(er.message, "bad"); }
    });
  }
  function tagSheet(r) {
    sheet(`<h3>Who is who?</h3><p class="small muted">Lines from anyone who isn't the brand's main contact or the creator are ignored.</p>
      ${r.speakers.map(s => `<label>${esc(s)} <span class="tiny muted">“${esc((r.segments.find(x => x.speaker === s) || {}).text || "").slice(0, 60)}…”</span></label>
        <select data-spk="${esc(s)}"><option value="unknown">Someone else</option>${r.people.map(p => `<option value="${p.id}">${esc(p.name)}${p.decider ? "" : " (can't change money)"}</option>`).join("")}</select>`).join("")}
      <button class="btn primary block" id="tag-go" style="margin-top:12px">Check the call for changes</button>`);
    $("#tag-go").onclick = e => busy(e.currentTarget, async () => {
      const mapping = Object.fromEntries($$("[data-spk]").map(s => [s.dataset.spk, s.value]));
      try { const t = await api(`${base}/call/${r.message}/tag`, { body: { mapping } }); closeSheet(); lastSig = ""; draw(t);
    toast(t.change ? "Change card added from the call" : "No deal changes found in the call"); }
   catch (er) { toast(er.message, "bad"); }
    });
  }

  function attachMenu() {
    sheet(`<h3>Add to the chat</h3><div class="stack">
      <button class="btn block" data-up="call"><i data-lucide='phone' aria-hidden='true'></i> Call recording (Zoom .m4a, voice memo)</button>
      <button class="btn block" data-up="image"><i data-lucide='camera' aria-hidden='true'></i> Photo</button>
      <button class="btn block" data-up="screenshot"><i data-lucide='receipt' aria-hidden='true'></i> Screenshot of a chat (Amend reads the changes)</button>
      <button class="btn block" data-up="whatsapp"><i data-lucide='message-circle' aria-hidden='true'></i> WhatsApp "Export chat" file (.txt)</button>
      <button class="btn block" data-up="file"><i data-lucide='file-text' aria-hidden='true'></i> File (up to 2 MB)</button></div>
      <p class="hint">Only your and ${isBrand ? "the creator's" : "the brand's"} words can change money. Other people's words are ignored.</p>`);
    $$("[data-up]").forEach(b => b.onclick = () => b.dataset.up === "call" ? callSheet() : pick(b.dataset.up));
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
