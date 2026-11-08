import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import delete, func, insert, or_, select, text

from abstract_customer import (
    CUSTOMER_UPDATE_COLUMNS,
    LEAD_UPDATE_COLUMNS,
    NESTED_UPDATE_COLUMNS,
    build_merge_map,
    get_company_json,
    get_contact_json,
    get_customer_json,
    get_customer_login,
    get_lead_json,
    get_lead_login,
    load_customer_id_map,
    load_lead_id_map,
    load_login_map,
    resolve_customer_abstract_id,
    resolve_lead_abstract_id,
    should_skip_customer,
    should_skip_lead,
)
from amocrm import COMPANIES, CONTACTS, Customer, Lead, amocrm_get
from batch import chunked, upsert_rows
from models import (
    AbstractCustomer,
    AmoCompany,
    AmoContact,
    AmoCustomer,
    AmoLead,
    db,
)

logger = logging.getLogger(__name__)

CUSTOMER_BATCH_SIZE = 500
LEAD_BATCH_SIZE = 500
MERGE_BATCH_SIZE = 500

ENTITY_MODELS = (AmoCustomer, AmoLead, AmoContact, AmoCompany)

ATTRIBUTE_MODELS = {
    "amo_customers": AmoCustomer,
    "amo_leads": AmoLead,
    "amo_contacts": AmoContact,
    "amo_companies": AmoCompany,
}


def _embedded_id(entity: Any) -> Optional[int]:
    if isinstance(entity, dict):
        return entity.get('id')
    return getattr(entity, 'id', None)


def _embedded_name(entity: Any) -> Optional[str]:
    if isinstance(entity, dict):
        return entity.get('name')
    return getattr(entity, 'name', None)


def _dedupe_by_crm_id(entities: Iterable[Any]) -> List[Any]:
    """Оставляет последнее вхождение каждого CRM id внутри пачки."""
    result: List[Any] = []
    positions: Dict[Any, int] = {}
    for entity in entities:
        crm_id = getattr(entity, 'id', None)
        if crm_id is None:
            result.append(entity)
        elif crm_id in positions:
            result[positions[crm_id]] = entity
        else:
            positions[crm_id] = len(result)
            result.append(entity)
    return result


def _create_abstract_customers(session, count: int) -> List[int]:
    """Создаёт пустые агрегаты пачкой и возвращает их id."""
    if count <= 0:
        return []

    if session.get_bind().dialect.name == 'postgresql':
        sequence_name = session.execute(
            text("SELECT pg_get_serial_sequence('abstract_customer', 'id')")
        ).scalar()
        if not sequence_name:
            sequence_name = 'abstract_customer_id_seq'
        ids = list(session.execute(
            text("SELECT nextval(CAST(:sequence AS regclass)) "
                 "FROM generate_series(1, :count)"),
            {'sequence': sequence_name, 'count': count},
        ).scalars().all())
        session.execute(
            insert(AbstractCustomer),
            [{'id': abstract_id} for abstract_id in ids],
        )
        return ids

    # Запасной путь для тестовых БД без PostgreSQL.
    objects = [AbstractCustomer() for _ in range(count)]
    session.add_all(objects)
    session.flush()
    return [obj.id for obj in objects]


def _nested_rows(embedded_entities: Iterable[Any], abstract_customer_id: int,
                 run_id: int, serializer) -> List[Dict[str, Any]]:
    if not isinstance(embedded_entities, (list, tuple)):
        return []

    rows = []
    for entity in embedded_entities:
        rows.append({
            'abstract_customer_id': abstract_customer_id,
            'crm_id': _embedded_id(entity),
            'login': None,
            'name': _embedded_name(entity),
            'data': serializer(entity),
            'sync_run_id': run_id,
        })
    return rows


