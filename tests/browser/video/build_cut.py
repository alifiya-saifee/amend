"""First cut of the demo video (silent, captions burned in), from the recorded clips and title cards.

Cards: docs/video/cards/0N-*.png (made here from the script in Amend's look) unless Alifiya's own
docs/video/amend-video-cards/0N-*.png exist, which win. Captions (the voiceover lines) and scene labels are drawn as
transparent 1920×1080 PNGs (this ffmpeg has no drawtext) and laid over each segment. Scenes E and F are placeholder
cards until they're filmed. Output: docs/video/amend-draft.mp4 (H.264, 30 fps, silent AAC track), plus the timeline.
"""
from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
V = ROOT / "docs" / "video"
CLIPS, CARDS, OVL, SEG = V / "clips", V / "cards", V / "overlays", V / "segments"
HERS = V / "amend-video-cards"
for d in (CARDS, OVL, SEG):
    d.mkdir(parents=True, exist_ok=True)

BG, GOLD, CREAM, MUTED = "#0a0d13", "#e8c77a", "#ece8df", "#9aa0aa"
FONT = '-apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif'


def card_html(body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{{margin:0;width:1920px;height:1080px;background:{BG};color:{CREAM};font-family:{FONT};}}
    .wrap{{position:absolute;inset:0;padding:120px 160px;display:flex;flex-direction:column;justify-content:center;}}
    .kicker{{color:{GOLD};font-size:34px;letter-spacing:4px;text-transform:uppercase;font-weight:700;margin-bottom:28px}}
    h1{{font-size:96px;line-height:1.08;margin:0 0 30px;font-weight:800;letter-spacing:-1.5px}}
    p{{font-size:44px;line-height:1.35;margin:0 0 18px;color:{CREAM};max-width:1500px}}
    .src{{font-size:28px;color:{MUTED};margin-top:30px}}
    .row{{display:flex;align-items:center;gap:36px;font-size:44px;margin:16px 0}}
    .row .pain{{width:560px;color:{MUTED}}} .row .arrow{{color:{GOLD}}} .row .fix{{font-weight:700}}
    .logo{{font-size:120px;font-weight:800;letter-spacing:-3px}} .logo b{{color:{GOLD}}}
    .foot{{position:absolute;left:160px;bottom:90px;font-size:30px;color:{MUTED}}}
    .tick{{color:{GOLD}}}
    </style></head><body><div class="wrap">{body}</div></body></html>"""


CARD_BODIES = {
    "01-title": '<div class="logo">Amend<b>.</b></div><p style="font-size:56px;margin-top:24px">When a brand deal changes, the money should too.</p>'
                '<div class="foot">PayPal AI Hackathon · PayPal sandbox demo</div>',
    "02-pain-1": '<div class="kicker">Pain 1 · Free extra work</div><h1>“Can you add<br>one more Story?”</h1>'
                 '<p>The deal changes after it’s signed. The price doesn’t. The creator does the extra work for free.</p>',
    "03-pain-2": '<div class="kicker">Pain 2 · Paid late</div><h1>30 days after posting.<br>Often later. Some wait 120.</h1>'
                 '<div class="src">Source: Digiday, Jan 2026</div>',
    "04-pain-3": '<div class="kicker">Pain 3 · “Did you deliver?”</div><h1>Proof is a screenshot.</h1>'
                 '<p>Disputes come down to who argues better.</p>',
    "05-pain-to-fix": '<div class="kicker">How Amend fixes each one</div>'
                      '<div class="row"><span class="pain">Free extra work</span><span class="arrow">→</span><span class="fix">a priced change card both confirm</span></div>'
                      '<div class="row"><span class="pain">Paid late</span><span class="arrow">→</span><span class="fix">a PayPal hold before any work</span></div>'
                      '<div class="row"><span class="pain">“Did you deliver?”</span><span class="arrow">→</span><span class="fix">checked from Instagram, signed</span></div>'
                      '<p style="margin-top:40px;color:#e8c77a">PayPal carries the money the whole way.</p>',
    "06-rebuild": '<div class="kicker">The proof</div><h1>The whole deal,<br>rebuilt from PayPal alone.</h1>'
                  '<p><span class="tick">✓</span> matches Amend, line by line, receipt hash included</p>',
    "07-same-engine": '<div class="kicker">Same engine, other uses</div><h1>Any deal that changes<br>after it’s signed.</h1>'
                      '<p>Contractors and suppliers · trades · AI agents buying services</p>',
    "08-end": '<div class="logo">Amend<b>.</b></div><p style="font-size:52px;margin-top:20px">AI reads · code decides · people confirm · '
              '<span style="color:#e8c77a">PayPal moves the money.</span></p>'
              '<div class="foot">PayPal sandbox demo · amend-r7le.onrender.com · github.com/alifiya-saifee/amend · all people and brands are made up</div>',
    "E-placeholder": '<div class="kicker">Scene E · to film Thu 12 Nov</div><h1>Bonus from Instagram views</h1>'
                     '<p>“Read from Instagram now” → tier met → Maya taps → bonus collected, the rest of its hold released.</p>',
    "F-placeholder": '<div class="kicker">Scene F · to film after the dispute is opened</div><h1>PayPal dispute → signed evidence</h1>'
                     '<p>Dispute banner → evidence pack → Send proof → RESOLVED.</p>',
}


def overlay_html(caption: str | None, label: str | None) -> str:
    cap = f'<div class="cap">{html.escape(caption)}</div>' if caption else ""
    lab = f'<div class="lab">{html.escape(label)}</div>' if label else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{{margin:0;width:1920px;height:1080px;background:transparent;font-family:{FONT};}}
    .cap{{position:absolute;left:50%;bottom:64px;transform:translateX(-50%);max-width:1480px;padding:18px 30px;border-radius:16px;
          background:rgba(10,13,19,.86);color:{CREAM};font-size:38px;line-height:1.3;text-align:center;font-weight:500}}
    .lab{{position:absolute;left:40px;top:34px;padding:12px 22px;border-radius:999px;background:rgba(10,13,19,.88);
          color:{GOLD};font-size:28px;font-weight:700;border:2px solid rgba(232,199,122,.6)}}
    </style></head><body>{lab}{cap}</body></html>"""


# (kind, source, start, end, caption, label[, speed])  kind: card | clip
LAB_A = "Pain: paid late → Fix: PayPal hold before work"
LAB_B = "Pain: free extra work → Fix: priced change card"
LAB_C = "Pain: “did you deliver?” → Fix: checked from Instagram, signed"
LAB_D = "Fix: PayPal collects only what was agreed"
TIMELINE = [
    ("card", "01-title", 0, 4.0, None, None),
    ("card", "02-pain-1", 0, 7.0, None, None),
    ("card", "03-pain-2", 0, 7.0, None, None),
    ("card", "04-pain-3", 0, 6.0, None, None),
    ("card", "05-pain-to-fix", 0, 4.5, None, None),
    # A · the hold (PayPal's own pages are cut out: 13.3 → 46.9 s)
    ("clip", "A-mandate-hold", 3.0, 13.3, "Before any work starts, Nadia signs what she’s willing to pre-approve…", LAB_A, (330, 280, 1300, 731)),
    ("clip", "A-mandate-hold", 47.0, 52.0, "…and PayPal places an authorization hold on her account. Nothing is collected yet.", LAB_A, (330, 0, 1300, 731)),
    ("clip", "A2-spine", 6.0, 12.5, "That’s a real PayPal authorization, with its twenty-nine-day clock.", LAB_A, (240, 0, 1440, 810)),
    # B · the voice note → change card
    ("clip", "B-voice-change-card", 2.2, 5.5, "Then the brand sends a voice note with four changes.", LAB_B, (200, 270, 1440, 810)),
    ("clip", "B-voice-change-card", 14.5, 17.0, "Then the brand sends a voice note with four changes.", LAB_B, (200, 270, 1440, 810)),
    ("clip", "B-voice-change-card", 27.0, 40.0, "The AI only reads, and quotes her exact words. Code prices every line from Maya’s own price list: free if it’s inside what was agreed, priced if it’s new work.", LAB_B, (180, 250, 1280, 720)),
    ("clip", "B2-maya-confirms", 3.0, 6.0, "Nadia sends it, Maya confirms, and the extra comes out of the hold Nadia already signed for.", LAB_B, (200, 220, 1280, 720)),
    # C · Instagram check: fail → fix → pass
    ("clip", "C1-instagram-check", 12.0, 18.6, "Maya posts. Amend reads the post straight from Instagram. #ad is missing, which the brand required, so code fails it and no money moves.", LAB_C, (200, 0, 1440, 810)),
    ("clip", "C-caption-edit-mac", 6.0, 13.5, "She fixes the caption on Instagram…", LAB_C, (736, 306, 1350, 759)),
    ("clip", "C2-instagram-check", 5.0, 13.0, "…Amend reads it again, and signs a new verdict.", LAB_C, (200, 0, 1440, 810)),
    # D · release
    ("clip", "D1-nadia-confirms", 4.0, 9.5, "Both confirm.", LAB_D, (180, 0, 1440, 810)),
    ("clip", "D2-maya-confirms-release", 5.5, 9.0, "Both confirm.", LAB_D, (240, 0, 1440, 810)),
    ("clip", "D2-maya-confirms-release", 30.0, 41.0, "PayPal collects exactly the agreed amount, and pays Maya and her editor in one Payouts batch. Every hold balances to the cent.", LAB_D, (820, 0, 1100, 619)),
    ("card", "E-placeholder", 0, 10.0, "Results come from Instagram itself, so the bonus Nadia signed is paid without a single screenshot.", "Fix: results from Instagram, not screenshots"),
    ("card", "F-placeholder", 0, 15.0, "And if a brand disputes later, Amend answers PayPal with signed evidence from the deal’s receipt chain. Resolved.", "Pain: disputes → Fix: signed evidence to PayPal"),
    # G · the proof
    ("clip", "G-rebuild-from-paypal", 5.5, 16.5, "Amend’s money doesn’t live in Amend. Here’s the whole deal, rebuilt from PayPal alone.", None, (180, 40, 1560, 878)),
    ("card", "06-rebuild", 0, 1.5, None, None),
    ("card", "07-same-engine", 0, 6.0, None, None),
    ("card", "08-end", 0, 6.0, None, None),
]


def render_pngs():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        for name, body in CARD_BODIES.items():
            pg.set_content(card_html(body)); pg.wait_for_timeout(150)
            pg.screenshot(path=str(CARDS / f"{name}.png"))
        for i, seg in enumerate(TIMELINE):
            cap, lab = seg[4], seg[5]
            pg.set_content(overlay_html(cap, lab)); pg.wait_for_timeout(80)
            pg.screenshot(path=str(OVL / f"{i:02d}.png"), omit_background=True)
        b.close()


def card_path(name: str) -> Path:
    mine = HERS / f"{name}.png"
    return mine if mine.exists() else CARDS / f"{name}.png"


def clip_path(name: str) -> Path:
    for ext in (".webm", ".mov", ".mp4"):
        if (CLIPS / f"{name}{ext}").exists():
            return CLIPS / f"{name}{ext}"
    raise FileNotFoundError(name)


def ff(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def build():
    render_pngs()
    parts, t, log = [], 0.0, []
    for i, seg in enumerate(TIMELINE):
        kind, src, a, z, cap, lab = seg[:6]
        crop = seg[6] if len(seg) > 6 else None
        out = SEG / f"{i:02d}.mp4"
        dur = z - a
        zoom = f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}," if crop else ""  # zoom on what matters in the shot
        base = zoom + "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0a0d13,setsar=1,fps=30"
        if kind == "card":
            ff("-loop", "1", "-t", f"{dur}", "-i", str(card_path(src)), "-i", str(OVL / f"{i:02d}.png"),
               "-filter_complex", f"[0:v]{base}[v];[v][1:v]overlay=0:0,format=yuv420p",
               "-t", f"{dur}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-an", str(out))
        else:
            ff("-ss", f"{a}", "-t", f"{dur}", "-i", str(clip_path(src)), "-i", str(OVL / f"{i:02d}.png"),
               "-filter_complex", f"[0:v]{base}[v];[v][1:v]overlay=0:0,format=yuv420p",
               "-t", f"{dur}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-an", str(out))
        parts.append(out)
        log.append({"at": round(t, 1), "len": round(dur, 1), "what": f"{kind}:{src}", "caption": cap, "label": lab})
        t += dur
    lst = SEG / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    joined = SEG / "joined.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined))
    final = V / "amend-draft.mp4"
    ff("-i", str(joined), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "copy", "-c:a", "aac",
       "-movflags", "+faststart", str(final))
    (V / "amend-draft.timeline.json").write_text(json.dumps(log, indent=1))
    print(f"draft: {final} · {t:.1f} s ({int(t // 60)}:{t % 60:04.1f})")


if __name__ == "__main__":
    build()
