/* Content Credentials (C2PA) read in the browser, from the creator's own draft file: nothing is uploaded but the
   result ("found / not found", the tool that made it, whether it says AI generated it). Library: @contentauth/c2pa-web,
   pinned. "No credential" never means "proven real": most files carry none. */
(function () {
  const V = "0.15.4";
  const BASE = `https://cdn.jsdelivr.net/npm/@contentauth/c2pa-web@${V}/dist`;
  // generative AI only (IPTC digital source types); "algorithmicMedia" (made by an algorithm without training data) isn't
  const AI_TYPES = ["trainedAlgorithmicMedia", "compositeWithTrainedAlgorithmicMedia"];
  let sdk = null;

  // what the manifest says, in plain fields (pure: tested on its own)
  function summarise(m) {
    if (!m) return { read: "ok", found: false, generator: null, ai: false, ai_kind: null };
    const gen = (m.claim_generator_info && m.claim_generator_info[0] && m.claim_generator_info[0].name) || m.claim_generator || null;
    let kind = null;
    for (const a of m.assertions || []) {
      if (!/^c2pa\.actions/.test(a.label || "")) continue;
      for (const act of (a.data && a.data.actions) || []) {
        const t = String(act.digitalSourceType || "");
        const hit = AI_TYPES.find(x => t.endsWith(x));
        if (hit && (!kind || hit === "trainedAlgorithmicMedia")) kind = hit;
      }
    }
    return { read: "ok", found: true, generator: gen ? String(gen).slice(0, 80) : null, ai: !!kind, ai_kind: kind };
  }

  async function read(file) {
    try {
      if (!sdk) {
        const mod = await import(`https://cdn.jsdelivr.net/npm/@contentauth/c2pa-web@${V}/+esm`);  // jsdelivr resolves its imports
        sdk = { mod, c2pa: await mod.createC2pa({ wasmSrc: `${BASE}/resources/c2pa_bg.wasm` }) };
      }
      const reader = await sdk.mod.Reader.fromBlob(sdk.c2pa, file.type || undefined, file);
      if (!reader) return summarise(null);
      return summarise(await reader.activeManifest());
    } catch (e) {
      const msg = (e && (e.name + " " + e.message)) || String(e);
      if (/JumbfNotFound|ManifestNotFound|ProvenanceMissing|NotFound/i.test(msg)) return summarise(null);  // a file with no credentials
      const big = /TooLarge/i.test(msg);
      return { read: big ? "too_large" : "error", found: false, generator: null, ai: false, ai_kind: null };
    }
  }
  window.C2PARead = { read, summarise, VERSION: V };
})();
