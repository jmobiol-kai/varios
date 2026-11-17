-- Rename installed module msb_lafija -> kai_viandas without losing data.
-- Run against the target database BEFORE `odoo -u kai_viandas`.
-- The kai_viandas folder must be on addons_path and msb_lafija must NOT
-- be present as a second module (same models would conflict).
-- Does not touch msb_lafija_quick_checkout's own technical name.
--
-- Usage:
--   psql -U <user> -d <database> -v ON_ERROR_STOP=1 -f migrate_rename.sql

BEGIN;

CREATE TEMP TABLE kai_viandas_rename_log (step text, n bigint);

UPDATE ir_module_module
   SET name = 'kai_viandas',
       icon = replace(coalesce(icon, ''), 'msb_lafija/', 'kai_viandas/'),
       description = CASE
           WHEN description IS NULL THEN description
           ELSE replace(
                    replace(description::text, 'msb_lafija_quick_checkout', 'MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER'),
                    'msb_lafija', 'kai_viandas'
                )::jsonb
       END
 WHERE name = 'msb_lafija';
INSERT INTO kai_viandas_rename_log VALUES (
    'ir_module_module',
    (SELECT count(*) FROM ir_module_module WHERE name = 'kai_viandas')
);

UPDATE ir_module_module_dependency
   SET name = 'kai_viandas'
 WHERE name = 'msb_lafija';
INSERT INTO kai_viandas_rename_log VALUES (
    'ir_module_module_dependency',
    (SELECT count(*) FROM ir_module_module_dependency WHERE name = 'kai_viandas')
);

UPDATE ir_model_data
   SET module = 'kai_viandas'
 WHERE module = 'msb_lafija';
INSERT INTO kai_viandas_rename_log VALUES (
    'ir_model_data.module',
    (SELECT count(*) FROM ir_model_data WHERE module = 'kai_viandas')
);

UPDATE ir_model_data
   SET name = 'module_kai_viandas'
 WHERE module = 'base' AND name = 'module_msb_lafija';

UPDATE ir_model_data
   SET name = replace(name, 'report_msb_lafija_', 'report_kai_viandas_')
 WHERE name LIKE '%report_msb_lafija_%';
INSERT INTO kai_viandas_rename_log VALUES (
    'ir_model_data.report_names',
    (SELECT count(*) FROM ir_model_data WHERE name LIKE '%report_kai_viandas_%')
);

UPDATE ir_model
   SET model = replace(model, 'report.msb_lafija.', 'report.kai_viandas.')
 WHERE model LIKE 'report.msb_lafija.%';
INSERT INTO kai_viandas_rename_log VALUES (
    'ir_model.report',
    (SELECT count(*) FROM ir_model WHERE model LIKE 'report.kai_viandas.%')
);

UPDATE ir_model_fields
   SET model = replace(model, 'report.msb_lafija.', 'report.kai_viandas.')
 WHERE model LIKE 'report.msb_lafija.%';
UPDATE ir_model_fields
   SET relation = replace(relation, 'report.msb_lafija.', 'report.kai_viandas.')
 WHERE relation LIKE 'report.msb_lafija.%';

UPDATE ir_act_report_xml
   SET report_name = replace(report_name, 'msb_lafija.', 'kai_viandas.'),
       report_file = replace(report_file, 'msb_lafija.', 'kai_viandas.')
 WHERE report_name LIKE 'msb_lafija.%' OR report_file LIKE 'msb_lafija.%';
INSERT INTO kai_viandas_rename_log VALUES (
    'ir_act_report_xml',
    (SELECT count(*) FROM ir_act_report_xml WHERE report_name LIKE 'kai_viandas.%' OR report_file LIKE 'kai_viandas.%')
);

UPDATE ir_ui_view
   SET key = replace(key, 'msb_lafija.', 'kai_viandas.')
 WHERE key LIKE 'msb_lafija.%';

UPDATE ir_ui_view
   SET arch_db = replace(
           replace(arch_db::text, 'msb_lafija_quick_checkout', 'MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER'),
           'msb_lafija', 'kai_viandas'
       )::jsonb
 WHERE arch_db IS NOT NULL AND arch_db::text LIKE '%msb_lafija%';

