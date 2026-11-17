from odoo import api, SUPERUSER_ID
from odoo.addons.kai_viandas.models.reservation import operation_context


def migrate(cr, version):
    """Recupera también solicitudes que el guardado anterior sacó de la cola.

    Se conserva íntegra la historia. En la versión anterior, 'note' era una
    respuesta sin cierre aunque estuviera clasificada como resolución.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT reservation_id,
               max(id) FILTER (WHERE kind = 'request') >
               COALESCE(max(id) FILTER (
                   WHERE kind = 'resolution' AND result NOT LIKE 'note:%%'
               ), 0) AS still_open
          FROM lafija_reservation_event
         GROUP BY reservation_id
    """)
    for reservation_id, still_open in cr.fetchall():
        env['lafija.reservation'].browse(reservation_id).with_context(
            **operation_context()
        ).write({'attention_pending': bool(still_open)})
