-- Dev local: databases por servicio + rol readonly para cross-reads.
-- Se ejecuta en docker-entrypoint-initdb.d (usuario POSTGRES_USER = lead_os).
CREATE ROLE readonly LOGIN PASSWORD 'readonly_dev_password';

CREATE DATABASE auth_db OWNER lead_os;
CREATE DATABASE tenant_db OWNER lead_os;
CREATE DATABASE users_db OWNER lead_os;
CREATE DATABASE files_db OWNER lead_os;

GRANT CONNECT ON DATABASE auth_db TO readonly;
GRANT CONNECT ON DATABASE tenant_db TO readonly;
GRANT CONNECT ON DATABASE users_db TO readonly;
GRANT CONNECT ON DATABASE files_db TO readonly;

\connect auth_db
GRANT USAGE ON SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE lead_os IN SCHEMA public GRANT SELECT ON TABLES TO readonly;

\connect tenant_db
GRANT USAGE ON SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE lead_os IN SCHEMA public GRANT SELECT ON TABLES TO readonly;

\connect users_db
GRANT USAGE ON SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE lead_os IN SCHEMA public GRANT SELECT ON TABLES TO readonly;

\connect files_db
GRANT USAGE ON SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE lead_os IN SCHEMA public GRANT SELECT ON TABLES TO readonly;