UPDATE ir_ui_view
   SET arch_fs = replace(
           replace(arch_fs, 'msb_lafija_quick_checkout', 'MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER'),
           'msb_lafija', 'kai_viandas'
       )
 WHERE arch_fs LIKE '%msb_lafija%';

UPDATE ir_ui_view
   SET arch_prev = replace(
           replace(arch_prev, 'msb_lafija_quick_checkout', 'MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER'),
           'msb_lafija', 'kai_viandas'
       )
 WHERE arch_prev LIKE '%msb_lafija%';

UPDATE ir_ui_view
   SET arch_db = replace(arch_db::text, 'MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER', 'msb_lafija_quick_checkout')::jsonb
 WHERE arch_db IS NOT NULL AND arch_db::text LIKE '%MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER%';
UPDATE ir_ui_view
   SET arch_fs = replace(arch_fs, 'MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER', 'msb_lafija_quick_checkout')
 WHERE arch_fs LIKE '%MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER%';
UPDATE ir_ui_view
   SET arch_prev = replace(arch_prev, 'MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER', 'msb_lafija_quick_checkout')
 WHERE arch_prev LIKE '%MSB_LAFIJA_QUICK_CHECKOUT_PLACEHOLDER%';

INSERT INTO kai_viandas_rename_log VALUES (
    'ir_ui_view.key',
    (SELECT count(*) FROM ir_ui_view WHERE key LIKE 'kai_viandas.%')
);

UPDATE ir_ui_menu
   SET web_icon = replace(web_icon, 'msb_lafija,', 'kai_viandas,')
 WHERE web_icon LIKE 'msb_lafija,%';
INSERT INTO kai_viandas_rename_log VALUES (
    'ir_ui_menu.web_icon',
    (SELECT count(*) FROM ir_ui_menu WHERE web_icon LIKE 'kai_viandas,%')
);

UPDATE ir_attachment
   SET url = replace(url, '/msb_lafija/', '/kai_viandas/'),
       name = replace(name, '/msb_lafija/', '/kai_viandas/'),
       index_content = replace(index_content, 'msb_lafija', 'kai_viandas')
 WHERE coalesce(url, '') LIKE '%msb_lafija%'
    OR coalesce(name, '') LIKE '%msb_lafija%'
    OR coalesce(index_content, '') LIKE '%msb_lafija%';
INSERT INTO kai_viandas_rename_log VALUES (
    'ir_attachment',
    (SELECT count(*) FROM ir_attachment WHERE coalesce(url,'') LIKE '%kai_viandas%' OR coalesce(name,'') LIKE '%kai_viandas%')
);

UPDATE ir_config_parameter
   SET key = replace(key, 'msb_lafija.', 'kai_viandas.')
 WHERE key LIKE 'msb_lafija.%';
INSERT INTO kai_viandas_rename_log VALUES (
    'ir_config_parameter',
    (SELECT count(*) FROM ir_config_parameter WHERE key LIKE 'kai_viandas.%')
);

DO $$
BEGIN
    IF to_regclass('public.ir_asset') IS NOT NULL THEN
        EXECUTE $q$
            UPDATE ir_asset
               SET path = replace(path, 'msb_lafija/', 'kai_viandas/')
             WHERE path LIKE '%msb_lafija/%'
        $q$;
    END IF;
END$$;

DO $$
DECLARE
  rec record;
  q text;
  n bigint;
BEGIN
  FOR rec IN
    SELECT c.table_name, c.column_name
      FROM information_schema.columns c
      JOIN information_schema.tables t
        ON t.table_schema = c.table_schema AND t.table_name = c.table_name
     WHERE c.table_schema = 'public'
       AND t.table_type = 'BASE TABLE'
       AND c.data_type IN ('text', 'character varying', 'character', 'json', 'jsonb', 'xml')
  LOOP
    q := format(
      'SELECT count(*) FROM %I WHERE CAST(%I AS text) LIKE %L AND CAST(%I AS text) NOT LIKE %L',
      rec.table_name, rec.column_name, '%msb_lafija%', rec.column_name, '%msb_lafija_quick_checkout%'
    );
    EXECUTE q INTO n;
    IF n > 0 THEN
      RAISE NOTICE 'LEFTOVER %.% = %', rec.table_name, rec.column_name, n;
    END IF;
  END LOOP;
END$$;

SELECT * FROM kai_viandas_rename_log ORDER BY 1;
COMMIT;
