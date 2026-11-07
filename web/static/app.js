// Shared helpers: api(), toast, sheets, money formatting, busy buttons. No build step.
const AED = 3.6725;

async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body ? "POST" : "GET"), headers: {}, credentials: "same-origin" };
  if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  let r;
  try { r = await fetch(path, init); }
  catch (e) { throw Object.assign(new Error("Can't reach Amend. Check your connection and try again."), { status: 0 }); }
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (!r.ok) {
    const msg = data.error || data.detail || `Something went wrong (${r.status})`;
    throw Object.assign(new Error(typeof msg === "string" ? msg : "Something went wrong"), { status: r.status, data });
  }
  return data;
}

function usd(cents) {
  if (cents == null) return "–";
  const d = Math.floor(cents / 100), c = cents % 100;
  return "$" + d.toLocaleString("en-US") + (c ? "." + String(c).padStart(2, "0") : "");
}
function aed(cents, compact = true) {
  const v = Math.round(cents * AED) / 100;
  return "AED " + (compact ? Math.round(v).toLocaleString("en-US") : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
}
function money(cents) {
 return `<span>${usd(cents)}</span> <span class="aed" title="Fixed rate 3.6725. PayPal charges in USD.">· ${aed(cents)}</span>`;
}
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return [...root.querySelectorAll(sel)]; }
function initials(name) { return (name || "?").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase(); }
function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now"; if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago"; return Math.floor(s / 86400) + " d ago";
}
function dateStr(iso) { return iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : ""; }

const MONEY_PILL = {
  planned: ["Planned", "planned"], approved: ["Waiting for PayPal", "waiting"], sent: ["Waiting for PayPal", "waiting"],
  authorized: ["Held", "held"], paid: ["Collected", "collected"], voided: ["Released", "released"],
  refunded: ["Refunded", "refunded"], failed: ["Failed", "failed"], expired: ["Hold expired", "expired"], cancelled: ["Cancelled", "planned"],
};
function moneyPill(status) { if (!status) return ""; const [t, c] = MONEY_PILL[status] || [status, ""]; return `<span class="pill ${c}">${t}</span>`; }
const DEAL_LABEL = { draft: "Waiting for brief", offered: "Draft to accept", accepted: "Accepted", in_progress: "In progress",
  delivered: "Delivered", completed: "Done", paused: "Paused", cancelled: "Cancelled" };
function dealPill(s) { return `<span class="pill status">${DEAL_LABEL[s] || s}</span>`; }

let toastTimer;
function toast(msg, kind = "ok", retry) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; t.setAttribute("role", "status"); t.setAttribute("aria-live", "polite"); document.body.appendChild(t); }
  t.className = `toast show ${kind}`;
  t.innerHTML = `<span class="grow">${esc(msg)}</span>` + (retry ? `<button class="btn small" id="toast-retry">Try again</button>` : "");
  if (retry) $("#toast-retry").onclick = () => { t.className = "toast"; retry(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.className = "toast", retry ? 8000 : 3000);
}

// Disable a button with a spinner while its request runs: a double tap can't send twice.
async function busy(btn, fn) {
  if (btn.disabled) return;
  const html = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin"></span>${html}`;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = html; }
}

function sheet(html, { onOpen, drawer = false } = {}) {
  let bg = $("#sheet-bg"), sh = $("#sheet");
  if (!bg) {
    bg = document.createElement("div"); bg.id = "sheet-bg"; bg.className = "sheet-bg"; document.body.appendChild(bg);
    sh = document.createElement("div"); sh.id = "sheet"; sh.className = "sheet"; document.body.appendChild(sh);
    bg.onclick = closeSheet;
  }
  sh.classList.toggle("drawer", drawer); sh.setAttribute("role", "dialog"); sh.setAttribute("aria-modal", "true");
  sh.innerHTML = `<div class="grab"></div>` + html;
  bg.classList.add("open"); requestAnimationFrame(() => sh.classList.add("open"));
  if (onOpen) onOpen(sh);
  return sh;
}
function closeSheet() { $("#sheet")?.classList.remove("open"); $("#sheet-bg")?.classList.remove("open"); }

