// Cinematic marketing pass (marketing page only): "the deal builds itself" hero and a card-driven scroll story.
// The text, buttons and the scene are plain HTML; the scene's HTML is already in its final state. An inline flag in <head>
// (html.js-anim, only without reduced motion / Save-Data) hides the parts that animate in, and GSAP 3 plays the timeline once
// it has loaded after the page. If GSAP can't load, the final state is shown. Motion uses transforms and opacity only.
(() => {
  const GSAP_URL = "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js";
  const ST_URL = "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js";
  const LENIS_URL = "https://cdn.jsdelivr.net/npm/lenis@1.1.13/dist/lenis.min.js";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const saveData = !!(navigator.connection && navigator.connection.saveData);
  const desktop = matchMedia("(min-width: 1025px) and (pointer: fine)").matches;
  const staticMode = reduce || saveData;
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;

  let gsapReady = null;
  const loadScript = src => new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
  const loadGsap = () => (gsapReady ||= loadScript(GSAP_URL));
  const idle = fn => ("requestIdleCallback" in window ? requestIdleCallback(fn, { timeout: 1200 }) : setTimeout(fn, 200));
  const afterLoad = fn => (document.readyState === "complete" ? idle(fn) : addEventListener("load", () => idle(fn), { once: true }));
  const showFinal = () => root.classList.remove("js-anim");

  /* ---------- header: dark while over a dark section ---------- */
  function headerTone() {
    const top = $("header.top"); if (!top) return;
    const seen = new Set();
    const io = new IntersectionObserver(es => { es.forEach(e => e.isIntersecting ? seen.add(e.target) : seen.delete(e.target)); top.classList.toggle("on-dark", seen.size > 0); },
      { rootMargin: "0px 0px -94% 0px" });
    $$(".dark-zone").forEach(z => io.observe(z));
  }

  /* ---------- the hero timeline ---------- */
  const money = v => "$" + Math.round(v);
  function heroTimeline() {
    const scene = $("#demo"), inner = $(".sc-inner", scene), card = $("#sc-card");
    const line = k => $(`.sc-ln[data-k="${k}"]`, card), bub = k => $(`.bub[data-k="${k}"]`, scene);
    const pill = $(".sc-pill", card), held = $(".sc-held", card), tot = $(".sc-tot", card), unch = $(".sc-unch", card);
    const plLbl = $(".pl-lbl", card), plReq = $(".pl-req", card), pend = $(".sc-pend", card);
    const setPill = (lbl, amt, req = "") => { plLbl.textContent = lbl; held.textContent = amt; plReq.textContent = req; };
    const bump = () => { pill.classList.remove("pill-bump"); void pill.offsetWidth; pill.classList.add("pill-bump"); };
    const oks = $$(".sc-ok", card), chat = $(".sc-chat", scene);
    const lines = $$(".sc-ln", card);

    // a flying copy of a bubble, and a soft shadow that grows where it will land
    const mkFlyer = (k, ringFrom, tag) => {
      const f = document.createElement("div"); f.className = "flyer" + (k === "plus" ? " plus" : "");
      f.appendChild(ringFrom.cloneNode(true)); if (tag) { const t = document.createElement("span"); t.className = "tag"; t.textContent = tag; f.appendChild(t); }
      const sh = document.createElement("div"); sh.className = "sc-shadow";
      inner.append(sh, f); gsap.set([f, sh], { opacity: 0 });
      return { f, sh };
    };
    const plusRing = $(".ring", bub("story")).cloneNode(true);
    $(".core", plusRing).innerHTML = $(".li-ic", line("plus")).innerHTML;
    const F = { reel: mkFlyer("reel", $(".ring", bub("reel"))), story: mkFlyer("story", $(".ring", bub("story"))),
      rev: mkFlyer("rev", $(".ring", bub("rev"))), plus: mkFlyer("plus", plusRing, "+1 Story") };
    // measured positions (getBoundingClientRect at run time), converted into the stage's own, unscaled units
    const at = (el, fx = 0.5, fy = 0.5) => { const r = el.getBoundingClientRect(), ir = inner.getBoundingClientRect(), k = ir.width / inner.offsetWidth || 1;
      return { x: (r.left - ir.left + r.width * fx) / k, y: (r.top - ir.top + r.height * fy) / k }; };

    const tl = gsap.timeline({ repeat: -1, paused: true, defaults: { overwrite: "auto" } });
    const count = { v: 0 }, hold = { v: 530 };
    const reset = () => {
      gsap.set(inner, { scale: 1, y: 0 });
      gsap.set(lines, { opacity: 0, y: 10 }); gsap.set($$(".li-ic", card), { scale: 0.4 });
      gsap.set(pill, { opacity: 0, scale: 0.7 }); gsap.set([unch, ...oks], { opacity: 0, y: 6 });
      gsap.set(chat, { opacity: 0, y: 14, scale: 0.96 });
      Object.values(F).forEach(x => gsap.set([x.f, x.sh], { opacity: 0 }));
      $$(".bub", scene).forEach(b => b.classList.remove("used"));
      count.v = 0; hold.v = 530; tot.textContent = "$0"; setPill("Held by PayPal", "$530"); pill.classList.remove("pill-bump");
      gsap.set(pend, { opacity: 0, scale: 0.8 });
    };

    // one flight: lift, curve into the line's icon slot (shadow grows as it nears), squash on impact, spring the line in
    const fly = (k, start, fromEl, onLand, fx = 0.5, fy = 0.5) => {
      const { f, sh } = F[k], dur = 0.85, p = { t: 0 };
      let s, e, c, size, end;
      tl.call(() => {
        size = $(".ring", bub(k === "plus" ? "story" : k)).offsetWidth || 72;
        s = at(fromEl, fx, fy); e = at($(".li-ic", line(k)));
        end = ($(".li-ic", line(k)).offsetWidth || 32) / size;
        c = k === "plus" ? { x: (s.x + e.x) / 2 - 30, y: s.y - 50 }                       // pops up out of the message, then drops into the card
                         : { x: (s.x + e.x) / 2 + 110, y: s.y + (e.y - s.y) * 0.25 };     // swings out, then down into its line
        gsap.set(f, { x: s.x - size / 2, y: s.y - size / 2, scale: 1, scaleX: 1, scaleY: 1, opacity: 1, width: size, height: size });
        gsap.set(sh, { x: e.x, y: e.y + size * end * 0.55, scale: 0.3, opacity: 0 });
        if (k !== "plus") bub(k).classList.add("used");
      }, null, start);
      tl.fromTo(p, { t: 0 }, { t: 1, duration: dur, ease: "power2.inOut", immediateRender: false, onUpdate: () => {
        const t = p.t, u = 1 - t, x = u * u * s.x + 2 * u * t * c.x + t * t * e.x, y = u * u * s.y + 2 * u * t * c.y + t * t * e.y;
        const lift = Math.sin(Math.min(t, 0.25) / 0.25 * Math.PI / 2) * 0.08 * (1 - t);
        gsap.set(f, { x: x - size / 2, y: y - size / 2, scale: 1 + lift - (1 - end) * t });
        gsap.set(sh, { opacity: 0.15 + 0.55 * t * t, scale: 0.3 + 0.8 * t });
      } }, start + 0.01);
      tl.to(f, { scaleX: end * 1.28, scaleY: end * 0.72, duration: 0.08, ease: "power1.out" }, start + dur)
        .to(f, { opacity: 0, duration: 0.18 }, start + dur + 0.08)
        .to(sh, { opacity: 0, scale: 1.4, duration: 0.3 }, start + dur)
        .fromTo(line(k), { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.5, ease: "back.out(2)", immediateRender: false }, start + dur - 0.02)
        .fromTo($(".li-ic", line(k)), { scale: 0.4 }, { scale: 1, duration: 0.8, ease: "elastic.out(1, 0.5)", immediateRender: false }, start + dur);
      if (onLand) onLand(start + dur);
    };
    const countTo = (to, t, d = 0.5) => tl.to(count, { v: to, duration: d, ease: "power2.out", onUpdate: () => { tot.textContent = money(count.v); } }, t);

    tl.call(reset, null, 0);
    fly("reel", 0.25, bub("reel"), t => countTo(450, t + 0.05));
    fly("story", 1.05, bub("story"), t => countTo(530, t + 0.05));
    fly("rev", 1.85, bub("rev"));
    tl.fromTo(pill, { opacity: 0, scale: 0.7 }, { opacity: 1, scale: 1, duration: 0.6, ease: "back.out(2.4)", immediateRender: false }, 2.95)
      .fromTo(chat, { opacity: 0, y: 14, scale: 0.96 }, { opacity: 1, y: 0, scale: 1, duration: 0.55, ease: "back.out(1.8)", immediateRender: false }, 3.6);
    // "+1 Story" pops out of the brand's message, then flies up into the card
    tl.call(() => { const s = at(chat, 0.12, 0.3), { f } = F.plus, w = $(".ring", bub("story")).offsetWidth || 72;
      gsap.set(f, { x: s.x - w / 2, y: s.y - w / 2, width: w, height: w, scale: 0, scaleX: 1, scaleY: 1, opacity: 1 }); }, null, 4.25);
    tl.to(F.plus.f, { scale: 1, duration: 0.4, ease: "back.out(3)" }, 4.27);
    fly("plus", 4.8, $(".sc-chat", scene), t => {
      tl.fromTo(line("date"), { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.5, ease: "back.out(2)", immediateRender: false }, t + 0.12)
        .fromTo($(".li-ic", line("date")), { scale: 0.4 }, { scale: 1, duration: 0.8, ease: "elastic.out(1, 0.5)", immediateRender: false }, t + 0.12)
        .fromTo(unch, { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.4, immediateRender: false }, t + 0.3)
        .fromTo(pend, { opacity: 0, scale: 0.8 }, { opacity: 1, scale: 1, duration: 0.4, ease: "back.out(2)", immediateRender: false }, t + 0.35);  // pending: total stays $530
    }, 0.12, 0.3);  // starts where it popped out of the message
    oks.forEach((o, i) => {
      tl.fromTo(o, { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.45, ease: "back.out(2.2)", immediateRender: false }, 6.5 + i * 0.35)
        .call(() => { o.classList.remove("glow"); void o.offsetWidth; o.classList.add("glow"); }, null, 6.55 + i * 0.35);
    });
    // both confirmed: the deal is now $610, PayPal still holds $530 and the extra $80 hold is requested ...
    tl.to(pend, { opacity: 0, duration: 0.25 }, 7.2);
    countTo(610, 7.25, 0.6);
    tl.call(() => { setPill("Held", "$530", " · +$80 hold requested"); bump(); }, null, 7.3)
    // ... next beat: the extra hold is placed, so PayPal holds $610
      .call(() => { setPill("Held by PayPal", "$610"); bump(); }, null, 8.4)
      .to(inner, { scale: 0.955, duration: 1.5, ease: "sine.inOut" }, 8.7)    // slow push-out (around the bottom edge: the caption stays 12px under the card)
      .to({}, { duration: 3 }, 10.2)                                                 // hold the final state for 3 s
      .to([...lines, pill, unch, ...oks, chat, pend], { opacity: 0, duration: 0.35, ease: "power1.in" }, 13.2);
    return tl;
  }

  function startHero() {
    loadGsap().then(() => {
      let tl;
      try { tl = heroTimeline(); } catch (e) { showFinal(); return; }
      root.classList.remove("js-anim");          // GSAP now owns the starting state
      tl.play(0);
      let visible = true, hovered = false;
      const sync = () => (visible && !document.hidden && !hovered ? tl.play() : tl.pause());
      new IntersectionObserver(([e]) => { visible = e.isIntersecting; sync(); }, { threshold: 0.15 }).observe($("#demo"));
      document.addEventListener("visibilitychange", sync);
      $("#demo").addEventListener("mouseenter", () => { hovered = true; sync(); });
      $("#demo").addEventListener("mouseleave", () => { hovered = false; sync(); });
    }).catch(showFinal);
    setTimeout(() => { if (root.classList.contains("js-anim")) showFinal(); }, 8000);  // never leave the card empty
  }

  /* ---------- scroll story: the same card, one stage at a time ---------- */
  const STAGE_PILL = [["Held by PayPal", "$530"], ["Held by PayPal", "$530"], ["Held by PayPal", "$610"], ["Held by PayPal", "$610"], ["Collected · paid to Sara", "$610"]];
  const STAGE_TOTAL = ["$530", "$530", "$610", "$610", "$610"];
  let cur = -1;
  function storySet(i) {
    if (i === cur) return; cur = i;
    $$(".story-list li").forEach((li, j) => li.classList.toggle("on", j === i));
    $$(".story-rail span").forEach((d, j) => d.classList.toggle("on", j <= i));
    const sc = $(".story-card"); sc.dataset.stage = i;
    $(".pl-lbl", sc).textContent = STAGE_PILL[i][0]; $(".sc-held", sc).textContent = STAGE_PILL[i][1]; $(".sc-tot", sc).textContent = STAGE_TOTAL[i];
  }
  const stageOf = p => Math.max(0, Math.min(4, Math.floor(p * 5)));
  function storyFades() {  // phones, reduced motion: a vertical list with simple fades
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("seen"); io.unobserve(e.target); } }), { threshold: 0.25 });
    $$(".story-list li").forEach(li => io.observe(li));
  }
  function storySticky() {  // desktop: full height set up front (no layout shift), stage follows scroll progress
    const sec = $("#story"); sec.classList.add("pinned"); storySet(0);
    const native = () => { const r = sec.getBoundingClientRect(); storySet(stageOf(-r.top / Math.max(1, r.height - innerHeight))); };
    addEventListener("scroll", native, { passive: true });
    afterLoad(async () => {
      try { await loadGsap(); await loadScript(ST_URL); } catch { return; }  // the plain listener keeps working
      removeEventListener("scroll", native);
      gsap.registerPlugin(ScrollTrigger);
      ScrollTrigger.create({ trigger: sec, start: "top top", end: "bottom bottom", onUpdate: s => storySet(stageOf(s.progress)) });
      try { await loadScript(LENIS_URL); const lenis = new Lenis({ lerp: 0.1, smoothWheel: true });
        lenis.on("scroll", ScrollTrigger.update); gsap.ticker.add(t => lenis.raf(t * 1000)); gsap.ticker.lagSmoothing(0); window.LENIS = lenis;
      } catch { /* native scroll is fine */ }
    });
  }

  /* ---------- polish: magnetic buttons, cursor glow (desktop only) ---------- */
  function polish() {
    if (!desktop) return;
    $$(".magnetic").forEach(b => {
      b.addEventListener("pointermove", e => { const r = b.getBoundingClientRect(); const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
        b.style.transform = `translate(${dx * 0.12}px, ${dy * 0.18}px)`; });
      b.addEventListener("pointerleave", () => { b.style.transform = ""; });
    });
    $$(".dark-zone").forEach(z => { const g = z.querySelector(".cursor-glow"); if (!g) return; g.classList.add("live");
      z.addEventListener("pointermove", e => { const r = z.getBoundingClientRect(); g.style.setProperty("--mx", (e.clientX - r.left) + "px"); g.style.setProperty("--my", (e.clientY - r.top) + "px"); }, { passive: true }); });
  }

  // the fixed 560 x 600 stage is scaled to its box (whose height is reserved by aspect-ratio, so nothing shifts)
  function fitStage() {
    const fit = $(".stage-fit"), stage = $(".stage"); if (!fit || !stage) return;
    const set = () => stage.style.setProperty("--k", (fit.clientWidth / 560).toFixed(4));
    set(); new ResizeObserver(set).observe(fit);
  }
  function start() {
    fitStage();
    headerTone();
    if (staticMode) { showFinal(); storyFades(); return; }   // final state, static; no animation libraries downloaded
    polish();
    if (desktop) storySticky(); else storyFades();
    afterLoad(startHero);
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", start) : start();
})();
