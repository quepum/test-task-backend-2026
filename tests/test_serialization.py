from abstract_customer import (
    dict_compare_merge,
    get_company_json,
    get_contact_json,
    get_customer_json,
    get_lead_json,
    merge_entity_lists,
)


class FakeCustomer:
    def __init__(self, id=1, name="Customer", fields=None):
        self.id = id
        self.name = name
        self.custom_fields_values = fields

    def as_dict(self):
        return {"id": self.id, "name": self.name}


class FakeLead:
    def __init__(self, id=1, name="Lead", fields=None):
        self.id = id
        self.name = name
        self.custom_fields_values = fields

    def as_dict(self):
        return {"id": self.id, "name": self.name}


def test_customer_json_serialization_handles_missing_fields():
    customer = FakeCustomer(
        id=7,
        name="Buyer",
        fields={
            "Логин": {"value": "buyer"},
            "Робот": {"value": True},
        },
    )

    payload = get_customer_json(customer)

    assert payload["general"]["id"] == 7
    assert payload["general"]["login"] == "buyer"
    assert payload["general"]["is_robot"] is True
    assert payload["general"]["billing_type"] is None
    assert payload["api_value"] == {"id": 7, "name": "Buyer"}


def test_customer_json_serialization_handles_none_fields():
    customer = FakeCustomer(id=None, name=None, fields=None)

    payload = get_customer_json(customer)

    assert payload["general"]["id"] is None
    assert payload["general"]["login"] is None
    assert payload["general"]["is_nds"] is False


def test_lead_json_serialization():
    lead = FakeLead(id=8, name="Deal", fields={"Логин": {"value": "buyer"}})

    payload = get_lead_json(lead)

    assert payload["general"] == {"id": 8, "login": "buyer", "name": "Deal"}
    assert payload["api_value"] == {"id": 8, "name": "Deal"}


def test_contact_and_company_json_serialization():
    assert get_contact_json({"id": 1, "name": "Phone", "phone": "+1"})["general"] == {
        "id": 1, "phone": "+1", "name": "Phone",
    }
    assert get_company_json({"id": 2, "name": "Company", "inn": "123"})["general"] == {
        "id": 2, "inn": "123", "name": "Company",
    }


def test_dict_compare_merge_keeps_fields_from_both_records():
    first = [{
        "general": {"id": 1, "login": "buyer", "name": "Old"},
        "api_value": {"left": 1},
    }]
    second = [{
        "general": {"id": 1, "name": "New"},
        "api_value": {"right": 2},
    }]

    merged = dict_compare_merge(first, second)

    assert len(merged) == 1
    assert merged[0]["general"] == {"id": 1, "login": "buyer", "name": "New"}
    assert merged[0]["api_value"] == {"left": 1, "right": 2}


def test_dict_compare_merge_does_not_collapse_entities_without_id():
    merged = dict_compare_merge(
        [{"general": {"id": None, "name": "first"}}],
        [{"general": {"id": None, "name": "second"}}],
    )

    assert len(merged) == 2


def test_merge_entity_lists_accepts_multiple_lists():
    merged = merge_entity_lists(
        [{"general": {"id": 1, "name": "A"}}],
        [{"general": {"id": 2, "name": "B"}}],
        [{"general": {"id": 1, "login": "a"}}],
    )

    assert len(merged) == 2
    assert merged[0]["general"] == {"id": 1, "name": "A", "login": "a"}
    assert merged[1]["general"]["id"] == 2