function quoteSheet(quote, who, where, when) {
  sheet(`<h3>Where this was agreed</h3><blockquote>“${esc(quote)}”</blockquote>
    <p class="muted small">${esc(who || "")}${where ? " · " + esc(where) : ""}${when ? " · " + esc(when) : ""}</p>
    <button class="btn block" onclick="closeSheet()">Close</button>`);
}

function sandboxStrip() {
 if (!$(".sandbox")) { const s = document.createElement("div"); s.className = "sandbox"; s.textContent = "PayPal sandbox. No real money."; document.body.appendChild(s); }
}
document.addEventListener("DOMContentLoaded", sandboxStrip);

function toggleMenu(id) { $("#" + id).classList.toggle("open"); }
document.addEventListener("click", e => { if (!e.target.closest(".chip-me, .menu")) $$(".menu.open").forEach(m => m.classList.remove("open")); });

async function signOut() { await api("/logout", { method: "POST" }); location.href = "/"; }

// Header (S83): every page shows "Sign in", or the signed-in person's name with a link home.
async function fillAuthSlots() {
  const slots = $$(".auth-slot");
  if (!slots.length) return;
  let w = { signed_in: false };
  try { w = await api("/api/whoami"); } catch {}
  window.WHO = w;
  const next = encodeURIComponent(location.pathname + location.search);
  slots.forEach(s => {
    const mk = document.body.classList.contains("marketing");
    s.innerHTML = w.signed_in
      ? (mk ? `<a class="btn primary small" href="${w.home}">${w.kind === "brand" ? "Go to my workspace" : "Go to my studio"}</a>`
      : `<a class="who" href="${w.home}" title="${w.kind === "brand" ? "Brand workspace" : "Your studio"}">${esc(w.name || "Account")}${w.company ? " · " + esc(w.company) : ""}</a>`)
      : (mk ? `<a class="btn small ghost" href="/login?next=${next}">Sign in</a><a class="btn small primary" href="/signup">Get started</a>`
            : `<a class="btn small" href="/login?next=${next}">Sign in</a>`);
  });
}
document.addEventListener("DOMContentLoaded", fillAuthSlots);

// Icons: Lucide (one set, 1.75 px stroke). <i data-lucide="name"></i> anywhere is drawn automatically.
(function fonts() {
  const l = document.createElement("link");
  l.rel = "stylesheet"; l.href = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap";
  document.head.appendChild(l);
})();
(function icons() {
  let pending = false;
  const draw = () => { pending = false; if (window.lucide) lucide.createIcons({ attrs: { "stroke-width": 1.75, width: 20, height: 20 } }); };
  const later = () => { if (!pending) { pending = true; requestAnimationFrame(draw); } };
  const s = document.createElement("script");
  s.src = "https://cdn.jsdelivr.net/npm/lucide@0.460.0/dist/umd/lucide.min.js";
  s.onload = draw;
  document.head.appendChild(s);
  new MutationObserver(m => { if (m.some(x => [...x.addedNodes].some(n => n.nodeType === 1))) later(); })
    .observe(document.documentElement, { childList: true, subtree: true });
})();
// Theme choice (Settings): system, light or dark. Stored per browser; marketing pages stay light.
function applyTheme(t) {
  try { localStorage.setItem("amend.theme", t); } catch {}
  document.documentElement.classList.toggle("theme-dark", t === "dark");
  document.documentElement.classList.toggle("theme-light", t === "light");
}
try { const t = localStorage.getItem("amend.theme"); if (t) applyTheme(t); } catch {}
function icon(name, cls = "") { return `<i data-lucide="${name}" class="${cls}" aria-hidden="true"></i>`; }
