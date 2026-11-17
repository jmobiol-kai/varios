def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    summary = env["lafija.reservation"]._lf_migrate_explicit_quotations()
    env.cr.commit()
    import logging
    logging.getLogger(__name__).info("kai_viandas 19.0.1.17.6 migration %s", summary)
