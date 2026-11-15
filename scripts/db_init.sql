-- Локальная инициализация БД для проекта «Умный кошелёк».
-- Запуск:
--   psql -U postgres -h localhost -f scripts/db_init.sql
--
-- Скрипт идемпотентен: повторный запуск не ломает существующую БД.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wallet') THEN
        CREATE ROLE wallet LOGIN PASSWORD 'wallet';
        RAISE NOTICE 'Роль wallet создана';
    ELSE
        RAISE NOTICE 'Роль wallet уже существует';
    END IF;
END
$$;

SELECT 'CREATE DATABASE smart_wallet OWNER wallet ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'smart_wallet')\gexec

-- Права на схему public (нужно для PostgreSQL 15+, где public не доступна всем).
\connect smart_wallet
GRANT ALL ON SCHEMA public TO wallet;
ALTER SCHEMA public OWNER TO wallet;
