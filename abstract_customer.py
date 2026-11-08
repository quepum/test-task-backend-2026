import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select

from amocrm import Customer, Lead
from batch import upsert_rows
from models import AbstractCustomer, AmoCustomer, AmoLead, db

logger = logging.getLogger(__name__)

CUSTOMER_PARTIAL_SKIP_STATUS_ID = 111349
LEAD_PARTIAL_SKIP_STATUS_ID = 143

CUSTOMER_UPDATE_COLUMNS = (
    "abstract_customer_id", "login", "name", "data", "sync_run_id",
)
LEAD_UPDATE_COLUMNS = (
    "abstract_customer_id", "login", "name", "data", "sync_run_id",
)
NESTED_UPDATE_COLUMNS = (
    "abstract_customer_id", "login", "name", "data", "sync_run_id",
)


def _custom_field(fields: Optional[Dict[str, Any]], name: str) -> Any:
    if not fields:
        return None
    field = fields.get(name)
    if isinstance(field, dict):
        return field.get('value')
    return field


def get_customer_login(customer: Customer) -> Optional[str]:
    """Возвращает логин покупателя или None."""
    return _custom_field(getattr(customer, 'custom_fields_values', None), 'Логин')


def get_lead_login(lead: Lead) -> Optional[str]:
    """Возвращает логин сделки или None."""
    return _custom_field(getattr(lead, 'custom_fields_values', None), 'Логин')


def _entity_as_dict(entity: Any) -> Dict[str, Any]:
    as_dict = getattr(entity, 'as_dict', None)
    if callable(as_dict):
        try:
            return as_dict()
        except Exception:  # pragma: no cover - defensive fallback
            logger.exception("Не удалось сериализовать сущность %r", entity)
    attributes = getattr(entity, '__dict__', None)
    if not isinstance(attributes, dict):
        return {}
    return {
        key: value for key, value in attributes.items()
        if not key.startswith('_')
    }


def get_customer_json(customer: Customer) -> dict:
    """Собирает JSON покупателя в формате general/api_value."""
    fields = getattr(customer, 'custom_fields_values', None)
    return {
        'general': {
            'id': getattr(customer, 'id', None),
            'login': _custom_field(fields, 'Логин'),
            'billing_type': _custom_field(fields, 'Вид оплаты'),
            'is_robot': bool(_custom_field(fields, 'Робот')),
            'is_nds': bool(_custom_field(fields, 'Оплата с НДС')),
            'system': _custom_field(fields, 'Система'),
            'host': _custom_field(fields, 'Хост'),
            'name': getattr(customer, 'name', None),
        },
        'api_value': _entity_as_dict(customer),
    }


def get_lead_json(lead: Lead) -> dict:
    """Собирает JSON сделки в формате general/api_value."""
    fields = getattr(lead, 'custom_fields_values', None)
    return {
        'general': {
            'id': getattr(lead, 'id', None),
            'login': _custom_field(fields, 'Логин'),
            'name': getattr(lead, 'name', None),
        },
        'api_value': _entity_as_dict(lead),
    }


def _embedded_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def get_contact_json(contact: Any) -> dict:
    """Собирает JSON контакта в формате general/api_value."""
    return {
        'general': {
            'id': _embedded_value(contact, 'id'),
            'phone': _embedded_value(contact, 'phone'),
            'name': _embedded_value(contact, 'name'),
        },
        'api_value': dict(contact) if isinstance(contact, dict) else _entity_as_dict(contact),
    }


def get_company_json(company: Any) -> dict:
    """Собирает JSON компании в формате general/api_value."""
    return {
        'general': {
            'id': _embedded_value(company, 'id'),
            'inn': _embedded_value(company, 'inn'),
            'name': _embedded_value(company, 'name'),
        },
        'api_value': dict(company) if isinstance(company, dict) else _entity_as_dict(company),
    }


def _deep_merge(left: Any, right: Any) -> Any:
    if isinstance(left, dict) and isinstance(right, dict):
        result = dict(left)
        for key, value in right.items():
            if key in result:
                result[key] = _deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    return right


def _entity_id(item: Any) -> Any:
    if not isinstance(item, dict):
        return None
    general = item.get('general')
    if not isinstance(general, dict):
        return None
    return general.get('id')


def merge_entity_lists(*entity_lists: Iterable[dict]) -> List[dict]:
    """Объединяет списки сущностей по general.id, не теряя поля."""
    result: List[dict] = []
    positions: Dict[Any, int] = {}

    for entities in entity_lists:
        for entity in entities or []:
            entity_id = _entity_id(entity)
            if entity_id is None or entity_id not in positions:
                if entity_id is not None:
                    positions[entity_id] = len(result)
                result.append(dict(entity))
                continue

            index = positions[entity_id]
            result[index] = _deep_merge(result[index], entity)

    return result


