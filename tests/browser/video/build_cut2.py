"""Draft 2 of the demo video, to Alifiya's edit rules (11 Nov):

- Every app shot sits in a fixed area (1536×864 at x 192, y 72) on Amend's dark background. Scene labels live in the band
  above it and captions in the lower-third band below it (max 2 lines), so neither ever covers a number.
- Each zoom frames whole UI components: the box is the component plus ≥ 40 px margin (source pixels), scaled at most
  160 % to fit the shot area, and centred; a tall or wide component is panned instead of cut.
- Proof close-ups are stills held ~1.2 s: the mandate lines, $680 held + the authorization ID, the card total,
  $450 collected, the payout lines, the balance ✓, "matches Amend ✓".
- No Results card (0 views) before Scene E; the Team panel (an email) never appears; the Instagram shot is under 3 s.
- A bridge card before Deal B. Motion clips docs/video/act1-opening.mp4 / act3-closing.mp4 replace the title and end
  cards when they exist.
Output: docs/video/amend-draft-2.mp4 (+ timeline JSON). Silent AAC track; the voice goes on later.
"""
from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cut import BG, CARD_BODIES, CARDS, CLIPS, CREAM, FONT, GOLD, V, card_html  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

OVL, SEG, STILL = V / "overlays2", V / "segments2", V / "stills"
for d in (OVL, SEG, STILL):
    d.mkdir(parents=True, exist_ok=True)
AREA_X, AREA_Y, AREA_W, AREA_H, MAXZ = 192, 72, 1536, 864, 1.6

CARD_BODIES = dict(CARD_BODIES)
CARD_BODIES["bridge"] = ('<div class="kicker">Same flow, a delivered deal</div><h1>$450 Reel<br>+ a $30 bonus hold</h1>'
                         '<p>Maya × Dune Roast Coffee, posted on Instagram today.</p>')

LA, LB = "Pain: paid late → Fix: PayPal hold before work", "Pain: free extra work → Fix: priced change card"
LC, LD = "Pain: “did you deliver?” → Fix: checked from Instagram, signed", "Fix: PayPal collects only what was agreed"
LG = "Proof: rebuilt from PayPal alone"

