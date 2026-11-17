import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Crear las OF en borrador que falten en listas ya tomadas; no tocar las confirmadas."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    for cut in env["lafija.preparation.cut"].search([("current_revision_id", "!=", False)]):
        try:
            cut._lf_sync_draft_productions()
        except Exception:
            _logger.exception("No se pudieron crear las órdenes de fabricación en borrador de %s al actualizar 19.0.1.14.1", cut.display_name)
