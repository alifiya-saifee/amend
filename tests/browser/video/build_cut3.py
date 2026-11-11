"""Draft 3 of the demo video, to Alifiya's polish notes on draft 2 (11 Nov):

1. Size: every app shot fills at least 65 % of the frame width (MIN_W). A component too tall to fit at that width is
   panned top → bottom instead of shrunk. Upscaled video gets a light unsharp; the key proof stills are crisp 2×
   element screenshots from the live pages (crisp_stills.py), so they need little or no upscaling.
2. Background: the motion clips' look, dark warm #100d0a, a slow amber glow that drifts continuously across cuts,
   light grain and a vignette. Each shot has 20 px rounded corners and a soft shadow, and is cropped to the card's own
   border (no slivers of neighbouring cards).
3. Spine: just the hold's clock line ("Hold day 1 of 29"), then the Version 1 line with the authorization ID.
   The live headroom line now shows the later $770 total, so it would contradict Scene A and is left out.
4. Captions: Inter SemiBold 46 px, at most 2 lines (the build fails if one wraps to 3), in the same lower band.
   The scene label pill sits on the shot's left edge.
5. docs/video/act1-opening.mp4 and act3-closing.mp4 replace the title and end cards when they exist.
Output: docs/video/amend-draft-3.mp4 (+ timeline JSON). Silent AAC track; the voice goes on later.
"""
from __future__ import annotations

import html
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cut import BG, CARD_BODIES, CARDS, CLIPS, CREAM, GOLD, V, card_html  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

OVL, SEG, STILL, CRISP, LOOK = V / "overlays3", V / "segments3", V / "stills3", V / "crisp", V / "look3"
for d in (OVL, SEG, STILL, LOOK):
    d.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1080
AREA_X, AREA_Y, AREA_W, AREA_H = 140, 100, 1640, 816   # the shot area; label band above, caption band below
CAP_Y, CAP_H = 930, 136
MIN_W, MAX_W = 1260, 1440                              # 65–75 % of the 1920 frame width
RADIUS, SHADOW = 20, 70
WARM = "#100d0a"
INTER = '"Inter", -apple-system, "Helvetica Neue", Arial, sans-serif'


def _fonts():
    """Inter SemiBold/Bold (latin, from Google Fonts, saved in look3/), embedded so the build never waits on the network."""
    import base64
    faces = "".join(f"@font-face{{font-family:'Inter';font-weight:{w};src:url(data:font/woff2;base64,"
                    f"{base64.b64encode((LOOK / f'inter-{w}.woff2').read_bytes()).decode()}) format('woff2')}}" for w in (600, 700))
    return f"<style>{faces}</style>"


FONTS = _fonts()

CARD_BODIES = dict(CARD_BODIES)
CARD_BODIES["bridge"] = ('<div class="kicker">Same flow, a delivered deal</div><h1>$450 Reel<br>+ a $30 bonus hold</h1>'
                         '<p>Maya × Dune Roast Coffee, posted on Instagram today.</p>')

LA, LB = "Pain: paid late → Fix: PayPal hold before work", "Pain: free extra work → Fix: priced change card"
LC, LD = "Pain: “did you deliver?” → Fix: checked from Instagram, signed", "Fix: PayPal collects only what was agreed"
LG = "Proof: rebuilt from PayPal alone"

# "Resolved" goes in the Scene F caption only once the live dispute run reaches RESOLVED (not yet, 11 Nov)
DISPUTE_RESOLVED = False
CARD_BODIES["F-placeholder"] = ('<div class="kicker">Scene F · to film after the dispute is opened</div><h1>PayPal dispute → signed evidence</h1>'
                                '<p>Dispute banner → evidence pack → Send proof' + (' → RESOLVED.' if DISPUTE_RESOLVED else '.') + '</p>')

