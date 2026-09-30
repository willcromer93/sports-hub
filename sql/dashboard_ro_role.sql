-- Read-only Postgres role for the public Streamlit dashboard.
-- Run once as a superuser/owner on the database host:
--   psql -d sports_hub -v ro_password="'CHOOSE_A_STRONG_PASSWORD'" -f sql/dashboard_ro_role.sql
-- Then set DASHBOARD_DB_USER=dashboard_ro and DASHBOARD_DB_PASSWORD in the
-- dashboard's .env (see scripts/db.py: get_readonly_connection).

CREATE ROLE dashboard_ro LOGIN PASSWORD :ro_password;
GRANT CONNECT ON DATABASE sports_hub TO dashboard_ro;
GRANT USAGE ON SCHEMA public TO dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboard_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO dashboard_ro;
