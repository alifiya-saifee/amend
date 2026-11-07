// Cinematic marketing pass (marketing page only). Everything here is an enhancement: the page's text, buttons and the demo
// card are plain HTML and render first. WebGL (three.js), GSAP + ScrollTrigger and Lenis load after the page has loaded.
// Fallbacks: reduced motion, Save-Data or no WebGL -> a static poster image and no animation libraries at all.
(() => {
  const THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/0.160.0/three.module.min.js";
  const GSAP_URL = "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js";
  const ST_URL = "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js";
  const LENIS_URL = "https://cdn.jsdelivr.net/npm/lenis@1.1.13/dist/lenis.min.js";
  const Q = new URLSearchParams(location.search);
  const POSTER = Q.has("poster");                       // used once to render the fallback poster image
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const saveData = !!(navigator.connection && navigator.connection.saveData);
  const phone = matchMedia("(max-width: 767px)").matches || matchMedia("(pointer: coarse)").matches;
  const desktop = matchMedia("(min-width: 1025px) and (pointer: fine)").matches;
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];

  function hasWebGL() {
    try { const c = document.createElement("canvas"); return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl"))); }
    catch { return false; }
  }
  const staticMode = !POSTER && (reduce || saveData);  // no-WebGL is checked lazily, just before the river starts
  const loadScript = src => new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
  const idle = fn => ("requestIdleCallback" in window ? requestIdleCallback(fn, { timeout: 1500 }) : setTimeout(fn, 300));
  const afterLoad = fn => (document.readyState === "complete" ? idle(fn) : addEventListener("load", () => idle(fn), { once: true }));

  /* ---------- header: dark while over a dark section ---------- */
  function headerTone() {
    const top = $("header.top"); if (!top) return;
    const zones = $$(".dark-zone"), seen = new Set();
    const io = new IntersectionObserver(es => { es.forEach(e => e.isIntersecting ? seen.add(e.target) : seen.delete(e.target)); top.classList.toggle("on-dark", seen.size > 0); },
      { rootMargin: "0px 0px -94% 0px" });
    zones.forEach(z => io.observe(z));
  }

  /* ---------- money counter roll ---------- */
  function roll(el, from, to, ms = 900) {
    if (!el) return;
    const t0 = performance.now();
    const step = now => { const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      el.textContent = "$" + Math.round(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  /* ---------- the hero story: demo card beats in sync with the river ---------- */
  const listeners = [];
  const onBeat = fn => listeners.push(fn);
  function heroStory() {
    const demo = $("#demo"), chip = $("#chip-amt"), nodes = $$("#hero-band .r-node");
    if (!demo) return;
    const held = demo.querySelector(".held");
    if (staticMode) {  // final state, no motion
      nodes.forEach(n => n.classList.add("confirmed")); if (chip) chip.textContent = "$610"; return;
    }
    held.innerHTML = 'Held <span class="hv-roll">$530</span>';
    const hv = held.querySelector(".hv-roll");
    demo.classList.add("beats");
    // beats: 0 message (skeleton of the card) · 1 change card (skeleton of the confirms) · 2 river splits, $530 -> $610 · 3 both confirm
    const plan = [[0, 0], [2000, 1], [4200, 2], [6000, 3]], cycle = 9200;
    let timers = [], running = false, hovered = false;
    const set = b => {
      demo.dataset.beat = b;
      if (b === 0) { hv.textContent = "$530"; if (chip) chip.textContent = "$530"; nodes.forEach(n => n.classList.remove("confirmed")); }
      if (b === 2) { roll(hv, 530, 610); roll(chip, 530, 610); chip && chip.parentElement.classList.remove("bump"); void chip?.offsetWidth; chip && chip.parentElement.classList.add("bump"); }
      if (b === 3) nodes.forEach((n, i) => setTimeout(() => n.classList.add("confirmed"), i * 260));
      listeners.forEach(fn => fn(b));
    };
    const run = () => { if (running) return; running = true;
      const loop = () => { plan.forEach(([at, b]) => timers.push(setTimeout(() => set(b), at))); timers.push(setTimeout(() => { timers = []; if (running) loop(); }, cycle)); };
      loop(); };
    const stop = () => { running = false; timers.forEach(clearTimeout); timers = []; };
    demo.addEventListener("mouseenter", () => { hovered = true; stop(); });
    demo.addEventListener("mouseleave", () => { hovered = false; if (visible && !document.hidden) run(); });
    let visible = true;
    new IntersectionObserver(([e]) => { visible = e.isIntersecting; visible && !hovered && !document.hidden ? run() : stop(); }).observe($("#hero"));
    document.addEventListener("visibilitychange", () => (document.hidden ? stop() : visible && !hovered && run()));
    set(0); run();
  }

  /* ---------- the particle river (three.js) ---------- */
  const VERT = `
    attribute vec4 aSeed; uniform float uTime, uSplit, uThick, uReach, uPool, uFlare, uWidth, uAmp, uPR, uPhase;
    uniform vec2 uP0, uP1, uP2, uP3; uniform vec3 uMouse; varying vec3 vColor; varying float vAlpha;
    vec2 bez(float t, vec2 a, vec2 b, vec2 c, vec2 d) { float u = 1.0 - t; return u*u*u*a + 3.0*u*u*t*b + 3.0*u*t*t*c + t*t*t*d; }
    vec2 bezD(float t, vec2 a, vec2 b, vec2 c, vec2 d) { float u = 1.0 - t; return 3.0*u*u*(b-a) + 6.0*u*t*(c-b) + 3.0*t*t*(d-c); }
    void main() {
      float t = fract(aSeed.x + uPhase * (0.55 + 0.9 * aSeed.z));
      t = mix(t, 0.5 + (t - 0.5) * 0.16, uPool);
      float branch = aSeed.w > 0.5 ? 1.0 : -1.0;
      float s = uSplit * branch;
      vec2 b1 = uP1 + vec2(0.0, -uAmp * s * 1.1), b2 = uP2 + vec2(0.0, -uAmp * s * 1.1 - uAmp * 0.25 * uSplit);
      vec2 p = bez(t, uP0, b1, b2, uP3);
      vec2 d = normalize(bezD(t, uP0, b1, b2, uP3) + 1e-4); vec2 n = vec2(-d.y, d.x);
      float taper = pow(sin(3.14159 * clamp(t, 0.0, 1.0)), 0.55);
      float w = uWidth * (1.0 + uThick * 1.7) * (taper * (1.0 + uPool * 1.8));
      p += n * aSeed.y * w + n * sin(t * 18.0 + uTime * 1.3 + aSeed.w * 6.283) * (2.0 + 3.0 * uThick);
      vec2 m = uMouse.xy - p; float dist = length(m);
      p += m * uMouse.z * 0.22 * exp(-dist / 150.0);
      float hl = pow(0.5 + 0.5 * sin((t * 5.0 - uTime * 0.55) * 6.283), 8.0);
      vColor = mix(vec3(0.851, 0.643, 0.255), vec3(1.0, 0.478, 0.239), clamp(hl * 0.95 + uThick * 0.18, 0.0, 1.0));
      vColor = mix(vColor, vec3(1.0, 0.92, 0.75), uFlare * smoothstep(0.75, 1.0, t) * 0.7);
      float reach = 1.0 - smoothstep(uReach - 0.06, uReach, t);
      float edge = smoothstep(0.0, 0.03, t) * (1.0 - smoothstep(0.97, 1.0, t) * (1.0 - uFlare));
      vAlpha = reach * edge * (0.45 + 0.95 * aSeed.z) * (0.5 + 0.7 * hl) * (1.0 + uFlare * smoothstep(0.8, 1.0, t) * 1.5);
      gl_PointSize = (1.8 + 3.0 * aSeed.z + hl * 2.6) * uPR * (1.0 + uThick * 0.25);
      gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 0.0, 1.0);
    }`;
  const FRAG = `
    varying vec3 vColor; varying float vAlpha;
    void main() { float r = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, r); a *= a; gl_FragColor = vec4(vColor * a * vAlpha, a * vAlpha); }`;
  const DUST_VERT = `
    attribute vec4 aSeed; uniform float uTime, uPR; uniform vec2 uSize; varying float vAlpha;
    void main() { vec2 p = aSeed.xy * uSize + vec2(sin(uTime * 0.07 + aSeed.w * 6.283) * 30.0, -mod(uTime * (4.0 + aSeed.z * 8.0) + aSeed.w * uSize.y, uSize.y));
      p.y = mod(p.y, uSize.y); vAlpha = 0.10 + 0.25 * aSeed.z; gl_PointSize = (1.0 + aSeed.z * 1.6) * uPR; gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 0.0, 1.0); }`;
  const DUST_FRAG = `varying float vAlpha; void main() { float r = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, r); gl_FragColor = vec4(vec3(0.95, 0.75, 0.45) * a * vAlpha, a * vAlpha); }`;

  const STATES = {  // what the river looks like at each moment of the story
    idle: { split: 0, thick: 0, reach: 1, pool: 0, flare: 0, speed: 1 },
    link: { split: 0, thick: 0, reach: 0.42, pool: 0, flare: 0, speed: 0.8 },
    held: { split: 0, thick: 0.2, reach: 1, pool: 0.85, flare: 0, speed: 0.45 },
    change: { split: 1, thick: 1, reach: 1, pool: 0.15, flare: 0, speed: 1 },
    match: { split: 0, thick: 0.55, reach: 1, pool: 0, flare: 0.2, speed: 1.05 },
    paid: { split: 0, thick: 0.8, reach: 1, pool: 0, flare: 1, speed: 1.9 },
  };

  class River {
    constructor(THREE, host, band, { count }) {
      this.T = THREE; this.host = host; this.band = band;
      const pr = Math.min(window.devicePixelRatio || 1, phone ? 1.5 : 2);
      this.renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "low-power", preserveDrawingBuffer: POSTER });
      this.renderer.setPixelRatio(pr); this.renderer.setClearColor(0x000000, 0);
      host.appendChild(this.renderer.domElement);
      this.scene = new THREE.Scene();
      this.camera = new THREE.OrthographicCamera(0, 1, 0, 1, -1, 1);
      const seeds = new Float32Array(count * 4);
      for (let i = 0; i < count; i++) {
        const lane = (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;  // denser in the middle of the river
        seeds.set([Math.random(), lane, Math.random(), Math.random()], i * 4);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 4));
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
      g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
      const V2 = () => new THREE.Vector2();
      this.u = { uTime: { value: 0 }, uPhase: { value: 0 }, uSplit: { value: 0 }, uThick: { value: 0 }, uReach: { value: 1 }, uPool: { value: 0 }, uFlare: { value: 0 },
        uWidth: { value: 10 }, uAmp: { value: 60 }, uPR: { value: pr }, uP0: { value: V2() }, uP1: { value: V2() }, uP2: { value: V2() }, uP3: { value: V2() },
        uMouse: { value: new THREE.Vector3(-999, -999, 0) } };
      const mat = new THREE.ShaderMaterial({ uniforms: this.u, vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, depthTest: false,
        blending: THREE.AdditiveBlending });
      this.scene.add(new THREE.Points(g, mat));
      const dn = Math.round(count * 0.05), ds = new Float32Array(dn * 4);
      for (let i = 0; i < dn; i++) ds.set([Math.random(), Math.random(), Math.random(), Math.random()], i * 4);
      const dg = new THREE.BufferGeometry(); dg.setAttribute("aSeed", new THREE.BufferAttribute(ds, 4));
      dg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(dn * 3), 3)); dg.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
      this.du = { uTime: this.u.uTime, uPR: this.u.uPR, uSize: { value: V2() } };
      this.scene.add(new THREE.Points(dg, new THREE.ShaderMaterial({ uniforms: this.du, vertexShader: DUST_VERT, fragmentShader: DUST_FRAG, transparent: true,
        depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending })));
      this.cur = { ...STATES.idle }; this.target = { ...STATES.idle };
      this.mouse = { x: -999, y: -999, k: 0, kt: 0 };
      this.running = false; this.inView = true; this.last = performance.now(); this.phase = Math.random();
      this.resize(); new ResizeObserver(() => this.resize()).observe(host);
      if (desktop) {
        addEventListener("pointermove", e => { const r = host.getBoundingClientRect(); this.mouse.x = e.clientX - r.left; this.mouse.y = e.clientY - r.top;
          this.mouse.kt = (e.clientY >= r.top && e.clientY <= r.bottom) ? 1 : 0; }, { passive: true });
      }
      new IntersectionObserver(([e]) => { this.inView = e.isIntersecting; this.sync(); }).observe(host);
      document.addEventListener("visibilitychange", () => this.sync());
    }
    resize() {
      const r = this.host.getBoundingClientRect(), b = this.band.getBoundingClientRect();
      const w = Math.max(1, r.width), h = Math.max(1, r.height);
      this.renderer.setSize(w, h, false);
      Object.assign(this.camera, { left: 0, right: w, top: 0, bottom: h }); this.camera.updateProjectionMatrix();
      const x0 = b.left - r.left, y = b.top - r.top + b.height / 2, bw = b.width, bh = b.height;
      const inset = phone ? 0.10 : 0.07;
      this.u.uP0.value.set(x0 + bw * inset, y); this.u.uP3.value.set(x0 + bw * (1 - inset), y);
      this.u.uP1.value.set(x0 + bw * 0.36, y - bh * 0.55); this.u.uP2.value.set(x0 + bw * 0.64, y + bh * 0.55);
      this.u.uWidth.value = phone ? 8 : 14; this.u.uAmp.value = bh * (phone ? 0.42 : 0.5);
      this.du.uSize.value.set(w, h);
      if (!this.running) this.render(0);
    }
    to(name) { this.target = { ...STATES[name] }; }
    sync() { const go = this.inView && !document.hidden; if (go && !this.running) { this.running = true; this.last = performance.now(); requestAnimationFrame(t => this.tick(t)); } if (!go) this.running = false; }
    tick(now) {
      if (!this.running) return;
      this.render(Math.min(0.05, (now - this.last) / 1000)); this.last = now;
      requestAnimationFrame(t => this.tick(t));
    }
    render(dt) {
      const c = this.cur, t = this.target, k = 1 - Math.pow(0.0015, dt || 0.016);
      for (const key in t) c[key] += (t[key] - c[key]) * k;
      this.phase += dt * 0.055 * c.speed;
      this.u.uTime.value += dt; this.u.uPhase.value = this.phase;
      for (const key of ["split", "thick", "reach", "pool", "flare"]) this.u["u" + key[0].toUpperCase() + key.slice(1)].value = c[key];
      this.mouse.k += (this.mouse.kt - this.mouse.k) * 0.06;
      this.u.uMouse.value.set(this.mouse.x, this.mouse.y, this.mouse.k);
      this.renderer.render(this.scene, this.camera);
    }
  }

  /* ---------- scroll story ---------- */
  const STORY = [["link", "Deal link sent"], ["held", "Held by PayPal $530"], ["change", "Held by PayPal $610"], ["match", "Delivery matches the deal"], ["paid", "Paid out to Sara"]];
  function storyFades() {  // phones, reduced motion, no WebGL: a vertical list with simple fades
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("seen"); io.unobserve(e.target); } }), { threshold: 0.25 });
    $$(".story-list li").forEach(li => io.observe(li));
  }
  // Desktop: the layout switches to the sticky version straight away (so nothing shifts later); the stage follows scroll
  // progress, first from a plain scroll listener, then from GSAP ScrollTrigger once it has loaded. The river joins when three.js is ready.
  const story = { river: null, cur: -1 };
  function storySet(i) {
    if (i === story.cur) return; story.cur = i;
    $$(".story-list li").forEach((li, j) => li.classList.toggle("on", j === i)); $$(".story-rail span").forEach((d, j) => d.classList.toggle("on", j <= i));
    $("#story-chip").textContent = STORY[i][1];
    $$("#story-band .r-node").forEach(n => n.classList.toggle("confirmed", i >= 2));
    if (story.river) story.river.to(STORY[i][0]);
  }
  const stageOf = p => Math.max(0, Math.min(4, Math.floor(p * 5)));
  function storySticky() {
    const sec = $("#story"); sec.classList.add("pinned"); storySet(0);
    const native = () => { const r = sec.getBoundingClientRect(); storySet(stageOf(-r.top / Math.max(1, r.height - innerHeight))); };
    addEventListener("scroll", native, { passive: true });
    afterLoad(async () => {
      try { await loadScript(GSAP_URL); await loadScript(ST_URL); } catch { return; }  // the plain listener keeps working
      removeEventListener("scroll", native);
      gsap.registerPlugin(ScrollTrigger);
      ScrollTrigger.create({ trigger: sec, start: "top top", end: "bottom bottom", onUpdate: s => storySet(stageOf(s.progress)) });
      try { await loadScript(LENIS_URL); const lenis = new Lenis({ lerp: 0.1, smoothWheel: true });
        lenis.on("scroll", ScrollTrigger.update); gsap.ticker.add(t => lenis.raf(t * 1000)); gsap.ticker.lagSmoothing(0); window.LENIS = lenis;
      } catch { /* native scroll is fine */ }
    });
  }
  function storyRiver(THREE) {
    story.river = new River(THREE, $("#story-canvas"), $("#story-band"), { count: 6000 });
    story.river.to(STORY[Math.max(0, story.cur)][0]); story.river.cur = { ...story.river.target }; story.river.sync();
  }

  /* ---------- polish: magnetic buttons, cursor glow ---------- */
  function polish() {
    if (!desktop || reduce) return;
    $$(".magnetic").forEach(b => {
      b.addEventListener("pointermove", e => { const r = b.getBoundingClientRect(); const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
        b.style.transform = `translate(${dx * 0.12}px, ${dy * 0.18}px)`; });
      b.addEventListener("pointerleave", () => { b.style.transform = ""; });
    });
    $$(".dark-zone").forEach(z => { const g = z.querySelector(".cursor-glow"); if (!g) return; g.classList.add("live");
      z.addEventListener("pointermove", e => { const r = z.getBoundingClientRect(); g.style.transform = `translate(${e.clientX - r.left}px, ${e.clientY - r.top}px)`; }, { passive: true }); });
  }

  /* ---------- start ---------- */
  function start() {
    headerTone();
    heroStory();
    if (staticMode) { $("#hero")?.classList.add("poster"); storyFades(); return; }
    polish();
    if (desktop && !POSTER) storySticky(); else storyFades();
    // Phones: the poster shows at once; the live river (25% of the particles) fades in over it on the first touch or scroll,
    // or once the phone has been idle for a few seconds, so loading never competes with the text and buttons.
    const phoneLater = phone && !POSTER;
    if (phoneLater) $("#hero").classList.add("poster");
    const when = phoneLater ? new Promise(res => {
      const go = () => { ["touchstart", "scroll", "pointerdown", "keydown"].forEach(t => removeEventListener(t, go)); res(); };
      ["touchstart", "scroll", "pointerdown", "keydown"].forEach(t => addEventListener(t, go, { once: true, passive: true }));
      afterLoad(() => setTimeout(go, 6000));
    }) : Promise.resolve();
    afterLoad(async () => {
      await when;
      if (!hasWebGL()) { $("#hero").classList.add("poster"); return; }
      let THREE;
      try { THREE = await import(THREE_URL); } catch { $("#hero").classList.add("poster"); return; }
      const hero = new River(THREE, $("#hero-canvas"), $("#hero-band"), { count: phone ? 2200 : 9000 });
      hero.renderer.domElement.style.opacity = "0"; hero.renderer.domElement.style.transition = "opacity 1.2s ease";
      requestAnimationFrame(() => { hero.renderer.domElement.style.opacity = "1"; });
      if (phoneLater) setTimeout(() => $("#hero").classList.remove("poster"), 1300);
      onBeat(b => hero.to(b === 2 || b === 3 ? "change" : "idle"));
      hero.sync();
      if (POSTER) { hero.to("change"); hero.cur = { ...STATES.change }; hero.render(0.016); for (let i = 0; i < 90; i++) hero.render(0.016);
        hero.renderer.domElement.style.transition = "none"; hero.renderer.domElement.style.opacity = "1";
        window.__poster = hero.renderer.domElement.toDataURL("image/webp", 0.82); return; }
      if (desktop) {
        const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); storyRiver(THREE); } }, { rootMargin: "50% 0px" });
        io.observe($("#story"));
      }
    });
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", start) : start();
})();
