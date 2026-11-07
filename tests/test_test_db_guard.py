"""The guard that keeps the Postgres tests away from the live database."""
from .conftest import unsafe_test_db

LIVE = "postgresql://postgres.liveref123:pw@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
TEST = "postgresql://postgres.testref456:pw@aws-0-eu-central-1.pooler.supabase.com:5432/postgres?application_name=amend-test"


def test_safe_separate_project():
    assert unsafe_test_db(TEST, [LIVE]) is None


def test_same_url_refused():
    assert "same" in unsafe_test_db(TEST, [TEST])


def test_same_project_with_a_different_password_or_label_refused():
    same_project = "postgresql://postgres.liveref123:other@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?application_name=amend-test"
    assert "same Supabase project" in unsafe_test_db(same_project, [LIVE])


def test_direct_and_pooler_urls_of_one_project_match():
    direct = "postgresql://postgres:pw@db.liveref123.supabase.co:5432/postgres?application_name=test"
    assert "same Supabase project" in unsafe_test_db(direct, [LIVE])


def test_must_say_test():
    no_label = "postgresql://postgres.abcref456:pw@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    assert '"test"' in unsafe_test_db(no_label, [LIVE])


def test_must_be_postgres():
    assert "Postgres" in unsafe_test_db("sqlite:///test.db", [])