def _process_customer_batch(session, batch: List[Customer], is_full: bool, run_id: int) -> None:
    customers = _dedupe_by_crm_id(
        customer for customer in batch if not should_skip_customer(customer, is_full)
    )
    if not customers:
        return

    logins = {get_customer_login(customer) for customer in customers}
    logins.discard(None)
    customer_ids = {getattr(customer, 'id', None) for customer in customers}

    by_customer_id = load_customer_id_map(customer_ids)
    by_lead_login = load_login_map(AmoLead, logins)

    prepared = []
    new_count = 0
    for customer in customers:
        login = get_customer_login(customer)
        target_id = resolve_customer_abstract_id(
            getattr(customer, 'id', None), login, by_customer_id, by_lead_login,
        )
        if target_id is None:
            new_count += 1
        prepared.append((customer, login, target_id))

    new_ids = iter(_create_abstract_customers(session, new_count))

    customer_rows = []
    contact_rows = []
    company_rows = []
    for customer, login, target_id in prepared:
        if target_id is None:
            target_id = next(new_ids)

        customer_rows.append({
            'abstract_customer_id': target_id,
            'crm_id': getattr(customer, 'id', None),
            'login': login,
            'name': getattr(customer, 'name', None),
            'data': get_customer_json(customer),
            'sync_run_id': run_id,
        })
        contact_rows.extend(_nested_rows(
            getattr(customer, 'contacts', None) or [],
            target_id, run_id, get_contact_json,
        ))
        company_rows.extend(_nested_rows(
            getattr(customer, 'companies', None) or [],
            target_id, run_id, get_company_json,
        ))

    upsert_rows(
        session, AmoCustomer, customer_rows,
        conflict_columns=('crm_id',),
        update_columns=CUSTOMER_UPDATE_COLUMNS,
    )
    upsert_rows(
        session, AmoContact, contact_rows,
        conflict_columns=('abstract_customer_id', 'crm_id'),
        update_columns=NESTED_UPDATE_COLUMNS,
    )
    upsert_rows(
        session, AmoCompany, company_rows,
        conflict_columns=('abstract_customer_id', 'crm_id'),
        update_columns=NESTED_UPDATE_COLUMNS,
    )


def _process_lead_batch(session, batch: List[Lead], is_full: bool, run_id: int) -> List[int]:
    leads = _dedupe_by_crm_id(
        lead for lead in batch if not should_skip_lead(lead, is_full)
    )
    if not leads:
        return []

    logins = {get_lead_login(lead) for lead in leads}
    logins.discard(None)
    lead_ids = {getattr(lead, 'id', None) for lead in leads}

    by_lead_id = load_lead_id_map(lead_ids)
    by_customer_login = load_login_map(AmoCustomer, logins)

    decisions = []
    merge_pairs = []
    for lead in leads:
        login = get_lead_login(lead)
        target_id, merge_source_id = resolve_lead_abstract_id(
            getattr(lead, 'id', None), login, by_lead_id, by_customer_login,
        )
        if target_id is not None and merge_source_id is not None:
            merge_pairs.append((merge_source_id, target_id))
        decisions.append((lead, login, target_id))

    # Цепочки слияний внутри пачки (C -> B -> A) сначала разворачиваются.
    merge_map = build_merge_map(merge_pairs)
    if merge_map:
        _merge_abstract_customers(session, merge_map, run_id)

    new_count = sum(1 for _, _, target_id in decisions if target_id is None)
    new_ids = iter(_create_abstract_customers(session, new_count))

    lead_rows = []
    contact_rows = []
    target_ids = []
    for lead, login, target_id in decisions:
        if target_id is None:
            target_id = next(new_ids)
        else:
            target_id = merge_map.get(target_id, target_id)
        target_ids.append(target_id)

        lead_rows.append({
            'abstract_customer_id': target_id,
            'crm_id': getattr(lead, 'id', None),
            'login': login,
            'name': getattr(lead, 'name', None),
            'data': get_lead_json(lead),
            'sync_run_id': run_id,
        })
        contact_rows.extend(_nested_rows(
            getattr(lead, 'contacts', None) or [],
            target_id, run_id, get_contact_json,
        ))

    upsert_rows(
        session, AmoLead, lead_rows,
        conflict_columns=('crm_id',),
        update_columns=LEAD_UPDATE_COLUMNS,
    )
    upsert_rows(
        session, AmoContact, contact_rows,
        conflict_columns=('abstract_customer_id', 'crm_id'),
        update_columns=NESTED_UPDATE_COLUMNS,
    )
    return target_ids


