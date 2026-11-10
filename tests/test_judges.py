"""Judges-only logins: their own password (JUDGE_PASSWORD, Render env only), never the shared demo password; nothing is
created without it; the judge's clean Sara doesn't show twice in Discover."""
import pytest

from amend.config import get_settings
from amend.db import get_db
from scripts.seed import ensure_judge_accounts

from .test_booking import ORIGIN, client  # noqa: F401

JUDGE_PW = "judge-only-test-pw"


@pytest.fixture
def judge_env(monkeypatch):
    monkeypatch.setenv("JUDGE_PASSWORD", JUDGE_PW)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def login(client, email, pw, kind):
    return client.post("/login", json={"email": email, "password": pw, "kind": kind}, headers=ORIGIN)


def test_nothing_without_a_judge_password(client):
    assert ensure_judge_accounts(get_db()) == 0
    assert not get_db().one("select id from accounts where email like 'judge.%'")


def test_judges_sign_in_with_their_own_password_only(client, judge_env):
    assert ensure_judge_accounts(get_db()) == 2 and ensure_judge_accounts(get_db()) == 0  # idempotent
    assert login(client, "judge.brand@amend.example", JUDGE_PW, "brand").status_code == 200
    client.post("/logout", headers=ORIGIN)
    assert login(client, "judge.sara@creators.example", JUDGE_PW, "creator").status_code == 200
    client.post("/logout", headers=ORIGIN)
    assert login(client, "judge.brand@amend.example", "test-demo-pw", "brand").status_code != 200   # demo password: no
    assert login(client, "nadia@duneroast.example", JUDGE_PW, "brand").status_code != 200           # judge password: no
    assert login(client, "nadia@duneroast.example", "test-demo-pw", "brand").status_code == 200


def test_judge_sara_has_her_price_list_and_no_history(client, judge_env):
    ensure_judge_accounts(get_db())
    c = get_db().one("select id from creators where handle = 'judge.sara'")
    assert get_db().one("select count(*) as n from price_items where creator_id = :c", {"c": c["id"]})["n"] >= 5
    assert get_db().one("select count(*) as n from deals where creator_id = :c", {"c": c["id"]})["n"] == 0


def test_judge_sara_is_not_a_second_sara_in_discover(client, judge_env):
    ensure_judge_accounts(get_db())
    handles = [x["handle"] for x in client.get("/api/creators").json()["creators"]]
    assert "judge.sara" not in handles and "sara.video" not in handles
