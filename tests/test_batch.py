import pytest

from batch import chunked, dedupe_rows


def test_chunked_splits_without_losing_items():
    assert list(chunked(range(5), 2)) == [[0, 1], [2, 3], [4]]
    assert list(chunked([], 2)) == []
    assert list(chunked(range(4), 10)) == [[0, 1, 2, 3]]


def test_chunked_rejects_non_positive_size():
    with pytest.raises(ValueError):
        list(chunked([1], 0))


def test_dedupe_rows_keeps_last_value_and_merges_data():
    rows = [
        {"crm_id": 1, "name": "Old", "data": {"a": 1}},
        {"crm_id": 1, "name": "New", "data": {"b": 2}},
        {"crm_id": 2, "name": "Other", "data": {}},
    ]

    result = dedupe_rows(rows, ("crm_id",))

    assert result == [
        {"crm_id": 1, "name": "New", "data": {"a": 1, "b": 2}},
        {"crm_id": 2, "name": "Other", "data": {}},
    ]


def test_dedupe_rows_never_collapses_null_keys():
    rows = [
        {"crm_id": None, "name": "first"},
        {"crm_id": None, "name": "second"},
    ]

    assert dedupe_rows(rows, ("crm_id",)) == rows


def test_dedupe_rows_uses_composite_key():
    rows = [
        {"abstract_customer_id": 1, "crm_id": 5, "name": "a"},
        {"abstract_customer_id": 1, "crm_id": 5, "name": "b"},
        {"abstract_customer_id": 2, "crm_id": 5, "name": "c"},
    ]

    result = dedupe_rows(rows, ("abstract_customer_id", "crm_id"))

    assert [(row["abstract_customer_id"], row["crm_id"], row["name"]) for row in result] == [
        (1, 5, "b"),
        (2, 5, "c"),
    ]