# card(name, dur, caption?) · clip(src, a, z, box, caption, label, pan=(y0, y1)?) · still(src, t, box, dur, caption, label)
# img(png in docs/video/crisp, dur, caption, label): a crisp element screenshot, already cropped to the card
T = [
    ("card", "01-title", 4.0, None), ("card", "02-pain-1", 7.0, None), ("card", "03-pain-2", 7.0, None),
    ("card", "04-pain-3", 6.0, None), ("card", "05-pain-to-fix", 4.5, None),
    # A · the hold
    ("clip", "A-mandate-hold", 5.0, 10.9, (343, 140, 726, 880), "Before any work starts, Nadia signs what she’s willing to pre-approve…", LA, (140, 140)),
    ("still", "A-mandate-hold", 10.9, (370, 365, 674, 262), 1.6, "…an extra Story up to $150, and #ad on every post.", LA),
    ("clip", "A-mandate-hold", 11.0, 13.3, (343, 140, 726, 880), "…so the hold is the $530 deal plus $150 of extras: $680.", LA, (300, 560)),
    ("img", "A_old-money.png", 2.0, "PayPal places an authorization hold: $680 held, with a real authorization ID. Nothing is collected yet.", LA),
    ("img", "A_old-clock.png", 1.6, "PayPal gives a hold twenty-nine days: Amend shows the clock…", LA),
    ("img", "A_old-ver1.png", 1.8, "…and the authorization behind this version of the deal.", LA),
    # B · the voice note → a priced change card
    # the voice note bubble from just under its transcript (this take's transcript repeats its first sentence: the
    # fake microphone looped; fixed since) down to "Checking the message for deal changes…"
    ("clip", "B-voice-change-card", 23.5, 25.5, (310, 791, 744, 141), "Then the brand sends a voice note with four changes.", LB, None,
     {"quote": "Make the Reel shorter, add subtitles, deliver tomorrow, and run it as a paid ad for 30 days.", "oy": 420}),
    # the change card, ~4 s: its priced lines, then "Confirmed by both · applied"
    ("clip", "B-voice-change-card", 35.5, 37.7, (313, 375, 737, 496), "The AI quotes her words; code prices each line from Maya’s list: +$240.", LB),
    ("clip", "B2-maya-confirms", 10.0, 12.0, (318, 336, 744, 488), "Both confirm, and the extra comes out of the hold Nadia signed.", LB, (336, 336)),
    ("card", "bridge", 2.0, "The same flow on a delivered deal: a $450 Reel, plus a $30 bonus held separately."),
    # C · Instagram: fail → fix → pass
    ("clip", "C1-instagram-check", 15.2, 16.8, (288, 0, 800, 530), "Maya posts. Amend reads the post straight from Instagram.", LC),
    ("still", "C1-instagram-check", 16.5, (288, 0, 800, 530), 1.6, "#ad is missing, which the brand required, so code fails it…", LC),
    ("clip", "C2-instagram-check", 5.5, 7.2, (282, 362, 800, 424), "…and no money moves until it’s fixed.", LC),
    ("clip", "C-caption-edit-mac", 10.2, 11.7, (1380, 344, 656, 320), "She fixes the caption on Instagram…", LC),
    ("still", "C-caption-edit-mac", 12.4, (1940, 40, 500, 152), 1.3, "She fixes the caption on Instagram…", LC),
    ("clip", "C2-instagram-check", 12.9, 14.3, (284, 88, 800, 282), "…Amend reads it again, and signs a new verdict.", LC),
    ("still", "C2-instagram-check", 14.2, (284, 88, 800, 282), 1.5, "…Amend reads it again, and signs a new verdict.", LC),
    # D · release
    # proposed release once (Nadia has confirmed; Maya taps at 7.6 s) → collected → the payout batch → the balance
    ("clip", "D2-maya-confirms-release", 5.9, 8.3, (290, 266, 796, 380), "Code proposes the release: exactly what was agreed. Both confirm.", LD),
    ("img", "B-money.png", 1.6, "PayPal collects exactly the agreed amount: $450.", LD),
    ("img", "B-payouts.png", 2.4, "Maya and her editor are paid in one Payouts batch; $45 is held back.", LD),
    ("img", "B-ver1.png", 2.0, "Every hold balances to the cent: $450 held = $450 collected ✓", LD),
    ("card", "E-placeholder", 10.0, "Results come from Instagram itself, so the bonus Nadia signed is paid without a single screenshot."),
    ("card", "F-placeholder", 15.0, "And if a brand disputes later, Amend answers PayPal with signed evidence from the deal’s receipt chain."
     + (" Resolved." if DISPUTE_RESOLVED else "")),
    # G · the proof
    ("clip", "G-rebuild-from-paypal", 13.0, 14.0, (300, 156, 1320, 766), "The whole deal, rebuilt from PayPal alone…", LG),
    ("img", "B-rebuild-3.png", 2.0, "Rebuilt from PayPal: every line matches Amend.", LG),
    ("card", "07-same-engine", 6.0, None), ("card", "08-end", 6.0, None),
]
MOTION = {"01-title": V / "act1-opening.mp4", "08-end": V / "act3-closing.mp4"}


