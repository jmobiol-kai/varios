from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Separa postres y bebidas que estaban mezclados en las opciones del día."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["lafija.menu.day"].search([])._split_mixed_options()
