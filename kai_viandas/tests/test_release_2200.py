"""19.0.2.2.0: cambiar un plato agotado después de tomar pedidos y la lista."""
from freezegun import freeze_time

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_preparation import PreparationCommon


@tagged("post_install", "-at_install")
class TestRelease2200(PreparationCommon):
    def _wizard(self, **values):
        return self.env["lafija.menu.change"].with_user(self.operator).create({"menu_id": self.menu.id, **values})

    def test_sold_out_plate_swap_after_list_taken_keeps_orders(self):
        self._take()
        menu = self.menu
        reservation = self.reservation.sudo()
        orders_before = reservation.lf_daily_order_id
        chosen = reservation.current_product_id
        self.assertEqual(chosen, self.chicken)
        replacement = self.env["product.product"].create({
            "name": "Tarta de verdura", "description_sale": "Tarta", "list_price": 100, "type": "consu",
            "categ_id": self.plate_categ.id, "website_id": self.env.ref("website.default_website").id})
        revision = menu.revision
        with freeze_time("2026-09-14 13:30:00"):
            self._wizard(sold_out_ids=[(6, 0, [self.chicken.id])],
                         add_plate_ids=[(6, 0, [replacement.id])], reason="Se acabó el pollo").action_apply()
        self.assertNotIn(self.chicken, menu.product_ids)
        self.assertIn(replacement, menu.product_ids)
        self.assertEqual(menu.revision, revision + 1)
        self.assertNotIn(str(self.chicken.id), menu.option_snapshot)
        self.assertIn(str(replacement.id), menu.option_snapshot)
        # La vianda ya pedida se mantiene tal cual.
        self.assertEqual(reservation.current_product_id, chosen)
        self.assertEqual(reservation.state, "active")
        self.assertEqual(reservation.lf_daily_order_id, orders_before)
        note = menu.sudo().message_ids[:1].body
        self.assertIn("Dejó de ofrecerse", str(note))
        self.assertIn("ya lo habían elegido 1", str(note))
        self.assertIn("Se acabó el pollo", str(note))

    def test_direct_edit_is_logged_too(self):
        self._take()
        with freeze_time("2026-09-14 13:30:00"):
            self.menu.with_user(self.operator).write({"product_ids": [(3, self.pork.id)]})
        self.assertIn("Dejó de ofrecerse", str(self.menu.sudo().message_ids[:1].body))

    def test_cannot_empty_a_published_menu(self):
        menu = self.menu
        self.assertTrue(menu.published)
        wizard = self._wizard(sold_out_ids=[(6, 0, menu.product_ids.ids)])
        with self.assertRaises(ValidationError):
            wizard.action_apply()

    def test_inline_list_edit_goes_through_same_logic(self):
        """Edición inline/multi-edit de la lista: es un write común sobre la oferta."""
        self._take()
        menu = self.menu
        revision = menu.revision
        choices = self.reservation.sudo().current_product_id
        with freeze_time("2026-09-14 13:30:00"):
            menu.with_user(self.operator).write({"product_ids": [(3, self.pork.id)]})
        self.assertEqual(menu.revision, revision + 1)
        self.assertEqual(self.reservation.sudo().current_product_id, choices)
        self.assertIn("Dejó de ofrecerse", str(menu.sudo().message_ids[:1].body))
        view = self.env.ref("kai_viandas.menu_day_list")
        self.assertIn('multi_edit="1"', view.arch_db)
