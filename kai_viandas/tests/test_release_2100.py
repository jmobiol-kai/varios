"""19.0.2.1.0: duplicar menú con fecha nueva, sin copiar pedidos."""
from datetime import timedelta

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_preparation import PreparationCommon


@tagged("post_install", "-at_install")
class TestRelease2100(PreparationCommon):
    def _wizard(self, menus, new_date=None):
        wizard = self.env["lafija.menu.duplicate"].with_user(self.operator).with_context(
            default_menu_ids=menus.ids).create({})
        wizard = wizard.with_context(default_menu_ids=menus.ids)
        if new_date:
            wizard.line_ids.write({"new_date": new_date})
        return wizard

    def test_duplicate_menu_with_orders_copies_only_the_menu(self):
        menu = self.menu
        self.assertTrue(menu.reservation_ids)
        before = (len(menu.reservation_ids), menu.revision, menu.published)
        reservations = self.env["lafija.reservation"].search_count([])
        new_date = menu.date + timedelta(days=60)
        wizard = self.env["lafija.menu.duplicate"].with_user(self.operator).create({
            "line_ids": [(0, 0, {"menu_id": menu.id, "new_date": new_date})]})
        self.assertEqual(wizard.line_ids.reservation_count, len(menu.reservation_ids))
        action = wizard.action_apply()
        new = self.env["lafija.menu.day"].browse(action["res_id"])
        self.assertEqual(new.date, new_date)
        self.assertEqual(new.website_id, menu.website_id)
        self.assertEqual(new.product_ids, menu.product_ids)
        self.assertEqual(new.dessert_ids, menu.dessert_ids)
        self.assertEqual(new.drink_ids, menu.drink_ids)
        self.assertFalse(new.published)
        self.assertFalse(new.reservation_ids)
        self.assertEqual(new.revision, 1)
        self.assertEqual(set(new.option_snapshot), {str(p.id) for p in new.product_ids})
        self.assertEqual(self.env["lafija.reservation"].search_count([]), reservations)
        self.assertEqual((len(menu.reservation_ids), menu.revision, menu.published), before)

    def test_clash_and_duplicate_dates_are_rejected(self):
        menu = self.menu
        with self.assertRaises(ValidationError):
            self._wizard(menu, new_date=menu.date).action_apply()
        other = self.menus[1]
        wizard = self._wizard(menu | other)
        wizard.line_ids.write({"new_date": menu.date + timedelta(days=90)})
        if menu.website_id == other.website_id:
            with self.assertRaises(ValidationError):
                wizard.action_apply()

    def test_native_copy_never_hits_the_history_guard(self):
        """El engranaje «Duplicar» (copy) copia solo el menú, sin historia ni pedidos."""
        menu = self.menu
        before = (len(menu.reservation_ids), menu.revision, menu.published)
        new = menu.with_user(self.operator).copy()
        self.assertEqual(new.website_id, menu.website_id)
        self.assertGreater(new.date, menu.date)
        self.assertFalse(new.published)
        self.assertFalse(new.reservation_ids)
        self.assertEqual(new.revision, 1)
        self.assertEqual(set(new.option_snapshot), {str(p.id) for p in new.product_ids})
        self.assertEqual((len(menu.reservation_ids), menu.revision, menu.published), before)
        again = menu.with_user(self.operator).copy()
        self.assertNotEqual(again.date, new.date)
