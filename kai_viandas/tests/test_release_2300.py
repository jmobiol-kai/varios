"""19.0.2.3.0: cambiar la elección de una vianda hasta el corte, moviéndola de una OF a otra."""
from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_preparation import PreparationCommon
from .test_release_112 import SidesCommon
from .test_release_114 import TestRelease114


@tagged("post_install", "-at_install")
class TestRelease2300(SidesCommon, PreparationCommon):
    def setUp(self):
        super().setUp()
        self.first = TestRelease114._goods_plate(self, "Guiso 2300 A")
        self.second = TestRelease114._goods_plate(self, "Tarta 2300 B")
        self.menu.with_user(self.operator).write({"product_ids": [Command.link(self.first.id), Command.link(self.second.id)]})
        other, _wizard = self._create_employee("abc-otro-2300")
        self.other_service = self.env["lafija.reservation"].with_user(other)
        with freeze_time("2026-09-08 12:00:00"):
            self.service._submit_selections(self.website, [(self.menu.id, self.first.id)])
            self.other = self.other_service._submit_selections(self.website, [(self.menu.id, self.first.id)])
        self.mo = self.reservation.sudo().fulfillment_production_ids.filtered(lambda mo: mo.product_id == self.first)
        self._take()

    def _change(self, record=None, **values):
        record = record or self.reservation
        wizard = self.env["lafija.reservation.correction"].with_user(self.operator).create({
            "reservation_id": record.id, "operation": "change", "reason": "Pidió otro plato", **values})
        return wizard.action_apply()

    def _mo(self, product):
        return self.env["mrp.production"].sudo().search([
            ("product_id", "=", product.id), ("lf_meal_date", "=", self.menu.date)])

    def test_change_before_cutoff_moves_the_vianda_between_draft_mos(self):
        self.assertEqual(self.mo.product_qty, 2)
        self.assertEqual(self.mo.state, "draft")
        with freeze_time("2026-09-14 12:00:00"):  # 09:00 en Buenos Aires
            self._change(product_id=self.second.id, dessert_id=self.flan.id)
            self.assertEqual(self.mo.product_qty, 1)
            new = self._mo(self.second)
            self.assertEqual(new.product_qty, 1)
            self.assertEqual(new.state, "draft")
            self.assertIn(self.reservation.sudo(), new.lf_reservation_ids)
            self.assertNotIn(self.reservation.sudo(), self.mo.lf_reservation_ids)
            self.assertEqual(self.reservation.sudo().current_product_id, self.second)
            self.assertEqual(self.reservation.sudo().current_dessert_id, self.flan)
            self.assertIn("Se quitó la vianda", " ".join(self.mo.message_ids.mapped("body")))
            self.assertIn("Se sumó la vianda", " ".join(new.message_ids.mapped("body")))
            self.assertIn("OF:", " ".join(self.reservation.sudo().event_ids.mapped("result")))
            # La segunda vianda deja la primera OF en cero: se cancela, sin tocar otras.
            self._change(self.other, product_id=self.second.id)
            self.assertEqual(self.mo.state, "cancel")
            self.assertEqual(new.product_qty, 2)

    def test_change_is_blocked_after_the_cutoff(self):
        with freeze_time("2026-09-14 13:31:00"):  # 10:31 en Buenos Aires
            self.assertFalse(self.reservation.sudo().lf_can_change)
            with self.assertRaises(ValidationError) as error:
                self._change(product_id=self.second.id)
            self.assertIn("10:30", str(error.exception))
        self.assertEqual(self.reservation.sudo().current_product_id, self.first)
        self.assertEqual(self.mo.product_qty, 2)

    def test_change_is_blocked_once_the_mo_is_confirmed_or_started(self):
        with freeze_time("2026-09-14 12:00:00"):
            self.mo.action_confirm()
            self.reservation.invalidate_recordset()
            self.assertFalse(self.reservation.sudo().lf_can_change)
            with self.assertRaises(ValidationError):
                self._change(product_id=self.second.id)
            with self.assertRaises(ValidationError):
                self.reservation.with_user(self.operator).action_change_choice()
        self.assertEqual(self.reservation.sudo().current_product_id, self.first)
        self.assertEqual(self.mo.product_qty, 2)

    def test_new_choice_must_be_offered_and_different(self):
        outside = TestRelease114._goods_plate(self, "Plato fuera del menú 2300")
        with freeze_time("2026-09-14 12:00:00"):
            with self.assertRaises(ValidationError):
                self._change(product_id=outside.id)
            with self.assertRaises(ValidationError):
                self._change(product_id=self.first.id)
            self.assertTrue(self.reservation.sudo().lf_can_change)
            action = self.reservation.with_user(self.operator).action_change_choice()
            self.assertEqual(action["context"]["default_operation"], "change")
            self.assertEqual(action["context"]["default_product_id"], self.first.id)
        self.assertEqual(self.mo.product_qty, 2)

    def test_only_operators_and_row_button_exists(self):
        with freeze_time("2026-09-14 12:00:00"):
            with self.assertRaises(Exception):
                self.env["lafija.reservation.correction"].with_user(self.env["res.users"].browse(self.service.env.uid)).create({
                    "reservation_id": self.reservation.id, "operation": "change", "product_id": self.second.id,
                    "reason": "x"}).action_apply()
        arch = self.env["lafija.reservation"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.reservation_list").id, "list"]])["views"]["list"]["arch"]
        self.assertIn('multi_edit="1"', arch)
        self.assertIn("lf_new_product_id", arch)

    def test_inline_list_write_moves_the_vianda_between_mos(self):
        """19.0.2.3.1: tildar la fila y cambiar el plato en la lista Pedidos = «Cambiar elección antes del corte»."""
        reservation = self.reservation.with_user(self.operator)
        with freeze_time("2026-09-14 12:00:00"):
            self.assertEqual(reservation.lf_new_product_id, self.first)
            self.assertIn(self.second, reservation.lf_offer_product_ids)
            reservation.write({"lf_new_product_id": self.second.id})
            self.assertEqual(self.reservation.sudo().current_product_id, self.second)
            self.assertEqual(self.mo.product_qty, 1)
            new = self._mo(self.second)
            self.assertEqual((new.state, new.product_qty), ("draft", 1))
            self.assertIn(self.reservation.sudo(), new.lf_reservation_ids)
            self.assertIn("OF:", " ".join(self.reservation.sudo().event_ids.mapped("result")))
            # Varias filas a la vez: cada vianda se valida y se mueve por separado.
            both = (self.reservation | self.other).with_user(self.operator)
            both.write({"lf_new_dessert_id": self.flan.id})
            self.assertEqual((self.reservation | self.other).sudo().mapped("current_dessert_id"), self.flan)
            self.assertEqual(self.other.sudo().current_product_id, self.first)
            self.assertEqual(self.mo.product_qty, 1)

    def test_inline_list_write_is_blocked_with_the_same_rules(self):
        outside = TestRelease114._goods_plate(self, "Plato fuera del menú 2301")
        reservation = self.reservation.with_user(self.operator)
        with freeze_time("2026-09-14 13:31:00"):  # después del corte
            with self.assertRaises(ValidationError) as error:
                reservation.write({"lf_new_product_id": self.second.id})
            self.assertIn("10:30", str(error.exception))
        with freeze_time("2026-09-14 12:00:00"):
            with self.assertRaises(ValidationError):
                reservation.write({"lf_new_product_id": outside.id})
            self.mo.action_confirm()
            with self.assertRaises(ValidationError):
                reservation.write({"lf_new_product_id": self.second.id})
            # Varias filas: si una no se puede, no se aplica ninguna.
            with self.assertRaises(ValidationError):
                (self.reservation | self.other).with_user(self.operator).write({"lf_new_product_id": self.second.id})
        self.assertEqual((self.reservation | self.other).sudo().mapped("current_product_id"), self.first)
        self.assertEqual(self.mo.product_qty, 2)
        with freeze_time("2026-09-14 12:00:00"):
            with self.assertRaises(Exception):
                self.reservation.with_user(self.service.env.user).write({"lf_new_product_id": self.second.id})
