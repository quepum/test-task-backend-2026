-- Шаг 2/4: переносит данные из старых JSONB-колонок и выравнивает sequence.
-- Требует 001_create_tables.sql. Повторный запуск не дублирует данные.
-- Применять: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/002_copy_data.sql

BEGIN;

DO $$
DECLARE
    legacy_columns int;
BEGIN
    IF to_regclass('amo_customers') IS NULL OR to_regclass('send_methods') IS NULL THEN
        RAISE EXCEPTION 'сначала выполните 001_create_tables.sql';
    END IF;

    SELECT count(*) INTO legacy_columns
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'abstract_customer'
      AND column_name IN (
          'amo_customers', 'amo_leads', 'amo_contacts',
          'amo_companies', 'send_methods'
      );

    IF legacy_columns <> 5 THEN
        RAISE EXCEPTION
            'ожидались 5 JSONB-колонок abstract_customer, найдено %; '
            'миграция уже применена или схема другая', legacy_columns;
    END IF;
END $$;

-- Покупатели
INSERT INTO amo_customers (abstract_customer_id, crm_id, login, name, data)
SELECT
    ac.id,
    CASE WHEN elem->'general'->>'id' ~ '^[0-9]+$'
         THEN (elem->'general'->>'id')::bigint ELSE NULL END,
    elem->'general'->>'login',
    elem->'general'->>'name',
    CASE WHEN jsonb_typeof(elem) = 'object' THEN elem ELSE '{}'::jsonb END
FROM abstract_customer ac
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(COALESCE(ac.amo_customers, '[]'::jsonb)) = 'array'
         THEN COALESCE(ac.amo_customers, '[]'::jsonb)
         ELSE '[]'::jsonb END
) AS elem
WHERE NOT EXISTS (SELECT 1 FROM amo_customers);

-- Сделки
INSERT INTO amo_leads (abstract_customer_id, crm_id, login, name, data)
SELECT
    ac.id,
    CASE WHEN elem->'general'->>'id' ~ '^[0-9]+$'
         THEN (elem->'general'->>'id')::bigint ELSE NULL END,
    elem->'general'->>'login',
    elem->'general'->>'name',
    CASE WHEN jsonb_typeof(elem) = 'object' THEN elem ELSE '{}'::jsonb END
FROM abstract_customer ac
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(COALESCE(ac.amo_leads, '[]'::jsonb)) = 'array'
         THEN COALESCE(ac.amo_leads, '[]'::jsonb)
         ELSE '[]'::jsonb END
) AS elem
WHERE NOT EXISTS (SELECT 1 FROM amo_leads);

-- Контакты
INSERT INTO amo_contacts (abstract_customer_id, crm_id, name, data)
SELECT
    ac.id,
    CASE WHEN elem->'general'->>'id' ~ '^[0-9]+$'
         THEN (elem->'general'->>'id')::bigint ELSE NULL END,
    elem->'general'->>'name',
    CASE WHEN jsonb_typeof(elem) = 'object' THEN elem ELSE '{}'::jsonb END
FROM abstract_customer ac
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(COALESCE(ac.amo_contacts, '[]'::jsonb)) = 'array'
         THEN COALESCE(ac.amo_contacts, '[]'::jsonb)
         ELSE '[]'::jsonb END
) AS elem
WHERE NOT EXISTS (SELECT 1 FROM amo_contacts);

-- Компании
INSERT INTO amo_companies (abstract_customer_id, crm_id, name, data)
SELECT
    ac.id,
    CASE WHEN elem->'general'->>'id' ~ '^[0-9]+$'
         THEN (elem->'general'->>'id')::bigint ELSE NULL END,
    elem->'general'->>'name',
    CASE WHEN jsonb_typeof(elem) = 'object' THEN elem ELSE '{}'::jsonb END
FROM abstract_customer ac
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(COALESCE(ac.amo_companies, '[]'::jsonb)) = 'array'
         THEN COALESCE(ac.amo_companies, '[]'::jsonb)
         ELSE '[]'::jsonb END
) AS elem
WHERE NOT EXISTS (SELECT 1 FROM amo_companies);

-- Способы связи
INSERT INTO send_methods (abstract_customer_id, type, value, description, data)
SELECT
    ac.id,
    elem->>'type',
    elem->>'value',
    elem->>'desc',
    CASE WHEN jsonb_typeof(elem) = 'object' THEN elem ELSE '{}'::jsonb END
FROM abstract_customer ac
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(COALESCE(ac.send_methods, '[]'::jsonb)) = 'array'
         THEN COALESCE(ac.send_methods, '[]'::jsonb)
         ELSE '[]'::jsonb END
) AS elem
WHERE NOT EXISTS (SELECT 1 FROM send_methods);

-- Старый код мог создать несколько агрегатов с одним CRM id.
-- Оставляем строку с наибольшим id перед созданием уникальных индексов.
DELETE FROM amo_customers a
USING amo_customers b
WHERE a.crm_id IS NOT NULL
  AND a.crm_id = b.crm_id
  AND a.id < b.id;

DELETE FROM amo_leads a
USING amo_leads b
WHERE a.crm_id IS NOT NULL
  AND a.crm_id = b.crm_id
  AND a.id < b.id;

DELETE FROM amo_contacts a
USING amo_contacts b
WHERE a.crm_id IS NOT NULL
  AND a.crm_id = b.crm_id
  AND a.abstract_customer_id = b.abstract_customer_id
  AND a.id < b.id;

DELETE FROM amo_companies a
USING amo_companies b
WHERE a.crm_id IS NOT NULL
  AND a.crm_id = b.crm_id
  AND a.abstract_customer_id = b.abstract_customer_id
  AND a.id < b.id;

-- Sequence новых таблиц должны идти после перенесённых id.
SELECT setval(
    pg_get_serial_sequence('abstract_customer', 'id'),
    COALESCE((SELECT MAX(id) FROM abstract_customer), 0) + 1,
    false
);
SELECT setval(
    pg_get_serial_sequence('amo_customers', 'id'),
    COALESCE((SELECT MAX(id) FROM amo_customers), 0) + 1,
    false
);
SELECT setval(
    pg_get_serial_sequence('amo_leads', 'id'),
    COALESCE((SELECT MAX(id) FROM amo_leads), 0) + 1,
    false
);
SELECT setval(
    pg_get_serial_sequence('amo_contacts', 'id'),
    COALESCE((SELECT MAX(id) FROM amo_contacts), 0) + 1,
    false
);
SELECT setval(
    pg_get_serial_sequence('amo_companies', 'id'),
    COALESCE((SELECT MAX(id) FROM amo_companies), 0) + 1,
    false
);
SELECT setval(
    pg_get_serial_sequence('send_methods', 'id'),
    COALESCE((SELECT MAX(id) FROM send_methods), 0) + 1,
    false
);

COMMIT;
