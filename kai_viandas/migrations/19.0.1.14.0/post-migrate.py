import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Al actualizar, crear o ajustar el pedido diario de las listas ya tomadas."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    for cut in env["lafija.preparation.cut"].search([("current_revision_id", "!=", False)]):
        try:
            cut._lf_sync_daily_orders()
        except Exception:
            _logger.exception("No se pudo sincronizar el pedido diario de %s al actualizar 19.0.1.14.0", cut.display_name)