def png_size(p: Path):
    with open(p, "rb") as f:
        f.read(16)
        return struct.unpack(">II", f.read(8))


def seg_opts(seg):
    """Optional per-shot settings, the dict after a clip's pan: min_w, oy (shot top), quote (a line above the shot)."""
    return seg[8] if seg[0] == "clip" and len(seg) > 8 and seg[8] else {}


def layout(seg):
    """→ (src box x,y,w,h, crop height shown, out w, out h, out x, out y, pan (y0, y1) or None)."""
    if seg[0] == "img":
        w, h = png_size(CRISP / seg[1]); x = y = 0
    else:
        x, y, w, h = seg[4] if seg[0] == "clip" else seg[3]
    opts = seg_opts(seg)
    min_w = opts.get("min_w", MIN_W)
    s = min(MAX_W / w, AREA_H / h)
    if w * s < min_w:
        s = min_w / w
    vis = min(h, int(AREA_H / s))
    ow, oh = int(round(w * s / 2) * 2), int(round(vis * s / 2) * 2)
    ox, oy = AREA_X + (AREA_W - ow) // 2, opts.get("oy", AREA_Y + (AREA_H - oh) // 2)
    pan = (y, y + h - vis) if vis < h else None
    return (x, y, w, h), vis, ow, oh, ox, oy, pan, s


def caption_of(seg):
    if seg[0] == "card":
        return seg[3], None
    return (seg[3], seg[4]) if seg[0] == "img" else (seg[5], seg[6])


