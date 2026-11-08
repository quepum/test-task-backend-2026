"""Батч-хелперы для цикла синхронизации."""

from typing import Any, Dict, Iterable, Iterator, List, Sequence, Tuple

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert


def chunked(iterable: Iterable[Any], size: int) -> Iterator[List[Any]]:
    """Отдаёт элементы порциями не больше size, не загружая весь поток в память."""
    if size <= 0:
        raise ValueError("size must be positive")

    batch: List[Any] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def dedupe_rows(rows: Sequence[Dict[str, Any]], key_fields: Sequence[str]) -> List[Dict[str, Any]]:
    """Схлопывает дубли конфликтного ключа внутри одного INSERT.

    Строки с NULL в ключе не схлопываются: NULL не конфликтует сам с собой.
    """
    result: List[Dict[str, Any]] = []
    positions: Dict[Tuple[Any, ...], int] = {}

    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        if any(value is None for value in key):
            result.append(dict(row))
            continue

        if key in positions:
            index = positions[key]
            previous = result[index]
            merged = dict(previous)
            for name, value in row.items():
                if isinstance(value, dict) and isinstance(merged.get(name), dict):
                    merged[name] = {**merged[name], **value}
                else:
                    merged[name] = value
            result[index] = merged
        else:
            positions[key] = len(result)
            result.append(dict(row))

    return result


def upsert_rows(session, model, rows: Sequence[Dict[str, Any]],
                conflict_columns: Sequence[str],
                update_columns: Sequence[str]) -> int:
    """Батчевый INSERT ... ON CONFLICT DO UPDATE для PostgreSQL.

    Возвращает число строк после дедупликации внутри пачки.
    """
    if not rows:
        return 0

    rows = dedupe_rows(rows, conflict_columns)
    statement = pg_insert(model).values(rows)
    update_values = {name: getattr(statement.excluded, name) for name in update_columns}
    update_values.setdefault("updated_at", func.now())
    statement = statement.on_conflict_do_update(
        index_elements=list(conflict_columns),
        set_=update_values,
    )
    session.execute(statement)
    return len(rows)
