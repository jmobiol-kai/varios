import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Actualizar origen y pedido de las OF ya vinculadas a viandas."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    productions = env["mrp.production"].search([("lf_reservation_ids", "!=", False)])
    for mo in productions:
        try:
            records = mo.lf_reservation_ids
            records._lf_apply_production_refs(mo, records)
        except Exception:
            _logger.exception("No se pudo actualizar el origen de %s al actualizar 19.0.1.14.2", mo.display_name)
