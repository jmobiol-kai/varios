import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Unir OF en borrador del mismo plato y día; no toca las OF hechas."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        env["lafija.reservation"]._lf_merge_draft_productions_by_dish_day()
    except Exception:
        _logger.exception("No se pudieron unir las órdenes de fabricación en borrador al actualizar 19.0.1.15.0")