# card(name, dur, caption?) · clip(src, a, z, box, caption, label, pan=(y0, y1)?) · still(src, t, box, dur, caption, label)
T = [
    ("card", "01-title", 4.0, None), ("card", "02-pain-1", 7.0, None), ("card", "03-pain-2", 7.0, None),
    ("card", "04-pain-3", 6.0, None), ("card", "05-pain-to-fix", 4.5, None),
    # A · the hold
    ("clip", "A-mandate-hold", 3.0, 13.3, (305, 100, 803, 540), "Before any work starts, Nadia signs what she’s willing to pre-approve…", LA, (100, 517)),
    ("still", "A-mandate-hold", 11.8, (329, 347, 755, 593), 1.3, "…an extra Story up to $150, and #ad on every post.", LA),
    ("clip", "A-mandate-hold", 47.0, 50.5, (305, 45, 1532, 862), "…and PayPal places an authorization hold on her account. Nothing is collected yet.", LA),
    ("still", "A-mandate-hold", 51.0, (1060, 535, 555, 372), 1.3, "$680 held by PayPal, with a real authorization ID.", LA),
    ("clip", "A2-spine", 7.0, 8.5, (1060, 250, 555, 630), "Every PayPal object behind the deal, with the hold’s twenty-nine-day clock.", LA),
    ("still", "A2-spine", 8.2, (1060, 250, 555, 630), 3.0, "Every PayPal object behind the deal, with the hold’s twenty-nine-day clock.", LA),
    # B · the voice note → a priced change card
    ("clip", "B-voice-change-card", 2.5, 5.5, (242, 203, 878, 857), "Then the brand sends a voice note with four changes.", LB),
    ("clip", "B-voice-change-card", 21.5, 25.0, (284, 668, 806, 267), "Then the brand sends a voice note with four changes.", LB),
    ("clip", "B-voice-change-card", 27.0, 38.6, (275, 360, 815, 530), "The AI only reads, and quotes her exact words. Code prices every line from Maya’s own price list: free if it’s inside what was agreed, priced if it’s new work.", LB),
    ("still", "B-voice-change-card", 36.0, (275, 662, 815, 118), 1.3, "+$240, every line from her list.", LB),
    ("clip", "B2-maya-confirms", 3.0, 5.2, (281, 296, 817, 589), "Nadia sends it, Maya confirms…", LB),
    ("clip", "B2-maya-confirms", 9.3, 12.0, (281, 296, 817, 589), "…and the extra comes out of the hold Nadia already signed for.", LB),
    ("card", "bridge", 2.0, "The same flow on a delivered deal: a $450 Reel, plus a $30 bonus held separately."),
    # C · Instagram: fail → fix → pass
    ("clip", "C1-instagram-check", 15.2, 16.8, (256, 0, 872, 540), "Maya posts. Amend reads the post straight from Instagram.", LC),
    ("still", "C1-instagram-check", 16.5, (256, 0, 872, 540), 1.6, "#ad is missing, which the brand required, so code fails it…", LC),
    ("clip", "C2-instagram-check", 5.5, 7.2, (256, 328, 872, 500), "…and no money moves until it’s fixed.", LC),
    ("clip", "C-caption-edit-mac", 10.2, 11.7, (1380, 320, 694, 330), "She fixes the caption on Instagram…", LC),
    ("still", "C-caption-edit-mac", 12.4, (1910, 20, 530, 190), 1.3, "She fixes the caption on Instagram…", LC),
    ("clip", "C2-instagram-check", 12.9, 14.3, (260, 80, 845, 295), "…Amend reads it again, and signs a new verdict.", LC),
    ("still", "C2-instagram-check", 14.2, (260, 80, 845, 295), 1.5, "…Amend reads it again, and signs a new verdict.", LC),
    # D · release
    ("clip", "D1-nadia-confirms", 4.0, 9.5, (260, 262, 838, 393), "Both confirm.", LD),
    ("clip", "D2-maya-confirms-release", 5.5, 8.9, (268, 262, 834, 401), "Both confirm.", LD),
    ("still", "D2-maya-confirms-release", 35.0, (1078, 373, 605, 262), 1.3, "PayPal collects exactly the agreed amount: $450.", LD),
    ("still", "D2-maya-confirms-release", 8.8, (268, 262, 834, 401), 1.3, "Maya and her editor are paid in one Payouts batch; $45 is held back.", LD),
    ("still", "D2-maya-confirms-release", 41.5, (1092, 525, 568, 187), 1.3, "Every hold balances to the cent.", LD),
    ("card", "E-placeholder", 10.0, "Results come from Instagram itself, so the bonus Nadia signed is paid without a single screenshot."),
    ("card", "F-placeholder", 15.0, "And if a brand disputes later, Amend answers PayPal with signed evidence from the deal’s receipt chain. Resolved."),
    # G · the proof
    ("clip", "G-rebuild-from-paypal", 5.5, 16.5, (260, 118, 1400, 844), "Amend’s money doesn’t live in Amend. Here’s the whole deal, rebuilt from PayPal alone.", LG),
    ("still", "G-rebuild-from-paypal", 15.5, (260, 150, 1400, 185), 1.3, "Rebuilt from PayPal: matches Amend, receipt hash included.", LG),
    ("card", "07-same-engine", 6.0, None), ("card", "08-end", 6.0, None),
]
MOTION = {"01-title": V / "act1-opening.mp4", "08-end": V / "act3-closing.mp4"}


