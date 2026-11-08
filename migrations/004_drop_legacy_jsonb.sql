-- Шаг 4/4: удаляет старые JSONB-колонки. Необратимо, нужен бэкап.
-- Требует 001-003 и не запускается, если данные не были перенесены.
-- Применять: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/004_drop_legacy_jsonb.sql

BEGIN;

DO $$
DECLARE
    legacy_columns int;
    legacy_rows bigint;
    copied_rows bigint;
BEGIN
    IF to_regclass('amo_customers') IS NULL
       OR to_regclass('amo_leads') IS NULL
       OR to_regclass('amo_contacts') IS NULL
       OR to_regclass('amo_companies') IS NULL
       OR to_regclass('send_methods') IS NULL THEN
        RAISE EXCEPTION 'сначала выполните 001-003';
    END IF;

    SELECT count(*) INTO legacy_columns
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'abstract_customer'
      AND column_name IN (
          'amo_customers', 'amo_leads', 'amo_contacts',
          'amo_companies', 'send_methods'
      );

    IF legacy_columns = 0 THEN
        RAISE NOTICE 'JSONB-колонки уже удалены';
        RETURN;
    END IF;

    IF legacy_columns <> 5 THEN
        RAISE EXCEPTION 'часть JSONB-колонок уже удалена; проверьте схему вручную';
    END IF;

    SELECT count(*) INTO legacy_rows
    FROM abstract_customer
    WHERE CASE WHEN jsonb_typeof(amo_customers) = 'array'
               THEN jsonb_array_length(amo_customers) ELSE 0 END > 0
       OR CASE WHEN jsonb_typeof(amo_leads) = 'array'
               THEN jsonb_array_length(amo_leads) ELSE 0 END > 0
       OR CASE WHEN jsonb_typeof(amo_contacts) = 'array'
               THEN jsonb_array_length(amo_contacts) ELSE 0 END > 0
       OR CASE WHEN jsonb_typeof(amo_companies) = 'array'
               THEN jsonb_array_length(amo_companies) ELSE 0 END > 0
       OR CASE WHEN jsonb_typeof(send_methods) = 'array'
               THEN jsonb_array_length(send_methods) ELSE 0 END > 0;

    SELECT (SELECT count(*) FROM amo_customers)
         + (SELECT count(*) FROM amo_leads)
         + (SELECT count(*) FROM amo_contacts)
         + (SELECT count(*) FROM amo_companies)
      INTO copied_rows;

    IF legacy_rows > 0 AND copied_rows = 0 THEN
        RAISE EXCEPTION 'в новых таблицах нет данных: сначала выполните 002_copy_data.sql';
    END IF;
END $$;

ALTER TABLE abstract_customer DROP COLUMN IF EXISTS amo_customers;
ALTER TABLE abstract_customer DROP COLUMN IF EXISTS amo_leads;
ALTER TABLE abstract_customer DROP COLUMN IF EXISTS amo_contacts;
ALTER TABLE abstract_customer DROP COLUMN IF EXISTS amo_companies;
ALTER TABLE abstract_customer DROP COLUMN IF EXISTS send_methods;

COMMIT;
