"""Menú Viandas sin la entrada Pendientes · 19.0.1.16.2."""
from odoo.tests import tagged

from .test_release_114 import TestRelease114


@tagged("post_install", "-at_install")
class TestRelease1162(TestRelease114):
    def test_root_menu_no_longer_has_pendientes(self):
        root = self.env.ref("kai_viandas.menu_root")
        sections = self.env["ir.ui.menu"].search([("parent_id", "=", root.id)], order="sequence,id")
        self.assertNotIn("Pendientes", sections.mapped("name"))
        missing = self.env["ir.model.data"].sudo().search([
            ("module", "=", "kai_viandas"),
            ("name", "=", "menu_pending"),
        ])
        self.assertFalse(missing)
        # La acción y el modelo siguen, para el botón de Hoy y el filtro de consulta.
        action = self.env.ref("kai_viandas.pending_action")
        self.assertEqual(action.res_model, "lafija.reservation")
        self.assertEqual(action.name, "Pendientes · todas las fechas")
        self.assertIn("search_default_pending", action.context)

    def test_hoy_button_and_consultar_reservas_filter_cover_all_pending(self):
        opened = self.env["lafija.reservation"].with_user(self.operator).action_pending_all_dates()
        pending = self.env.ref("kai_viandas.pending_action")
        self.assertEqual(opened["id"], pending.id)
        self.assertIn("search_default_pending", opened["context"])
        search = self.env.ref("kai_viandas.reservation_search")
        arch = search.arch
        self.assertIn('name="pending"', arch)
        self.assertIn("Requieren atención", arch)
        self.assertIn("[('pending', '=', True)]", arch)
        consultar = self.env.ref("kai_viandas.reservation_action")
        self.assertEqual(consultar.search_view_id, search)
        self.assertEqual(pending.search_view_id, search)

    def test_operator_help_no_longer_points_to_pendientes_menu(self):
        views = self.env["ir.ui.view"].sudo().search([
            ("key", "=", "kai_viandas.help_operator_content"),
        ], limit=1) or self.env.ref("kai_viandas.help_operator_content")
        arch = views.arch if "arch" in views._fields else self.env.ref("kai_viandas.help_operator_content").arch
        self.assertNotIn("tiene seis entradas", arch)
        self.assertNotIn("Viandas → <strong>Pendientes</strong>", arch)
        self.assertNotIn("Hoy y Pendientes", arch)
        self.assertNotIn("Ver pendientes de cualquier fecha", arch)
        self.assertIn("Agregar pedido cliente", arch)