def dict_compare_merge(l_dict1: Iterable[dict], l_dict2: Iterable[dict]) -> List[dict]:
    """Совместимый алиас merge_entity_lists."""
    return merge_entity_lists(l_dict1, l_dict2)


def unique_abstract_id(ids: Optional[Iterable[Any]]) -> Optional[int]:
    """Возвращает id, только если найдено ровно одно значение."""
    if ids is None:
        return None
    if isinstance(ids, int):
        return ids
    unique_ids = {value for value in ids if value is not None}
    if len(unique_ids) == 1:
        return next(iter(unique_ids))
    return None


def build_merge_map(pairs: Iterable[Tuple[int, int]]) -> Dict[int, int]:
    """Схлопывает пары (источник, цель) в источник → итоговая цель."""
    parent: Dict[int, int] = {}

    def find(value: int) -> int:
        root = value
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(value, value) != value:
            next_value = parent[value]
            parent[value] = root
            value = next_value
        return root

    for source, target in pairs:
        if source is None or target is None or source == target:
            continue
        source_root = find(source)
        target_root = find(target)
        if source_root != target_root:
            parent[source_root] = target_root

    result: Dict[int, int] = {}
    for source in list(parent):
        target = find(source)
        if target != source:
            result[source] = target
    return result


def resolve_customer_abstract_id(crm_customer_id: Optional[int],
                                 login: Optional[str],
                                 customer_id_map: Dict[int, int],
                                 lead_login_map: Dict[str, Set[int]]) -> Optional[int]:
    """Ищет покупателя по CRM id, затем по логину среди уже сохранённых сделок.

    Неоднозначный логин не используется.
    """
    if crm_customer_id is not None:
        by_id = customer_id_map.get(crm_customer_id)
        if by_id is not None:
            return by_id

    if not login:
        return None
    return unique_abstract_id(lead_login_map.get(login))


def resolve_lead_abstract_id(crm_lead_id: Optional[int],
                             login: Optional[str],
                             lead_id_map: Dict[int, int],
                             customer_login_map: Dict[str, Set[int]]):
    """Ищет запись по CRM id сделки, затем по логину среди покупателей.

    Возвращает (цель, источник слияния): цель — запись по CRM id сделки,
    источник — запись по логину, которую нужно слить и удалить.
    """
    by_lead = lead_id_map.get(crm_lead_id) if crm_lead_id is not None else None
    by_login = unique_abstract_id(customer_login_map.get(login)) if login else None

    if by_lead is not None and by_login is not None and by_lead != by_login:
        return by_lead, by_login
    if by_lead is not None:
        return by_lead, None
    if by_login is not None:
        return by_login, None
    return None, None


def should_skip_customer(customer: Customer, is_full: bool) -> bool:
    """Пропускает покупателя без логина и статус из частичного прогона."""
    if not is_full and getattr(customer, 'status_id', None) == CUSTOMER_PARTIAL_SKIP_STATUS_ID:
        return True
    return not bool(get_customer_login(customer))


def should_skip_lead(lead: Lead, is_full: bool) -> bool:
    """Пропускает сделку со статусом из частичного прогона."""
    return not is_full and getattr(lead, 'status_id', None) == LEAD_PARTIAL_SKIP_STATUS_ID


def _load_id_map(model, crm_ids: Iterable[Optional[int]]) -> Dict[int, int]:
    crm_ids = {crm_id for crm_id in crm_ids if crm_id is not None}
    if not crm_ids:
        return {}

    rows = db.session.execute(
        select(model.crm_id, model.abstract_customer_id).where(model.crm_id.in_(crm_ids))
    ).all()

    result: Dict[int, int] = {}
    for crm_id, abstract_id in rows:
        if crm_id in result and result[crm_id] != abstract_id:
            logger.warning("CRM id %s belongs to several abstract customers", crm_id)
            continue
        result[crm_id] = abstract_id
    return result


def load_customer_id_map(crm_ids: Iterable[Optional[int]]) -> Dict[int, int]:
    """Загружает карту CRM id → abstract_customer.id для покупателей."""
    return _load_id_map(AmoCustomer, crm_ids)


def load_lead_id_map(crm_ids: Iterable[Optional[int]]) -> Dict[int, int]:
    """Загружает карту CRM id → abstract_customer.id для сделок."""
    return _load_id_map(AmoLead, crm_ids)


