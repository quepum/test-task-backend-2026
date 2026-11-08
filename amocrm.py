"""Клиент AmoCRM и разбор ответов API."""

import copy
import time
from typing import Any, Dict, Iterator, List, Type

import requests

TRANSACTIONS = "transactions"
TASKS = "tasks"
CUSTOMERS = "customers"
COMPANIES = "companies"
CONTACTS = "contacts"
CUSTOM_FIELDS = "custom_fields"
LEADS = "leads"
TAGS = "tags"
PIPELINES = "pipelines"
STATUSES = "statuses"
NOTES = "notes"
EVENTS = "events"


class AmoCrmRepeatError(Exception):
    """Надо ещё раз запрос кинуть"""

    def __init__(self, retry_after=None):
        self.retry_after = retry_after
        super().__init__(f"retry after {retry_after}" if retry_after else "retry")


class AmoCrmNoConten(Exception):
    """
    amocrm error not found
    """


class AmoCrmSearchError(Exception):
    """
    amocrm error when search
    """


class AmoCrmError(Exception):
    errors = {
        "301": 'Moved permanently',
        "400": 'Bad request',
        "401": 'Unauthorized',
        "403": 'Forbidden',
        "404": 'Not found',
        "500": 'Internal server error',
        "502": 'Bad gateway',
        "503": 'Service unavailable',
        "429": 'Requests Per Second Exceeded'
    }

    def __init__(self, msg=None, error_code=None):
        self.error_code = error_code
        self.error_description = self.errors.get(str(error_code), f'Undescribed error: {error_code}')
        self.msg = f"{msg or 'AmoCRM error'}, {self.error_description}"
        super().__init__(self.msg)


class AmoCrmCompaniesMoreThanOne(Exception):
    """Найдено больше одной компании."""


def normalize_custom_fields(raw_fields: Any) -> Dict[str, Dict[str, Any]]:
    """Приводит custom_fields_values AmoCRM к словарю {имя поля: {id, value}}.

    Понимает и реальный список полей AmoCRM, и уже нормализованный словарь.
    """
    if not raw_fields:
        return {}
    if isinstance(raw_fields, dict):
        return dict(raw_fields)
    if not isinstance(raw_fields, list):
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        name = item.get('field_name') or item.get('field_code') or item.get('name')
        if not name:
            continue

        values = item.get('values')
        if isinstance(values, list) and values:
            first = values[0]
            value = first.get('value') if isinstance(first, dict) else first
        else:
            value = item.get('value')

        result[name] = {'id': item.get('field_id') or item.get('id'), 'value': value}
    return result


def _embedded_items(embedded: Any, key: str) -> List[Any]:
    if not isinstance(embedded, dict):
        return []
    items = embedded.get(key)
    return items if isinstance(items, list) else []


class BaseEntity:
    """
    base class for entity
    """
    schema = None
    entity_name = None
    url = None
    custom_fields_values = None
    PATCH_FIELDS = None
    FIELDS = ()

    def __str__(self):
        return f"<{type(self).__name__}: {getattr(self, 'name', None)}, {getattr(self, 'id', None)}>"

    def __repr__(self):
        return str(self)

    def get_field(self, field_name):
        """Возвращает значение кастомного поля по имени."""
        field = (self.custom_fields_values or {}).get(field_name)
        if isinstance(field, dict):
            return field.get('value')
        return field

    def as_dict(self) -> Dict[str, Any]:
        """Возвращает JSON-совместимый словарь для колонки data."""
        return copy.deepcopy({
            name: getattr(self, name, None) for name in self.FIELDS
        })

    def set_field(self, field_name, field_value, field_id=None):
        """Записывает значение кастомного поля."""
        if self.custom_fields_values is None:
            self.custom_fields_values = {}
        custom_field = self.custom_fields_values.get(field_name)
        if custom_field is None:
            if field_id is None:
                raise KeyError(f"Not found custom field with key: {field_name}")
            self.custom_fields_values[field_name] = dict(id=field_id, value=field_value)
            return
        if custom_field.get('id'):
            custom_field['value'] = field_value
        elif field_id:
            custom_field['value'] = field_value
            custom_field['id'] = field_id
        else:
            raise ValueError(f"Custom field {field_name} without id")

    def get_url(self):
        """Возвращает URL сущности в API."""
        return self.url


