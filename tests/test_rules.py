from abstract_customer import (
    LEAD_PARTIAL_SKIP_STATUS_ID,
    CUSTOMER_PARTIAL_SKIP_STATUS_ID,
    build_merge_map,
    resolve_customer_abstract_id,
    resolve_lead_abstract_id,
    should_skip_customer,
    should_skip_lead,
    unique_abstract_id,
)


class FakeCustomer:
    def __init__(self, id=1, name="Customer", fields=None, status_id=None,
                 contacts=None, companies=None):
        self.id = id
        self.name = name
        self.custom_fields_values = fields or {}
        self.status_id = status_id
        self.contacts = contacts or []
        self.companies = companies or []

    def as_dict(self):
        return {"id": self.id, "name": self.name}


class FakeLead:
    def __init__(self, id=1, name="Lead", fields=None, status_id=None):
        self.id = id
        self.name = name
        self.custom_fields_values = fields or {}
        self.status_id = status_id

    def as_dict(self):
        return {"id": self.id, "name": self.name}


def login_field(value):
    return {"Логин": {"value": value}}


def test_customer_without_login_is_skipped():
    assert should_skip_customer(FakeCustomer(fields={}), True) is True
    assert should_skip_customer(FakeCustomer(fields={"Логин": {"value": ""}}), True) is True
    assert should_skip_customer(FakeCustomer(fields=login_field("buyer")), True) is False


def test_partial_customer_status_is_filtered():
    customer = FakeCustomer(fields=login_field("buyer"), status_id=CUSTOMER_PARTIAL_SKIP_STATUS_ID)
    assert should_skip_customer(customer, is_full=False) is True
    assert should_skip_customer(customer, is_full=True) is False


def test_partial_lead_status_is_filtered():
    lead = FakeLead(status_id=LEAD_PARTIAL_SKIP_STATUS_ID)
    assert should_skip_lead(lead, is_full=False) is True
    assert should_skip_lead(lead, is_full=True) is False


def test_unique_abstract_id_requires_one_value():
    assert unique_abstract_id({10}) == 10
    assert unique_abstract_id({10, 11}) is None
    assert unique_abstract_id(set()) is None


def test_customer_resolution_prefers_crm_id():
    target = resolve_customer_abstract_id(
        1, "buyer", customer_id_map={1: 10}, lead_login_map={"buyer": {20}},
    )
    assert target == 10


def test_customer_resolution_falls_back_to_lead_login():
    target = resolve_customer_abstract_id(
        1, "buyer", customer_id_map={}, lead_login_map={"buyer": {20}},
    )
    assert target == 20


def test_customer_resolution_ignores_ambiguous_lead_login():
    target = resolve_customer_abstract_id(
        1, "buyer", customer_id_map={}, lead_login_map={"buyer": {20, 21}},
    )
    assert target is None


def test_customer_resolution_does_not_look_at_customer_logins():
    # Логины покупателей намеренно не участвуют в правиле 2.
    target = resolve_customer_abstract_id(
        1, "buyer", customer_id_map={}, lead_login_map={},
    )
    assert target is None


def test_lead_resolution_marks_login_match_for_merge():
    target, merge_source = resolve_lead_abstract_id(
        1, "buyer", lead_id_map={1: 10}, customer_login_map={"buyer": {20}},
    )
    assert target == 10
    assert merge_source == 20


def test_lead_resolution_by_crm_id_only():
    assert resolve_lead_abstract_id(
        1, "buyer", lead_id_map={1: 10}, customer_login_map={},
    ) == (10, None)


def test_lead_resolution_by_login_only():
    assert resolve_lead_abstract_id(
        1, "buyer", lead_id_map={}, customer_login_map={"buyer": {20}},
    ) == (20, None)


def test_lead_resolution_ignores_ambiguous_login():
    assert resolve_lead_abstract_id(
        1, "buyer", lead_id_map={}, customer_login_map={"buyer": {20, 21}},
    ) == (None, None)


def test_lead_resolution_creates_when_nothing_found():
    assert resolve_lead_abstract_id(
        1, "buyer", lead_id_map={}, customer_login_map={},
    ) == (None, None)


def test_lead_resolution_without_login_still_uses_crm_id():
    assert resolve_lead_abstract_id(
        1, None, lead_id_map={1: 10}, customer_login_map={},
    ) == (10, None)


def test_build_merge_map_keeps_lead_target_and_marks_login_match_as_source():
    assert build_merge_map([(20, 10)]) == {20: 10}


def test_build_merge_map_flattens_chains():
    # B -> C and C -> D must not move rows onto C and delete C afterwards.
    assert build_merge_map([(2, 3), (3, 4)]) == {2: 4, 3: 4}


def test_build_merge_map_ignores_self_merges_and_missing_ids():
    assert build_merge_map([(1, 1), (None, 2), (3, None)]) == {}


def test_build_merge_map_resolves_shared_targets():
    assert build_merge_map([(1, 3), (2, 3)]) == {1: 3, 2: 3}
