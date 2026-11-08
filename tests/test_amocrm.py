import pytest

import amocrm
from amocrm import (
    AmoCrmError,
    AmoCrmNoConten,
    AmoCrmRepeatError,
    Customer,
    Lead,
    extract_entities,
    get_next_href,
    normalize_custom_fields,
    response_handler,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, url="http://crm"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.url = url
        self.request = type("Request", (), {"method": "GET"})()

    def json(self):
        return self._payload


def test_extract_entities_handles_normal_page():
    payload = {"_embedded": {"leads": [{"id": 1}, {"id": 2}]}}
    assert extract_entities(payload, "leads") == [{"id": 1}, {"id": 2}]


@pytest.mark.parametrize("payload", [
    {},
    {"_embedded": None},
    {"_embedded": {}},
    {"_embedded": {"leads": None}},
    {"_embedded": {"leads": "not-a-list"}},
])
def test_extract_entities_handles_empty_or_incomplete_embedded(payload):
    assert extract_entities(payload, "leads") == []


def test_get_next_href():
    assert get_next_href({"_links": {"next": {"href": "page-2"}}}) == "page-2"
    assert get_next_href({}) is None
    assert get_next_href({"_links": {}}) is None


def test_response_handler_200():
    assert response_handler(FakeResponse(payload={"ok": True})) == {"ok": True}


def test_response_handler_204():
    with pytest.raises(AmoCrmNoConten):
        response_handler(FakeResponse(status_code=204))


def test_response_handler_429_retry_after():
    with pytest.raises(AmoCrmRepeatError) as exc_info:
        response_handler(FakeResponse(status_code=429, headers={"Retry-After": "7"}))
    assert exc_info.value.retry_after == 7


def test_response_handler_retries_5xx():
    with pytest.raises(AmoCrmRepeatError):
        response_handler(FakeResponse(status_code=503))


def test_response_handler_does_not_retry_4xx():
    with pytest.raises(AmoCrmError):
        response_handler(FakeResponse(status_code=404))


class DummyEntity:
    url = "api/v4/items"
    entity_name = "items"


def test_amocrm_get_follows_pages_without_artificial_delay(monkeypatch):
    pages = [
        FakeResponse(payload={
            "_embedded": {"items": [{"id": 1}, {"id": 2}]},
            "_links": {"next": {"href": "page-2"}},
        }),
        FakeResponse(payload={
            "_embedded": {"items": [{"id": 3}]},
        }),
    ]

    def fake_get(*args, **kwargs):
        return pages.pop(0)

    def fail_sleep(*args, **kwargs):
        raise AssertionError("amocrm_get must not sleep between pages")

    monkeypatch.setattr(amocrm.requests, "get", fake_get)
    monkeypatch.setattr(amocrm.time, "sleep", fail_sleep)

    assert list(amocrm.amocrm_get(DummyEntity, limit=2)) == [
        {"id": 1}, {"id": 2}, {"id": 3},
    ]


def test_amocrm_get_retries_5xx(monkeypatch):
    responses = [
        FakeResponse(status_code=500),
        FakeResponse(payload={"_embedded": {"items": [{"id": 1}]}}),
    ]
    sleeps = []

    monkeypatch.setattr(amocrm.requests, "get", lambda *a, **kw: responses.pop(0))
    monkeypatch.setattr(amocrm.time, "sleep", lambda delay: sleeps.append(delay))

    assert list(amocrm.amocrm_get(DummyEntity, limit=10)) == [{"id": 1}]
    assert sleeps == [2]


def test_amocrm_get_stops_on_empty_embedded(monkeypatch):
    monkeypatch.setattr(
        amocrm.requests, "get",
        lambda *a, **kw: FakeResponse(payload={"_embedded": {}}),
    )

    assert list(amocrm.amocrm_get(DummyEntity)) == []


def test_normalize_custom_fields_from_amocrm_list():
    raw = [
        {"field_id": 1, "field_name": "Логин", "values": [{"value": "buyer"}]},
        {"field_id": 2, "field_name": "Робот", "values": [{"value": True}]},
    ]

    assert normalize_custom_fields(raw) == {
        "Логин": {"id": 1, "value": "buyer"},
        "Робот": {"id": 2, "value": True},
    }
    assert normalize_custom_fields(None) == {}
    assert normalize_custom_fields({"Логин": {"value": "x"}}) == {"Логин": {"value": "x"}}


def test_customer_from_dict_parses_fields_and_embedded():
    customer = Customer.from_dict({
        "id": 10,
        "name": "Buyer",
        "status_id": 5,
        "custom_fields_values": [
            {"field_name": "Логин", "values": [{"value": "buyer"}]},
        ],
        "_embedded": {
            "contacts": [{"id": 100, "name": "Contact"}],
            "companies": [{"id": 200, "name": "Company"}],
        },
    })

    assert customer.id == 10
    assert customer.name == "Buyer"
    assert customer.status_id == 5
    assert customer.get_field("Логин") == "buyer"
    assert customer.contacts == [{"id": 100, "name": "Contact"}]
    assert customer.companies == [{"id": 200, "name": "Company"}]
    assert customer.as_dict()["id"] == 10


def test_customer_from_dict_handles_missing_and_empty_payload():
    customer = Customer.from_dict({})

    assert customer.id is None
    assert customer.get_field("Логин") is None
    assert customer.contacts == []
    assert customer.companies == []
    assert Customer.from_dict(None).name is None


def test_lead_from_dict_parses_embedded_contacts():
    lead = Lead.from_dict({
        "id": 11,
        "name": "Deal",
        "custom_fields_values": [
            {"field_name": "Логин", "values": [{"value": "buyer"}]},
        ],
        "_embedded": {"contacts": [{"id": 100}]},
    })

    assert lead.id == 11
    assert lead.get_field("Логин") == "buyer"
    assert lead.contacts == [{"id": 100}]
    assert lead.companies == []


class ParsedEntity:
    url = "api/v4/items"
    entity_name = "items"

    def __init__(self, payload):
        self.payload = payload

    @classmethod
    def from_dict(cls, payload):
        return cls(payload)


def test_amocrm_get_builds_entities_with_from_dict(monkeypatch):
    payload = {"_embedded": {"items": [{"id": 1}, {"id": 2}]}}
    monkeypatch.setattr(amocrm.requests, "get", lambda *a, **kw: FakeResponse(payload=payload))

    entities = list(amocrm.amocrm_get(ParsedEntity, limit=2))

    assert [entity.payload for entity in entities] == [{"id": 1}, {"id": 2}]
