"""Deal A for the video (live site, PayPal sandbox, nothing recorded): Maya × Dune Roast Coffee (Nadia).
Maya makes the deal link → Nadia (link only) says it's her and sends the brief → Maya accepts → Maya adds her editor
(20 %, the sandbox editor account) → stop before the hold (the hold and the mandate are filmed in Scene A).
Prints the deal ID and the brand link; saves them to docs/video/deals.json (no secrets in it)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rec import B, ROOT, S, signed_in_state  # noqa: E402

BRIEF = ("Hi Maya! For our new Dune Roast cold brew: 1 Reel showing it at home, plus 1 Story set. "
         "Post Friday. Start the caption with #ad and tag @duneroast.")
OUT = ROOT / "docs" / "video" / "deals.json"

with sync_playwright() as p:
    b = p.chromium.launch()
    maya = b.new_context(storage_state=signed_in_state(b, "clinicrobotest@creators.example", "creator"))
    r = maya.request.post(B + "/api/deals", data={"brand_org": "Dune Roast Coffee", "contact_name": "Nadia"}, headers={"Origin": B})
    assert r.status == 200, r.text()
    deal, link = r.json()["deal"], r.json()["link"]
    tok = link.rstrip("/").split("/")[-1]
    brand = b.new_context()
    assert brand.request.post(f"{B}/api/d/{tok}/whoami", data={"is_me": True}, headers={"Origin": B}).status == 200
    r = brand.request.post(f"{B}/api/d/{tok}/brief", data={"brief": BRIEF}, headers={"Origin": B}, timeout=120000)
    assert r.status == 200, r.text()[:300]
    v = r.json()
    print("offer:", [(t["name"], t["qty"], t["amount_cents"]) for t in v.get("terms", [])], "total", v.get("total_cents"), flush=True)
    for _ in range(3):
        r = maya.request.post(f"{B}/api/deals/{deal}/accept", headers={"Origin": B})
        if r.status == 200:
            break
        print("accept:", r.status, r.text()[:200], flush=True); time.sleep(3)
    assert r.status == 200, r.text()[:300]
    if S.sandbox_editor_email:
        r = maya.request.put(f"{B}/api/deals/{deal}/team", headers={"Origin": B},
                             data={"members": [{"role": "Editor", "email": S.sandbox_editor_email, "pct": 20}], "refund_rule": "shared"})
        print("team:", r.status, "(editor 20 %, shared refund rule)" if r.status == 200 else r.text()[:200], flush=True)
    else:
        print("team: no SANDBOX_EDITOR_EMAIL in settings, skipped", flush=True)
    d = maya.request.get(f"{B}/api/deals/{deal}").json()["deal"]
    print("deal A:", deal, "status", d["status"], "total", d["total_cents"], "deadline", d.get("deadline"), flush=True)
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    data["A"] = {"deal": deal, "brand_link": link, "made": time.strftime("%Y-%m-%d %H:%M")}
    OUT.write_text(json.dumps(data, indent=1))
    b.close()