class Customer(BaseEntity):
    """
    class for amocrm customer
    """
    url = "api/v4/customers"
    entity_name = CUSTOMERS
    FIELDS = (
        'id', 'name', 'next_price', 'next_date', 'responsible_user_id',
        'status_id', 'periodicity', 'created_by', 'updated_by', 'created_at',
        'updated_at', 'closest_task_at', 'is_deleted', 'ltv',
        'purchases_count', 'average_check', 'account_id', 'custom_fields_values',
    )

    @classmethod
    def from_dict(cls, payload: Any) -> "Customer":
        """Создаёт покупателя из JSON-объекта AmoCRM."""
        data = payload if isinstance(payload, dict) else {}
        embedded = data.get('_embedded')
        return cls(
            **{field: data.get(field) for field in cls.FIELDS},
            _embedded=embedded if isinstance(embedded, dict) else None,
        )

    def __init__(self,
                 id,
                 name,
                 next_price,
                 next_date,
                 responsible_user_id,
                 status_id,
                 periodicity,
                 created_by,
                 updated_by,
                 created_at,
                 updated_at,
                 closest_task_at,
                 is_deleted,
                 ltv,
                 purchases_count,
                 average_check,
                 account_id,
                 custom_fields_values,
                 _embedded=None
                 ):
        self.id = id
        self.name = name
        self.next_price = next_price
        self.next_date = next_date
        self.responsible_user_id = responsible_user_id
        self.status_id = status_id
        self.periodicity = periodicity
        self.created_by = created_by
        self.updated_by = updated_by
        self.created_at = created_at
        self.updated_at = updated_at
        self.closest_task_at = closest_task_at
        self.is_deleted = is_deleted
        self.ltv = ltv
        self.purchases_count = purchases_count
        self.average_check = average_check
        self.account_id = account_id
        self.custom_fields_values = normalize_custom_fields(custom_fields_values)
        self._embedded = _embedded

        self.companies = []
        self.contacts = []
        self._new_next_date = None
        self.companies = _embedded_items(_embedded, COMPANIES)
        self.contacts = _embedded_items(_embedded, CONTACTS)


class Lead(BaseEntity):
    """
    class for amocrm lead
    """
    url = "api/v4/leads"
    entity_name = LEADS
    PATCH_FIELDS = ("custom_fields_values", "id")
    FIELDS = (
        'id', 'name', 'price', 'responsible_user_id', 'group_id', 'status_id',
        'pipeline_id', 'source_id', 'created_by', 'updated_by', 'created_at',
        'updated_at', 'closest_task_at', 'is_deleted', 'score', 'account_id',
        'custom_fields_values',
    )

    @classmethod
    def from_dict(cls, payload: Any) -> "Lead":
        """Создаёт сделку из JSON-объекта AmoCRM."""
        data = payload if isinstance(payload, dict) else {}
        embedded = data.get('_embedded')
        return cls(
            **{field: data.get(field) for field in cls.FIELDS},
            _embedded=embedded if isinstance(embedded, dict) else None,
        )

    def __init__(self,
                 name=None,
                 id=None,
                 price=None,
                 responsible_user_id=None,
                 group_id=None,
                 status_id=None,
                 pipeline_id=None,
                 source_id=None,
                 created_by=None,
                 updated_by=None,
                 created_at=None,
                 updated_at=None,
                 closest_task_at=None,
                 is_deleted=None,
                 score=None,
                 account_id=None,
                 custom_fields_values=None,
                 _embedded=None
                 ):
        self.id = id
        self.name = name
        self.price = price
        self.responsible_user_id = responsible_user_id
        self.group_id = group_id
        self.status_id = status_id
        self.pipeline_id = pipeline_id
        self.source_id = source_id
        self.created_by = created_by
        self.updated_by = updated_by
        self.created_at = created_at
        self.updated_at = updated_at
        self.closest_task_at = closest_task_at
        self.is_deleted = is_deleted
        self.score = score
        self.account_id = account_id
        self.custom_fields_values = normalize_custom_fields(custom_fields_values)
        self._embedded = _embedded
        self.tags = _embedded_items(_embedded, TAGS)
        self.contacts = _embedded_items(_embedded, CONTACTS)
        self.companies = _embedded_items(_embedded, COMPANIES)


