-- Шаг 1/4: создаёт нормализованные таблицы под сущности AmoCRM.
-- Требует существующую таблицу abstract_customer (старая схема).
-- Применять: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_create_tables.sql

BEGIN;

DO $$
BEGIN
    IF to_regclass('abstract_customer') IS NULL THEN
        RAISE EXCEPTION 'таблица abstract_customer не найдена';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS amo_customers (
    id BIGSERIAL PRIMARY KEY,
    abstract_customer_id BIGINT NOT NULL
        REFERENCES abstract_customer(id) ON DELETE CASCADE,
    crm_id BIGINT,
    login TEXT,
    name TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    sync_run_id BIGINT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS amo_leads (
    id BIGSERIAL PRIMARY KEY,
    abstract_customer_id BIGINT NOT NULL
        REFERENCES abstract_customer(id) ON DELETE CASCADE,
    crm_id BIGINT,
    login TEXT,
    name TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    sync_run_id BIGINT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS amo_contacts (
    id BIGSERIAL PRIMARY KEY,
    abstract_customer_id BIGINT NOT NULL
        REFERENCES abstract_customer(id) ON DELETE CASCADE,
    crm_id BIGINT,
    login TEXT,
    name TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    sync_run_id BIGINT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS amo_companies (
    id BIGSERIAL PRIMARY KEY,
    abstract_customer_id BIGINT NOT NULL
        REFERENCES abstract_customer(id) ON DELETE CASCADE,
    crm_id BIGINT,
    login TEXT,
    name TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    sync_run_id BIGINT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS send_methods (
    id BIGSERIAL PRIMARY KEY,
    abstract_customer_id BIGINT NOT NULL
        REFERENCES abstract_customer(id) ON DELETE CASCADE,
    type TEXT,
    value TEXT,
    description TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    sync_run_id BIGINT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);

COMMIT;
