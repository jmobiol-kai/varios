"""Menú Preparación sin Listas ni Entregas del día · 19.0.1.16.1."""
from odoo.tests import tagged

from .test_release_114 import TestRelease114


@tagged("post_install", "-at_install")
class TestRelease1161(TestRelease114):
    def test_preparation_group_only_keeps_menus_del_dia(self):
        # 19.0.1.16.3: Menús del día es de primer nivel; el grupo Preparación ya no existe.
        menus = self.env.ref("kai_viandas.menu_days")
        self.assertEqual(menus.action, self.env.ref("kai_viandas.menu_day_action"))
        missing = self.env["ir.model.data"].sudo().search([
            ("module", "=", "kai_viandas"),
            ("name", "in", ["menu_preparation", "menu_deliveries"]),
        ])
        self.assertFalse(missing)
        # Las acciones y los modelos siguen, para la historia y el menú del día.
        self.assertTrue(self.env.ref("kai_viandas.cut_action"))
        self.assertTrue(self.env.ref("kai_viandas.delivery_action"))
        self.assertEqual(self.env.ref("kai_viandas.cut_action").res_model, "lafija.preparation.cut")
        self.assertEqual(self.env.ref("kai_viandas.delivery_action").res_model, "lafija.reservation")

    def test_take_list_and_elaborate_banner_still_open_the_cut_form(self):
        cut = self._take()
        opened = self.menu.with_user(self.operator).action_open_fulfillment()
        self.assertEqual(opened["res_model"], "lafija.preparation.cut")
        self.assertEqual(opened["res_id"], cut.id)
        self.assertEqual(opened.get("view_id"), self.env.ref("kai_viandas.cut_form").id)
        taken = self.menu.with_user(self.operator).action_take_list()
        self.assertEqual(taken["res_model"], "lafija.preparation.cut")
        self.assertEqual(taken["res_id"], cut.id)

    def test_operator_help_no_longer_points_to_removed_menus(self):
        views = self.env["ir.ui.view"].sudo().search([
            ("key", "=", "kai_viandas.help_operator_content"),
        ], limit=1) or self.env.ref("kai_viandas.help_operator_content")
        arch = views.arch if "arch" in views._fields else self.env.ref("kai_viandas.help_operator_content").arch
        self.assertIn("Menús del día", arch)
        self.assertNotIn("Preparación → Listas de preparación", arch)
        self.assertNotIn("Preparación → Entregas del día", arch)
        self.assertNotIn("Entregas del día", arch)