def extract_entities(json_data: Any, entity_name: str):
    """Возвращает сущности страницы CRM, безопасно к пустому _embedded."""
    if not isinstance(json_data, dict):
        return []
    embedded = json_data.get('_embedded')
    if not isinstance(embedded, dict):
        return []
    entities = embedded.get(entity_name)
    if not isinstance(entities, list):
        return []
    return entities


def get_next_href(json_data: Any):
    """Возвращает ссылку на следующую страницу или None."""
    if not isinstance(json_data, dict):
        return None
    links = json_data.get('_links')
    if not isinstance(links, dict):
        return None
    next_link = links.get('next')
    if not isinstance(next_link, dict):
        return None
    href = next_link.get('href')
    return href if isinstance(href, str) and href else None


def amocrm_get(obj_cls: Type[BaseEntity],
               page: int = None,
               limit: int = 250,
               _filter: dict = None,
               _with: str = None,
               query: Any = None,
               custom_filter: dict = None,
               max_attempts: int = 5) -> Iterator[BaseEntity]:
    """Постранично отдаёт сущности AmoCRM с повторами на 429/5xx и сетевые ошибки."""
    params = {}
    if page:
        params['page'] = page
    if limit:
        params['limit'] = limit
    if _filter:
        for key, value in _filter.items():
            filter_key = f'filter[{key}]'
            if isinstance(value, list):
                filter_key = f'{filter_key}[]'
            params[filter_key] = value
    if _with:
        if isinstance(_with, list):
            params['with'] = ",".join(_with)
        else:
            params['with'] = _with
    if query:
        params['query'] = query

    headers = {}
    base_url = ""
    url = f"{base_url}{obj_cls.url}"
    entity_name = obj_cls.entity_name
    factory = getattr(obj_cls, 'from_dict', None)

    while True:
        json_data = None
        attempt = 0
        while True:
            try:
                response = requests.get(url, params=params, headers=headers, timeout=120)
                json_data = response_handler(response)
                break
            except AmoCrmNoConten:
                return
            except AmoCrmRepeatError as exc:
                attempt += 1
                if attempt >= max_attempts:
                    raise
                delay = exc.retry_after or min(2 ** attempt, 30)
                time.sleep(delay)
            except requests.exceptions.RequestException as exc:
                attempt += 1
                if attempt >= max_attempts:
                    raise AmoCrmError(f"Сетевая ошибка AmoCRM: {exc}") from exc
                time.sleep(min(2 ** attempt, 30))

        raw_entities = extract_entities(json_data, entity_name)
        if callable(factory):
            loaded_entities = [factory(raw) for raw in raw_entities]
        else:
            loaded_entities = raw_entities
        for entity in loaded_entities:
            skip_entity = False
            if custom_filter:
                for key, value in custom_filter.items():
                    if entity.get_field(key) != value:
                        skip_entity = True
                        break
            if not skip_entity:
                yield entity

        if page:
            break
        # Идём по курсору, а не по размеру страницы: AmoCRM может вернуть
        # меньше записей и всё равно иметь следующую страницу. Без пауз.
        next_href = get_next_href(json_data)
        if not raw_entities or not next_href:
            break
        url = next_href
        params = {}


def response_handler(response):
    """Проверяет ответ CRM и возвращает JSON; на 429/5xx просит повтор."""
    if response.status_code == 204:
        method = getattr(getattr(response, 'request', None), 'method', 'GET')
        raise AmoCrmNoConten(
            f"no content for {getattr(response, 'url', '')}, method: {method}"
        )
    elif response.status_code == 429:
        retry_after = None
        headers = getattr(response, 'headers', None) or {}
        raw_retry_after = headers.get('Retry-After') if hasattr(headers, 'get') else None
        if raw_retry_after:
            try:
                retry_after = float(raw_retry_after)
            except (TypeError, ValueError):
                retry_after = None
        raise AmoCrmRepeatError(retry_after=retry_after)
    elif 500 <= response.status_code < 600:
        raise AmoCrmRepeatError()
    elif response.status_code != 200:
        json_data = {}
        try:
            json_data = response.json()
        except Exception:
            pass
        raise AmoCrmError(error_code=response.status_code, msg=json_data)
    return response.json()