def _delete_nested_merge_duplicates(session, table_name: str, run_id: int) -> None:
    """Оставляет по одной строке на (целевой агрегат, CRM id) после слияния.

    Сначала побеждает строка текущего прогона, затем строка источника.
    """
    session.execute(text(f"""
        WITH candidates AS (
            SELECT c.id,
                   COALESCE(m.target_id, c.abstract_customer_id) AS target_id,
                   c.crm_id,
                   CASE WHEN c.sync_run_id = :run_id THEN 1 ELSE 0 END AS is_fresh,
                   CASE WHEN m.source_id IS NOT NULL THEN 1 ELSE 0 END AS is_source,
                   c.updated_at
            FROM {table_name} c
            LEFT JOIN _merge_map m ON c.abstract_customer_id = m.source_id
            WHERE c.crm_id IS NOT NULL
              AND (
                  c.abstract_customer_id IN (SELECT source_id FROM _merge_map)
                  OR c.abstract_customer_id IN (SELECT target_id FROM _merge_map)
              )
        ),
        ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY target_id, crm_id
                       ORDER BY is_fresh DESC, is_source DESC,
                                updated_at DESC NULLS LAST, id DESC
                   ) AS rn
            FROM candidates
        )
        DELETE FROM {table_name} c
        USING ranked r
        WHERE c.id = r.id AND r.rn > 1
    """), {'run_id': run_id})


def _merge_chunk(session, pairs: List[Tuple[int, int]], run_id: int) -> None:
    session.execute(text("DROP TABLE IF EXISTS _merge_map"))
    session.execute(text(
        "CREATE TEMPORARY TABLE _merge_map ("
        "source_id BIGINT PRIMARY KEY, target_id BIGINT NOT NULL)"
    ))
    session.execute(
        text("INSERT INTO _merge_map (source_id, target_id) "
             "VALUES (:source_id, :target_id)"),
        [{'source_id': source, 'target_id': target} for source, target in pairs],
    )

    for table_name in ('amo_customers', 'amo_leads'):
        session.execute(text(f"""
            UPDATE {table_name} AS t
            SET login = s.login,
                name = s.name,
                data = s.data,
                sync_run_id = :run_id,
                updated_at = now()
            FROM {table_name} AS s
            JOIN _merge_map m ON s.abstract_customer_id = m.source_id
            WHERE t.abstract_customer_id = m.target_id
              AND t.crm_id = s.crm_id
              AND s.crm_id IS NOT NULL
              AND s.sync_run_id = :run_id
        """), {'run_id': run_id})
        session.execute(text(f"""
            DELETE FROM {table_name} AS s
            USING _merge_map m
            WHERE s.abstract_customer_id = m.source_id
              AND s.crm_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM {table_name} AS t
                  WHERE t.abstract_customer_id = m.target_id
                    AND t.crm_id = s.crm_id
              )
        """))
        session.execute(text(f"""
            UPDATE {table_name} AS s
            SET abstract_customer_id = m.target_id,
                updated_at = now()
            FROM _merge_map m
            WHERE s.abstract_customer_id = m.source_id
        """))

    for table_name in ('amo_contacts', 'amo_companies'):
        _delete_nested_merge_duplicates(session, table_name, run_id)
        session.execute(text(f"""
            UPDATE {table_name} AS c
            SET abstract_customer_id = m.target_id,
                updated_at = now()
            FROM _merge_map m
            WHERE c.abstract_customer_id = m.source_id
        """))

    session.execute(text("""
        UPDATE send_methods AS sm
        SET abstract_customer_id = m.target_id,
            updated_at = now()
        FROM _merge_map m
        WHERE sm.abstract_customer_id = m.source_id
    """))

    session.execute(text("""
        DELETE FROM abstract_customer a
        USING _merge_map m
        WHERE a.id = m.source_id
    """))
    session.execute(text("DROP TABLE IF EXISTS _merge_map"))


def _merge_abstract_customers(session, merge_map: Dict[int, int], run_id: int) -> None:
    if not merge_map:
        return
    for pairs in chunked(list(merge_map.items()), MERGE_BATCH_SIZE):
        _merge_chunk(session, pairs, run_id)


