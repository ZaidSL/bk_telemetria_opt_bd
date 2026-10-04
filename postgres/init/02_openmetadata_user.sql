-- ===============================================================
-- 02_OPENMETADATA_USER.SQL
-- Crea el usuario de solo-lectura para OpenMetadata y el Agente IA.
-- También habilita auto_explain para capturar planes de ejecución
-- en los logs que ya recoge Promtail → Loki.
-- ===============================================================

-- 1. Usuario de solo lectura (nunca escribe en la BD bancaria)
CREATE USER openmetadata_reader WITH PASSWORD 'om_reader_2026';

GRANT CONNECT ON DATABASE banco_telemetria TO openmetadata_reader;
GRANT USAGE ON SCHEMA public TO openmetadata_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO openmetadata_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO openmetadata_reader;

-- pg_read_all_stats: permite leer pg_stat_statements, pg_stat_user_tables, etc.
GRANT pg_read_all_stats TO openmetadata_reader;

-- 2. Habilitar auto_explain para capturar planes de consultas lentas en los logs
--    (>100ms → plan visible en Loki automáticamente sin intervención manual)
LOAD 'auto_explain';
ALTER SYSTEM SET auto_explain.log_min_duration = '100ms';
ALTER SYSTEM SET auto_explain.log_analyze = on;
ALTER SYSTEM SET auto_explain.log_buffers = on;
ALTER SYSTEM SET auto_explain.log_format = 'text';
SELECT pg_reload_conf();