def load_login_map(model, logins: Iterable[Optional[str]]) -> Dict[str, Set[int]]:
    """Загружает карту логин → множество abstract_customer.id."""
    logins = {login for login in logins if login}
    if not logins:
        return {}

    rows = db.session.execute(
        select(model.login, model.abstract_customer_id)
        .where(model.login.in_(logins))
        .distinct()
    ).all()

    result: Dict[str, Set[int]] = defaultdict(set)
    for login, abstract_id in rows:
        result[login].add(abstract_id)
    return result


def get_abccustomer_by_lead_login(lead_login: str) -> Optional[AbstractCustomer]:
    """Ищет агрегат по логину сделки, если он однозначен."""
    if not lead_login:
        return None

    abstract_ids = set(db.session.execute(
        select(AmoLead.abstract_customer_id).where(AmoLead.login == lead_login).distinct()
    ).scalars().all())

    abstract_id = unique_abstract_id(abstract_ids)
    if abstract_ids and abstract_id is None:
        logger.warning("Lead %s has more than one abccustomer", lead_login)
        return None
    if abstract_id is None:
        return None
    return db.session.get(AbstractCustomer, abstract_id)


def get_abccustomer_by_amocustomer_login(customer_login: str) -> Optional[AbstractCustomer]:
    """Ищет агрегат по логину покупателя, если он однозначен."""
    if not customer_login:
        return None

    abstract_ids = set(db.session.execute(
        select(AmoCustomer.abstract_customer_id)
        .where(AmoCustomer.login == customer_login)
        .distinct()
    ).scalars().all())

    abstract_id = unique_abstract_id(abstract_ids)
    if abstract_ids and abstract_id is None:
        logger.warning("Customer %s has more than one abccustomer", customer_login)
        return None
    if abstract_id is None:
        return None
    return db.session.get(AbstractCustomer, abstract_id)


def get_abccustomer_by_amocustomer_id(crm_customer_id: int) -> Optional[AbstractCustomer]:
    """Ищет агрегат по CRM id покупателя."""
    abstract_id = db.session.execute(
        select(AmoCustomer.abstract_customer_id).where(AmoCustomer.crm_id == crm_customer_id)
    ).scalar_one_or_none()
    if abstract_id is None:
        return None
    return db.session.get(AbstractCustomer, abstract_id)


def get_abccustomer_by_lead_id(crm_lead_id: int) -> Optional[AbstractCustomer]:
    """Ищет агрегат по CRM id сделки."""
    abstract_id = db.session.execute(
        select(AmoLead.abstract_customer_id).where(AmoLead.crm_id == crm_lead_id)
    ).scalar_one_or_none()
    if abstract_id is None:
        return None
    return db.session.get(AbstractCustomer, abstract_id)


def create_or_update_customer(abstract_customer: Optional[AbstractCustomer],
                              amo_customer: Customer) -> AbstractCustomer:
    """Создаёт или обновляет покупателя; транзакцией управляет вызывающий."""
    if abstract_customer is None:
        abstract_customer = AbstractCustomer()
        db.session.add(abstract_customer)
        db.session.flush()

    upsert_rows(
        db.session,
        AmoCustomer,
        [{
            'abstract_customer_id': abstract_customer.id,
            'crm_id': getattr(amo_customer, 'id', None),
            'login': get_customer_login(amo_customer),
            'name': getattr(amo_customer, 'name', None),
            'data': get_customer_json(amo_customer),
            'sync_run_id': None,
        }],
        conflict_columns=('crm_id',),
        update_columns=CUSTOMER_UPDATE_COLUMNS,
    )
    return abstract_customer


def create_or_update_lead(abstract_customer: Optional[AbstractCustomer],
                          amo_lead: Lead) -> AbstractCustomer:
    """Создаёт или обновляет сделку; транзакцией управляет вызывающий."""
    if abstract_customer is None:
        abstract_customer = AbstractCustomer()
        db.session.add(abstract_customer)
        db.session.flush()

    upsert_rows(
        db.session,
        AmoLead,
        [{
            'abstract_customer_id': abstract_customer.id,
            'crm_id': getattr(amo_lead, 'id', None),
            'login': get_lead_login(amo_lead),
            'name': getattr(amo_lead, 'name', None),
            'data': get_lead_json(amo_lead),
            'sync_run_id': None,
        }],
        conflict_columns=('crm_id',),
        update_columns=LEAD_UPDATE_COLUMNS,
    )
    return abstract_customer
