"""Scenes A and B on Deal A (live site, PayPal sandbox), recorded at 1920×1080.

A · Nadia's brand room: pre-approve an extra Story up to $150 + #ad → "Pay with PayPal: hold $680" → (PayPal sandbox:
    raw clip only, cut in the edit) → "$680 held by PayPal" → the spine: authorization ID, day 1 of 29, headroom.
B · Nadia's voice note (a file played as the microphone) → "From your voice note: this looks like a change to the
    deal" with the priced lines → Send change card → Maya confirms → version 2 → the money line.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rec import B, ROOT, Scene, paypal_approve, signed_in_state  # noqa: E402

DEALS = json.loads((ROOT / "docs" / "video" / "deals.json").read_text())
A = DEALS["A"]
LINK, DEAL = A["brand_link"], A["deal"]
WAV = ROOT / "docs" / "video" / "voice_note.wav"
ONLY = sys.argv[1:] or ["A", "B"]

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                f"--use-file-for-fake-audio-capture={WAV}"])
    if "A" in ONLY:
        with Scene(b, "A-mandate-hold") as sc:
            pg = sc.page
            pg.goto(LINK, timeout=120000); pg.wait_for_selector("#pay", timeout=90000)
            if pg.query_selector("#welcome-go"): pg.click("#welcome-go"); pg.wait_for_timeout(400)
            if pg.query_selector("#yes"): pg.click("#yes"); pg.wait_for_timeout(1500)
            sc.hold(1.2); sc.mark("brand room, offer $530")
            sc.click("#mbox summary", after=0.8); sc.mark("pre-approve box open")
            sc.click("#m-x", after=0.4)
            pg.select_option("#m-item", "story_set"); pg.fill("#m-max", "150"); pg.dispatch_event("#m-max", "input")
            sc.glide("#m-max", pause=0.5)
            sc.click("#m-ad", after=0.6); sc.mark("extra Story up to $150 + #ad ticked")
            sc.glide("#hold-sum" if pg.query_selector("#hold-sum") else "#pay", pause=1.6); sc.mark("hold sum $530 + $150 = $680")
            sc.glide("#pay", pause=0.8); sc.mark("Pay with PayPal: hold $680")
            pg.click("#pay"); sc.mark("left for PayPal (cut from here)")
            paypal_approve(pg); sc.mark("back from PayPal (cut to here)")
            pg.wait_for_timeout(2500); sc.hold(1.0); sc.mark("$680 held by PayPal banner")
            pg.goto(LINK.split("#")[0] + "#money"); pg.reload(); pg.wait_for_selector(".spine", timeout=60000); pg.wait_for_timeout(2500)
            sc.glide(".spine", pause=1.0); sc.mark("spine: authorization ID, day 1 of 29, headroom")
            pg.mouse.wheel(0, 300); sc.hold(2.5); sc.mark("spine detail")
    if "A2" in ONLY:  # the spine after the hold: authorization ID, day 1 of 29, headroom
        with Scene(b, "A2-spine") as sc:
            pg = sc.page
            pg.goto(LINK.split("#")[0] + "#money", timeout=120000); pg.wait_for_selector(".spine:visible", timeout=90000); pg.wait_for_timeout(2500)
            sc.hold(1.0); sc.mark("money tab")
            sp = pg.locator(".spine:visible").first
            sp.scroll_into_view_if_needed(); sc.glide(".spine:visible", pause=1.5); sc.mark("spine: authorization ID, day 1 of 29")
            print("  spine:", " ".join(sp.inner_text().split())[:500], flush=True)
            pg.mouse.wheel(0, 250); sc.hold(2.5); sc.mark("headroom / clock")
    if "B" in ONLY:
        maya_state = signed_in_state(b, "clinicrobotest@creators.example", "creator")
        with Scene(b, "B-voice-change-card") as sc:
            pg = sc.page
            pg.goto(LINK.split("#")[0] + "#chat", timeout=120000); pg.wait_for_selector("#chat-in", timeout=90000)
            pg.locator("#chat-list").scroll_into_view_if_needed(); sc.hold(1.0); sc.mark("brand chat")
            sc.click("#chat-mic", after=0.2); sc.mark("recording voice note")
            pg.wait_for_timeout(9800)
            sc.click("#chat-mic", after=0.5); sc.mark("voice note sent")
            pg.wait_for_selector(".askcard", timeout=120000); pg.wait_for_timeout(1500)
            pg.locator(".askcard").scroll_into_view_if_needed(); sc.mark("From your voice note: this looks like a change")
            for i in range(pg.locator(".askcard .line").count()):
                sc.glide(f".askcard .line >> nth={i}", pause=1.1)
            sc.mark("lines read"); sc.glide(".askcard .num", pause=1.4); sc.mark("total")
            print("  ask panel:", " ".join(pg.inner_text(".askcard").split())[:400], flush=True)
            sc.click(".askcard [data-act=send]", after=2.0); sc.mark("Send change card")
        with Scene(b, "B2-maya-confirms", storage=maya_state) as sc:
            pg = sc.page
            pg.goto(f"{B}/studio/deals/{DEAL}#chat", timeout=120000); pg.wait_for_selector(".changecard.previewed", timeout=90000)
            pg.locator(".changecard.previewed").last.scroll_into_view_if_needed(); sc.hold(1.5); sc.mark("Maya sees the card")
            print("  card for Maya:", " ".join(pg.locator(".changecard.previewed").last.inner_text().split())[:400], flush=True)
            conf = ".changecard.previewed [data-act=confirm]"
            if pg.query_selector(conf):
                sc.click(conf, after=0.3); sc.mark("Maya confirms")
            pg.wait_for_timeout(2500)  # the page redraws: back to the card (never the Team panel: it shows an email)
            pg.goto(f"{B}/studio/deals/{DEAL}#chat"); pg.wait_for_selector(".changecard", timeout=60000); pg.wait_for_timeout(1500)
            pg.locator(".changecard").last.scroll_into_view_if_needed(); sc.hold(2.5); sc.mark("version 2 / money line")
            print("  after confirm:", " ".join(pg.inner_text("#chat-list").split())[-300:], flush=True)
    b.close()