def overlay_html(caption, label, lab_x, lab_y, quote=None, q_x=0, q_w=0):
    lab = f'<div class="lab" style="left:{lab_x}px;top:{lab_y}px">{html.escape(label)}</div>' if label else ""
    if quote:  # the brand's words, Inter SemiBold, white on the warm background, above the shot
        lab += f'<div class="quote" style="left:{q_x}px;width:{q_w}px">“{html.escape(quote)}”</div>'
    cap = f'<div class="cap"><span id="c">{html.escape(caption)}</span></div>' if caption else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>
    html,body{{margin:0;width:{W}px;height:{H}px;background:transparent;font-family:{INTER};}}
    .lab{{position:absolute;padding:9px 20px;border-radius:999px;background:rgba(16,13,10,.92);color:{GOLD};
          font-size:24px;font-weight:700;border:1.5px solid rgba(232,199,122,.55);white-space:nowrap}}
    .cap{{position:absolute;left:{AREA_X}px;width:{AREA_W}px;top:{CAP_Y}px;height:{CAP_H}px;display:flex;align-items:center;
          justify-content:center;text-align:center}}
    .quote{{position:absolute;top:150px;color:#fff;font-size:52px;line-height:1.3;font-weight:600;letter-spacing:-.3px;
          text-shadow:0 2px 16px rgba(0,0,0,.55)}}
    #c{{color:{CREAM};font-size:46px;line-height:1.25;font-weight:600;letter-spacing:-.2px;text-shadow:0 2px 12px rgba(0,0,0,.6)}}
    </style></head><body>{lab}{cap}</body></html>"""


LOOK_HTML = f"""<!doctype html><html><head><style>html,body{{margin:0;width:{W}px;height:{H}px}}
body{{background:{WARM};background-image:radial-gradient(ellipse 75% 70% at 50% 48%, rgba(0,0,0,0) 45%, rgba(0,0,0,.72) 100%)}}</style></head><body></body></html>"""
GLOW_HTML = """<!doctype html><html><head><style>html,body{margin:0;width:1700px;height:1700px;background:transparent}
div{width:1700px;height:1700px;background:radial-gradient(circle at 50% 50%, rgba(232,170,92,.30) 0%, rgba(214,140,60,.14) 30%, rgba(0,0,0,0) 62%)}
</style></head><body><div></div></body></html>"""


def mask_html(w, h):
    return f"""<!doctype html><html><head><style>html,body{{margin:0;width:{w}px;height:{h}px;background:#000}}
    div{{width:{w}px;height:{h}px;border-radius:{RADIUS}px;background:#fff}}</style></head><body><div></div></body></html>"""


def shadow_html(w, h):
    S = SHADOW
    return f"""<!doctype html><html><head><style>html,body{{margin:0;width:{w + 2 * S}px;height:{h + 2 * S}px;background:transparent}}
    div{{position:absolute;left:{S}px;top:{S}px;width:{w}px;height:{h}px;border-radius:{RADIUS}px;background:#000;
        box-shadow:0 22px 60px 6px rgba(0,0,0,.75), 0 0 0 1px rgba(232,199,122,.10)}}</style></head><body><div></div></body></html>"""


def ff(*a):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *a], check=True)


def probe_len(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


def clip_path(name):
    for ext in (".webm", ".mov", ".mp4"):
        if (CLIPS / f"{name}{ext}").exists():
            return CLIPS / f"{name}{ext}"
    raise FileNotFoundError(name)


def seg_len(seg):
    if seg[0] == "card":
        m = MOTION.get(seg[1])
        return probe_len(m) if m and m.exists() else seg[2]
    return {"clip": lambda: seg[3] - seg[2], "still": lambda: seg[4], "img": lambda: seg[2]}[seg[0]]()


def look_inputs(dur):
    return ["-loop", "1", "-t", f"{dur}", "-i", str(LOOK / "bg.png"), "-loop", "1", "-t", f"{dur}", "-i", str(LOOK / "glow.png")]


def look_chain(bg, glow, t0, out):
    """Warm background + grain, then the slow amber glow drifting on a clock that runs across cuts."""
    gx = f"'-120+300*sin((t+{t0})/7.5)'"
    gy = f"'-560+170*cos((t+{t0})/9.0)'"
    return (f"[{bg}:v]format=yuv420p,noise=alls=6:allf=t,gblur=sigma=0.8,format=rgba[bgn];"
            f"[bgn][{glow}:v]overlay=x={gx}:y={gy}:format=auto[{out}]")


def render_assets(pg):
    pg.set_viewport_size({"width": W, "height": H}); pg.set_content(LOOK_HTML); pg.screenshot(path=str(LOOK / "bg.png"))
    pg.set_viewport_size({"width": 1700, "height": 1700}); pg.set_content(GLOW_HTML)
    pg.screenshot(path=str(LOOK / "glow.png"), omit_background=True)
    for name, body in CARD_BODIES.items():  # cards on a transparent page, so they sit on the warm look
        pg.set_viewport_size({"width": W, "height": H})
        pg.set_content(card_html(body).replace(f"background:{BG}", "background:transparent")); pg.wait_for_timeout(120)
        pg.screenshot(path=str(LOOK / f"card-{name}.png"), omit_background=True)
    sizes = {layout(s)[2:4] for s in T if s[0] != "card"}
    for ow, oh in sizes:
        pg.set_viewport_size({"width": ow, "height": oh}); pg.set_content(mask_html(ow, oh))
        pg.screenshot(path=str(LOOK / f"mask-{ow}x{oh}.png"))
        pg.set_viewport_size({"width": ow + 2 * SHADOW, "height": oh + 2 * SHADOW}); pg.set_content(shadow_html(ow, oh))
        pg.screenshot(path=str(LOOK / f"shadow-{ow}x{oh}.png"), omit_background=True)


def build(out_name="amend-draft-5"):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        render_assets(pg)
        pg.set_viewport_size({"width": W, "height": H})
        for i, seg in enumerate(T):
            cap, lab = caption_of(seg)
            if seg[0] == "card":
                lx, ly = AREA_X, 28
            else:
                _, _, ow, _, ox, oy, _, _ = layout(seg)
                q = seg_opts(seg).get("quote")
                lx, ly = ox, (60 if q else max(24, oy - 64))
            pg.set_content(overlay_html(cap, lab, lx, ly, *((q, ox, ow) if seg[0] != "card" and q else ())))
            pg.evaluate("Promise.all([document.fonts.load('600 46px Inter'), document.fonts.load('700 24px Inter')])")
            assert pg.evaluate("document.fonts.check('600 46px Inter')"), "Inter didn't load"
            if cap:
                lines = pg.evaluate("(() => { const r = document.getElementById('c').getClientRects(); return r.length })()")
                assert lines <= 2, f"segment {i}: caption wraps to {lines} lines: {cap}"
            pg.screenshot(path=str(OVL / f"{i:02d}.png"), omit_background=True)
        b.close()

    parts, t, log = [], 0.0, []
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-an"]
    for i, seg in enumerate(T):
        out, ovl = SEG / f"{i:02d}.mp4", OVL / f"{i:02d}.png"
        dur = seg_len(seg)
        if seg[0] == "card":
            name = seg[1]
            m = MOTION.get(name)
            if m and m.exists():
                ff("-i", str(m), "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={WARM},fps=30",
                   *enc, str(out))
                what = f"motion:{m.name}"
            else:
                fc = look_chain(0, 1, t, "b") + f";[b][2:v]overlay=0:0[c];[c][3:v]overlay=0:0"
                ff(*look_inputs(dur), "-loop", "1", "-t", f"{dur}", "-i", str(LOOK / f"card-{name}.png"),
                   "-loop", "1", "-t", f"{dur}", "-i", str(ovl), "-filter_complex", fc, "-t", f"{dur}", *enc, str(out))
                what = f"card:{name}"
        else:
            (x, y, w, h), vis, ow, oh, ox, oy, auto_pan, s = layout(seg)
            if seg[0] == "clip":
                src = seg[1]; pan = seg[7] if len(seg) > 7 and seg[7] else auto_pan
                inp = ["-ss", f"{seg[2]}", "-t", f"{dur}", "-i", str(clip_path(src))]
            elif seg[0] == "still":
                src, pan = seg[1], auto_pan
                frame = STILL / f"{i:02d}.png"
                ff("-ss", f"{seg[2]}", "-i", str(clip_path(src)), "-frames:v", "1", str(frame))
                inp = ["-loop", "1", "-t", f"{dur}", "-i", str(frame)]
            else:
                src, pan = seg[1], auto_pan
                inp = ["-loop", "1", "-t", f"{dur}", "-i", str(CRISP / seg[1])]
            # ease the pan (smoothstep) so it starts and ends gently
            ypos = (f"'{pan[0]}+({pan[1]}-{pan[0]})*(3*pow(min(t/{dur},1),2)-2*pow(min(t/{dur},1),3))'" if pan else f"{y}")
            sharpen = ",unsharp=5:5:0.55:5:5:0" if s > 1.2 else ""
            fc = (look_chain(2, 3, t, "b") + ";"
                  f"[0:v]crop={w}:{vis}:{x}:{ypos},scale={ow}:{oh}:flags=lanczos{sharpen},setsar=1,format=rgba[s0];"
                  f"[4:v]format=gray[m];[s0][m]alphamerge[s1];"
                  f"[b][5:v]overlay={ox - SHADOW}:{oy - SHADOW}[b2];[b2][s1]overlay={ox}:{oy}[b3];[b3][1:v]overlay=0:0")
            ff(*inp, "-loop", "1", "-t", f"{dur}", "-i", str(ovl), *look_inputs(dur),
               "-loop", "1", "-t", f"{dur}", "-i", str(LOOK / f"mask-{ow}x{oh}.png"),
               "-loop", "1", "-t", f"{dur}", "-i", str(LOOK / f"shadow-{ow}x{oh}.png"),
               "-filter_complex", fc, "-t", f"{dur}", *enc, str(out))
            what = f"{seg[0]}:{src} · {ow}px wide ({ow / W:.0%}) · ×{s:.2f}{' · pan' if pan else ''}"
        parts.append(out)
        log.append({"at": round(t, 1), "len": round(dur, 2), "what": what})
        t += dur
    lst = SEG / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    joined = SEG / "joined.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined))
    final = V / f"{out_name}.mp4"
    ff("-i", str(joined), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "copy", "-c:a", "aac",
       "-movflags", "+faststart", str(final))
    (V / f"{out_name}.timeline.json").write_text(json.dumps(log, indent=1))
    for e in log:
        print(f"{int(e['at'] // 60)}:{e['at'] % 60:04.1f}  {e['len']:>5}  {e['what']}")
    print(f"{out_name}: {final} · {t:.1f} s ({int(t // 60)}:{t % 60:04.1f})")


if __name__ == "__main__":
    build()