def overlay_html(caption, label):
    lab = f'<div class="lab">{html.escape(label)}</div>' if label else ""
    cap = f'<div class="cap">{html.escape(caption)}</div>' if caption else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{{margin:0;width:1920px;height:1080px;background:transparent;font-family:{FONT};}}
    .lab{{position:absolute;left:{AREA_X}px;top:14px;padding:8px 18px;border-radius:999px;background:#151a24;color:{GOLD};
          font-size:24px;font-weight:700;border:1.5px solid rgba(232,199,122,.55)}}
    .cap{{position:absolute;left:{AREA_X}px;width:{AREA_W}px;top:{AREA_Y + AREA_H + 14}px;height:116px;box-sizing:border-box;
          display:flex;align-items:center;justify-content:center;text-align:center;color:{CREAM};font-size:33px;line-height:1.3;
          font-weight:500;overflow:hidden}}
    </style></head><body>{lab}{cap}</body></html>"""


def fit(box):
    _, _, w, h = box
    s = min(MAXZ, AREA_W / w, AREA_H / h)
    ow, oh = int(round(w * s / 2) * 2), int(round(h * s / 2) * 2)
    return ow, oh, AREA_X + (AREA_W - ow) // 2, AREA_Y + (AREA_H - oh) // 2


def ff(*a):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *a], check=True)


def clip_path(name):
    for ext in (".webm", ".mov", ".mp4"):
        if (CLIPS / f"{name}{ext}").exists():
            return CLIPS / f"{name}{ext}"
    raise FileNotFoundError(name)


def build():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        for name, body in CARD_BODIES.items():
            pg.set_content(card_html(body)); pg.wait_for_timeout(120)
            pg.screenshot(path=str(CARDS / f"{name}.png"))
        for i, seg in enumerate(T):
            cap, lab = (seg[3], None) if seg[0] == "card" else (seg[5], seg[6])
            pg.set_content(overlay_html(cap, lab)); pg.wait_for_timeout(60)
            pg.screenshot(path=str(OVL / f"{i:02d}.png"), omit_background=True)
        b.close()
    parts, t, log = [], 0.0, []
    for i, seg in enumerate(T):
        out, ovl = SEG / f"{i:02d}.mp4", OVL / f"{i:02d}.png"
        enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", "-an"]
        if seg[0] == "card":
            name, dur = seg[1], seg[2]
            motion = MOTION.get(name)
            if motion and motion.exists():
                ff("-i", str(motion), "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0a0d13,fps=30",
                   *enc, str(out))
                dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                                           capture_output=True, text=True).stdout)
            else:
                ff("-loop", "1", "-t", f"{dur}", "-i", str(CARDS / f"{name}.png"), "-i", str(ovl),
                   "-filter_complex", "[0:v][1:v]overlay=0:0", "-t", f"{dur}", *enc, str(out))
            what = f"card:{name}"
        else:
            if seg[0] == "clip":
                _, src, a, z, box, cap, lab, *rest = seg
                pan, dur = (rest[0] if rest else None), z - a
                inp = ["-ss", f"{a}", "-t", f"{dur}", "-i", str(clip_path(src))]
            else:
                _, src, at, box, dur, cap, lab = seg
                pan = None
                frame = STILL / f"{i:02d}.png"
                ff("-ss", f"{at}", "-i", str(clip_path(src)), "-frames:v", "1", str(frame))
                inp = ["-loop", "1", "-t", f"{dur}", "-i", str(frame)]
            x, y, w, h = box
            ow, oh, ox, oy = fit(box)
            ypos = f"'{pan[0]}+({pan[1]}-{pan[0]})*min(t/{dur},1)'" if pan else f"{y}"
            fc = (f"color=c=0x0a0d13:s=1920x1080:d={dur}:r=30[bg];"
                  f"[0:v]crop={w}:{h}:{x}:{ypos},scale={ow}:{oh}:flags=lanczos,setsar=1[shot];"
                  f"[bg][shot]overlay={ox}:{oy}:shortest=1[v];[v][1:v]overlay=0:0")
            ff(*inp, "-i", str(ovl), "-filter_complex", fc, "-t", f"{dur}", *enc, str(out))
            what = f"{seg[0]}:{src}"
        parts.append(out)
        log.append({"at": round(t, 1), "len": round(dur, 2), "what": what})
        t += dur
    lst = SEG / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    joined = SEG / "joined.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined))
    final = V / "amend-draft-2.mp4"
    ff("-i", str(joined), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "copy", "-c:a", "aac",
       "-movflags", "+faststart", str(final))
    (V / "amend-draft-2.timeline.json").write_text(json.dumps(log, indent=1))
    print(f"draft 2: {final} · {t:.1f} s ({int(t // 60)}:{t % 60:04.1f})")


if __name__ == "__main__":
    build()
