-- Шаг 3/4: индексы для ночного поиска и внешних запросов по логину/названию.
-- Требует 001_create_tables.sql и 002_copy_data.sql.
-- Применять: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/003_indexes.sql

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_amo_customers_crm_id
    ON amo_customers (crm_id);
CREATE INDEX IF NOT EXISTS ix_amo_customers_login ON amo_customers (login);
CREATE INDEX IF NOT EXISTS ix_amo_customers_name ON amo_customers (name);
CREATE INDEX IF NOT EXISTS ix_amo_customers_sync_run_id ON amo_customers (sync_run_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_amo_leads_crm_id ON amo_leads (crm_id);
CREATE INDEX IF NOT EXISTS ix_amo_leads_login ON amo_leads (login);
CREATE INDEX IF NOT EXISTS ix_amo_leads_name ON amo_leads (name);
CREATE INDEX IF NOT EXISTS ix_amo_leads_sync_run_id ON amo_leads (sync_run_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_amo_contacts_abstract_customer_id_crm_id
    ON amo_contacts (abstract_customer_id, crm_id);
CREATE INDEX IF NOT EXISTS ix_amo_contacts_crm_id ON amo_contacts (crm_id);
CREATE INDEX IF NOT EXISTS ix_amo_contacts_name ON amo_contacts (name);
CREATE INDEX IF NOT EXISTS ix_amo_contacts_sync_run_id ON amo_contacts (sync_run_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_amo_companies_abstract_customer_id_crm_id
    ON amo_companies (abstract_customer_id, crm_id);
CREATE INDEX IF NOT EXISTS ix_amo_companies_crm_id ON amo_companies (crm_id);
CREATE INDEX IF NOT EXISTS ix_amo_companies_name ON amo_companies (name);
CREATE INDEX IF NOT EXISTS ix_amo_companies_sync_run_id ON amo_companies (sync_run_id);

CREATE INDEX IF NOT EXISTS ix_send_methods_sync_run_id ON send_methods (sync_run_id);

COMMIT;