def _cleanup(session, run_id: int) -> None:
    """Удаляет сущности, которых не было в успешно завершённой полной выгрузке."""
    logger.info("Чистка покупателей и вложенных сущностей")

    # Сущности с «удалить» в имени убираем, даже если CRM их вернула.
    for model in ENTITY_MODELS:
        session.execute(
            delete(model).where(func.lower(model.name).like('%удалить%'))
        )

    # Полный проход помечает каждую увиденную строку sync_run_id.
    # Остальное устарело: удаляем одним запросом, не читая JSONB в память.
    for model in ENTITY_MODELS:
        session.execute(
            delete(model).where(
                or_(model.sync_run_id.is_(None), model.sync_run_id != run_id)
            )
        )

    has_customer = select(AmoCustomer.id).where(
        AmoCustomer.abstract_customer_id == AbstractCustomer.id
    ).exists()
    has_lead = select(AmoLead.id).where(
        AmoLead.abstract_customer_id == AbstractCustomer.id
    ).exists()
    session.execute(
        delete(AbstractCustomer).where(~has_customer, ~has_lead)
    )
    session.commit()
    logger.info("Чистка завершена")


def collect_leads_customers(is_full=True):
    """Синхронизирует покупателей и сделки AmoCRM с PostgreSQL.

    Чистка выполняется только после успешного полного прохода.
    """
    session = db.session
    run_id = time.time_ns()

    try:
        logger.info("Сбор покупателей %s", f"{is_full=}")
        customers = amocrm_get(Customer, _with=f"{COMPANIES},{CONTACTS}")
        for batch in chunked(customers, CUSTOMER_BATCH_SIZE):
            _process_customer_batch(session, batch, is_full, run_id)
            session.commit()

        logger.info("Сбор сделок %s", f"{is_full=}")
        leads = amocrm_get(Lead, _with=f"{CONTACTS}")
        for batch in chunked(leads, LEAD_BATCH_SIZE):
            _process_lead_batch(session, batch, is_full, run_id)
            session.commit()
    except Exception:
        session.rollback()
        logger.exception("Сбор прерван, чистка не выполняется")
        raise

    if is_full:
        _cleanup(session, run_id)


def lead_action(lead: Lead):
    """Обрабатывает одну сделку для совместимости; ночной прогон работает батчами."""
    run_id = time.time_ns()
    target_ids = _process_lead_batch(db.session, [lead], True, run_id)
    db.session.commit()
    if not target_ids:
        return None
    return db.session.get(AbstractCustomer, target_ids[0])


def filter_merge_abstract_customer(abstract_customer: AbstractCustomer, attr: str,
                                   check_ids: List[int]) -> None:
    """Устаревшая фильтрация одного агрегата, оставлена для совместимости."""
    model = ATTRIBUTE_MODELS.get(attr)
    if model is None:
        return

    check_ids = set(check_ids or [])
    rows = db.session.scalars(
        select(model).where(model.abstract_customer_id == abstract_customer.id)
    ).all()
    for row in rows:
        name = row.name or ''
        if 'удалить' in name.lower() or (
                row.crm_id is not None and row.crm_id not in check_ids):
            db.session.delete(row)
    db.session.flush()


def filter_abc_customer(abc_customer: AbstractCustomer, ids_map: Dict) -> None:
    """Устаревшая чистка одного агрегата, оставлена для совместимости."""
    entity_ids = ids_map.get(abc_customer.id, {})
    filter_merge_abstract_customer(
        abc_customer, 'amo_leads', entity_ids.get('leads', []),
    )
    filter_merge_abstract_customer(
        abc_customer, 'amo_customers', entity_ids.get('customers', []),
    )
    filter_merge_abstract_customer(
        abc_customer, 'amo_contacts', entity_ids.get('contacts', []),
    )
    filter_merge_abstract_customer(
        abc_customer, 'amo_companies', entity_ids.get('companies', []),
    )
    if not abc_customer.customers and not abc_customer.leads:
        db.session.delete(abc_customer)
    db.session.flush()
