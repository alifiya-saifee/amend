"""The judges' "Demo history": one completed deal between judge.sara and the judges' brand, made by the real engine
with the fake PayPal, every PayPal ID starting DEMO (so screens label it demo, never checked at PayPal). Once only;
nothing without JUDGE_PASSWORD; other deals' holdbacks are never touched."""
import asyncio

from amend.db import get_db
from scripts.seed import JUDGE_DEMO_TITLE, ensure_judge_accounts, ensure_judge_demo_history

from .test_booking import client  # noqa: F401
from .test_judges import JUDGE_PW, judge_env, login  # noqa: F401


def seed():
    ensure_judge_accounts(get_db())
    return asyncio.run(ensure_judge_demo_history(get_db()))


def demo_deal():
    return get_db().one("select * from deals where title = :t", {"t": JUDGE_DEMO_TITLE})


def test_nothing_without_a_judge_password(client):
    assert asyncio.run(ensure_judge_demo_history(get_db())) == 0
    assert not demo_deal()


def test_one_completed_demo_deal_once(client, judge_env):
    assert seed() == 1
    assert asyncio.run(ensure_judge_demo_history(get_db())) == 0  # a restart adds nothing
    assert len(get_db().all("select id from deals where title = :t", {"t": JUDGE_DEMO_TITLE})) == 1
    d = demo_deal()
    assert d["status"] == "completed" and d["is_demo"] == 1 and d["version"] == 2  # one confirmed change
    items = get_db().all("select * from money_items where deal_id = :d", {"d": d["id"]})
    assert items and all(str(i["paypal_id"]).startswith("DEMO") for i in items if i["paypal_id"])
    kinds = {i["kind"] for i in items if i["status"] == "paid"}
    assert {"capture", "payout"} <= kinds


def test_both_judge_accounts_see_it(client, judge_env):
    seed()
    d = demo_deal()
    assert login(client, "judge.sara@creators.example", JUDGE_PW, "creator").status_code == 200
    for path in ("/api/studio/deals", "/api/studio/earnings", "/api/studio/ledger", "/api/studio/inbox"):
        r = client.get(path)
        assert r.status_code == 200 and d["id"] in r.text, path
    assert client.get(f"/api/deals/{d['id']}/paypal-map").json()["stages"]["authorization"]
    client.post("/logout", headers={"Origin": "http://testserver"})
    assert login(client, "judge.brand@amend.example", JUDGE_PW, "brand").status_code == 200
    for path in ("/api/brand/deals", "/api/brand/payments", "/api/brand/inbox"):
        r = client.get(path)
        assert r.status_code == 200 and d["id"] in r.text, path


def test_labelled_demo_never_checked_at_paypal(client, judge_env):
    from amend import spine
    seed()
    d = demo_deal()
    hold = get_db().one("select * from money_items where deal_id = :d and kind = 'hold' order by created_at limit 1", {"d": d["id"]})
    assert spine.conservation(get_db(), hold)["ok"] is None
