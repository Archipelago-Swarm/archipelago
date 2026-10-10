-- NOLOGIN group roles; operators grant LOGIN + password out of band (no secrets in git).
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'archipelago_writer') THEN
    CREATE ROLE archipelago_writer NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'archipelago_reader') THEN
    CREATE ROLE archipelago_reader NOLOGIN;
  END IF;
END $$;
GRANT SELECT, INSERT ON runs, events, metrics, dropped_metrics, artifacts TO archipelago_writer;
GRANT SELECT ON runs, events, metrics, dropped_metrics, artifacts TO archipelago_reader;
