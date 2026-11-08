import inspect
from types import SimpleNamespace

import pytest

import main
from abstract_customer import get_contact_json
from main import _dedupe_by_crm_id, _nested_rows, collect_leads_customers


class Entity:
    def __init__(self, crm_id, name="entity"):
        self.id = crm_id
        self.name = name


class FakeCustomer:
    def __init__(self, crm_id, login="buyer", name="Customer", contacts=None, companies=None):
        self.id = crm_id
        self.name = name
        self.custom_fields_values = {"Логин": {"value": login}} if login else {}
        self.contacts = contacts or []
        self.companies = companies or []


class FakeLead:
    def __init__(self, crm_id, login="buyer", name="Lead", contacts=None):
        self.id = crm_id
        self.name = name
        self.custom_fields_values = {"Логин": {"value": login}} if login else {}
        self.contacts = contacts or []


class Session:
    """Заглушка сессии: батч-хелперы в тестах подменяются."""


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _capture_upserts(monkeypatch):
    captured = []

    def fake_upsert(session, model, rows, **kwargs):
        captured.append((model, rows))
        return len(rows)

    monkeypatch.setattr(main, "upsert_rows", fake_upsert)
    return captured


def _fake_create(monkeypatch, first_id=9000):
    def fake_create_abstract_customers(session, count):
        return list(range(first_id, first_id + count))

    monkeypatch.setattr(main, "_create_abstract_customers", fake_create_abstract_customers)


def test_public_entry_point_is_unchanged():
    signature = inspect.signature(collect_leads_customers)

    assert list(signature.parameters) == ["is_full"]
    assert signature.parameters["is_full"].default is True


def test_dedupe_by_crm_id_keeps_last_occurrence():
    first = Entity(1, "first")
    second = Entity(1, "second")
    without_id = Entity(None, "new-a")
    another_without_id = Entity(None, "new-b")

    result = _dedupe_by_crm_id([first, second, without_id, another_without_id])

    assert result[0] is second
    assert result[1:] == [without_id, another_without_id]


def test_nested_rows_handles_entities_without_id():
    rows = _nested_rows(
        [{"id": None, "name": "new"}, {"id": 5, "name": "contact"}],
        abstract_customer_id=10,
        run_id=42,
        serializer=get_contact_json,
    )

    assert rows[0]["crm_id"] is None
    assert rows[0]["abstract_customer_id"] == 10
    assert rows[0]["sync_run_id"] == 42
    assert rows[0]["data"]["general"]["name"] == "new"
    assert rows[1]["crm_id"] == 5


def test_nested_rows_accepts_none_instead_of_a_list():
    assert _nested_rows(None, 1, 2, get_contact_json) == []


def test_customer_batch_uses_crm_id_then_creates_a_new_aggregate(monkeypatch):
    _fake_create(monkeypatch, first_id=9000)
    captured = _capture_upserts(monkeypatch)
    monkeypatch.setattr(main, "load_customer_id_map", lambda ids: {1: 100})
    monkeypatch.setattr(main, "load_login_map", lambda model, logins: {})

    main._process_customer_batch(
        Session(),
        [FakeCustomer(1), FakeCustomer(2, contacts=[{"id": 50, "name": "c"}])],
        is_full=True,
        run_id=42,
    )

    customer_rows = captured[0][1]
    assert [(row["crm_id"], row["abstract_customer_id"]) for row in customer_rows] == [
        (1, 100),
        (2, 9000),
    ]
    assert customer_rows[1]["sync_run_id"] == 42
    assert captured[1][1][0]["abstract_customer_id"] == 9000


def test_lead_batch_merges_login_match_into_crm_id_record(monkeypatch):
    _fake_create(monkeypatch)
    captured = _capture_upserts(monkeypatch)
    merges = []

    monkeypatch.setattr(main, "load_lead_id_map", lambda ids: {7: 10})
    monkeypatch.setattr(main, "load_login_map", lambda model, logins: {"buyer": {20}})
    monkeypatch.setattr(
        main, "_merge_abstract_customers",
        lambda session, merge_map, run_id: merges.append(merge_map),
    )

    main._process_lead_batch(Session(), [FakeLead(7)], is_full=True, run_id=42)

    assert merges == [{20: 10}]
    lead_rows = captured[0][1]
    assert lead_rows[0]["crm_id"] == 7
    assert lead_rows[0]["abstract_customer_id"] == 10


def test_lead_batch_flattens_merge_chains(monkeypatch):
    _fake_create(monkeypatch)
    captured = _capture_upserts(monkeypatch)
    merges = []

    monkeypatch.setattr(main, "load_lead_id_map", lambda ids: {7: 10, 8: 20})
    monkeypatch.setattr(
        main, "load_login_map",
        lambda model, logins: {"login-a": {20}, "login-b": {30}},
    )
    monkeypatch.setattr(
        main, "_merge_abstract_customers",
        lambda session, merge_map, run_id: merges.append(merge_map),
    )

    main._process_lead_batch(
        Session(),
        [FakeLead(7, login="login-a"), FakeLead(8, login="login-b")],
        is_full=True,
        run_id=42,
    )

    assert merges == [{20: 10, 30: 10}]
    assert [row["abstract_customer_id"] for row in captured[0][1]] == [10, 10]


def _prepare_entry_point(monkeypatch, fake_get):
    session = FakeSession()
    cleanups = []

    monkeypatch.setattr(main, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(main, "amocrm_get", fake_get)
    monkeypatch.setattr(main, "_process_customer_batch", lambda *args: None)
    monkeypatch.setattr(main, "_process_lead_batch", lambda *args: [])
    monkeypatch.setattr(
        main, "_cleanup", lambda session_arg, run_id: cleanups.append(run_id),
    )
    return session, cleanups


def test_entry_point_runs_cleanup_after_a_successful_full_pass(monkeypatch):
    def fake_get(cls, **kwargs):
        return iter([object()])

    session, cleanups = _prepare_entry_point(monkeypatch, fake_get)

    collect_leads_customers(is_full=True)

    assert session.commits == 2
    assert len(cleanups) == 1
    assert session.rollbacks == 0


def test_entry_point_does_not_run_cleanup_when_collection_breaks(monkeypatch):
    def fake_get(cls, **kwargs):
        if cls.__name__ == "Lead":
            raise RuntimeError("CRM is down")
        return iter([object()])

    session, cleanups = _prepare_entry_point(monkeypatch, fake_get)

    with pytest.raises(RuntimeError):
        collect_leads_customers(is_full=True)

    assert cleanups == []
    assert session.rollbacks == 1


def test_entry_point_does_not_clean_up_partial_runs(monkeypatch):
    def fake_get(cls, **kwargs):
        return iter([object()])

    session, cleanups = _prepare_entry_point(monkeypatch, fake_get)

    collect_leads_customers(is_full=False)

    assert cleanups == []
    assert session.commits == 2
