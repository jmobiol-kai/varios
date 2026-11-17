"""Editar, cortes 10:30 / sábado 14:00 y OF automática · 19.0.1.17.8."""
from lxml import etree
from freezegun import freeze_time
from odoo import Command
from odoo.tests import tagged

from odoo.addons.kai_viandas.models import order_windows

from ..models.reservation import OrderWindowClosed, operation_context
from .test_preparation import PreparationCommon
from .test_release_112 import SidesCommon
from .test_release_114 import TestRelease114


@tagged("post_install", "-at_install")
class TestRelease1177(SidesCommon, PreparationCommon):
    def _goods_plate(self, name):
        return TestRelease114._goods_plate(self, name)

    def _other_company_employee(self, login):
        other = self.env["res.partner"].create({"name": f"Otra empresa {login}", "is_company": True})
        wizard = self.env["lafija.employee.access"].with_user(self.operator).create({
            "operation": "create", "name": f"Ana {login}", "login": login,
            "customer_company_id": other.id, "website_id": self.website.id,
            "new_password": "employee-password-123", "reason": f"Alta {login}",
        })
        result = wizard.action_apply()
        partner = self.env["res.partner"].browse(result["res_id"])
        return partner.user_ids, other

    def _force_pending(self, record, plate, current=False):
        record.sudo().with_context(**operation_context()).write({
            "current_product_id": current.id if current else False,
            "current_description": (current.description_sale or current.display_name) if current else False,
            "pending_product_id": plate.id,
            "pending_description": plate.description_sale or plate.display_name,
            "pending_dessert_id": False, "pending_dessert_description": False,
            "pending_drink_id": False, "pending_drink_description": False,
            "state": "active",
            "fulfillment_state": "to_prepare",
        })
        record.invalidate_recordset()
        return record

    def test_views_rename_atender_to_editar_and_remove_elaborar_from_pedidos(self):
        views = self.env["lafija.reservation"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.reservation_list").id, "list"],
             [self.env.ref("kai_viandas.reservation_form").id, "form"]]
        )
        list_arch = etree.fromstring(views["views"]["list"]["arch"].encode())
        buttons = list_arch.xpath("//button[@name='action_correct']")
        self.assertTrue(buttons)
        self.assertEqual(buttons[0].get("invisible"), "not pending")
        self.assertEqual(buttons[0].get("string"), "Editar")
        self.assertFalse(list_arch.xpath("//button[@name='action_elaborate']"))
        ver = list_arch.xpath("//button[@name='action_open_production']")
        self.assertTrue(ver)
        self.assertEqual(ver[0].get("string"), "Ver orden")
        self.assertTrue(list_arch.xpath("//field[@name='fulfillment_production_ids'][@widget='many2many_tags']"))

        form_arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        form_buttons = form_arch.xpath("//header//button[@name='action_correct']")
        self.assertTrue(form_buttons)
        self.assertEqual(form_buttons[0].get("string"), "Editar")
        self.assertFalse(form_arch.xpath("//header//button[@name='action_elaborate']"))
        form_ver = form_arch.xpath("//header//button[@name='action_open_production']")
        self.assertTrue(form_ver)
        self.assertEqual(form_ver[0].get("string"), "Ver orden")

        wizard_arch = etree.fromstring(self.env.ref("kai_viandas.correction_form").arch.encode())
        self.assertEqual(wizard_arch.get("string"), "Editar pedido")
        action = self.reservation.with_user(self.operator).action_correct()
        self.assertEqual(action.get("name"), "Editar pedido")

        prod = self.env.ref("kai_viandas.lf_day_production_action")
        self.assertEqual(prod.name, "Producción del día")
        self.assertEqual(prod.res_model, "mrp.production")
        self.assertIn("lf_meal_date", prod.domain)
        menu = self.env.ref("kai_viandas.menu_day_production")
        self.assertEqual(menu.parent_id, self.env.ref("kai_viandas.menu_orders_group"))
        self.assertEqual(menu.action, prod)

        help_arch = self.env.ref("kai_viandas.help_operator_content").arch
        self.assertIn("Editar</strong> en la fila solo aparece si requiere atención", help_arch)
        self.assertIn("Producción del día", help_arch)
        self.assertNotIn("Atender / corregir", help_arch)
        self.assertIn("10:30", help_arch)
        self.assertIn("sábado a las 14:00", help_arch)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertEqual(module.latest_version, "19.0.2.0.0")

    def test_defaults_are_saturday_14_and_daily_1030(self):
        self.env["ir.config_parameter"].sudo().search([
            ("key", "in", [
                "kai_viandas.daily_cutoff",
                "kai_viandas.weekly_close_weekday",
                "kai_viandas.weekly_close_time",
            ]),
        ]).unlink()
        self.assertEqual(order_windows.weekly_close_weekday(self.env), 5)
        self.assertEqual(order_windows.daily_cutoff_label(self.env), "10:30")
        self.assertEqual(self.menu._reference_datetime().strftime("%Y-%m-%d %H:%M"), "2026-09-14 13:30")
        self.assertEqual(self.menu._weekly_close_datetime().strftime("%Y-%m-%d %H:%M"), "2026-09-12 17:00")
        with freeze_time("2026-09-14 13:29:59"):
            self.assertTrue(self.menu._employee_window_open())
        with freeze_time("2026-09-14 13:30:00"):
            self.assertFalse(self.menu._employee_window_open())
            self.assertIn("10:30", self.menu._employee_window_message())

    def test_weekly_window_closes_saturday_1400_and_reopens_on_menu_week(self):
        with freeze_time("2026-09-11 16:00:00"):
            self.assertTrue(self.menu._employee_window_open())
        with freeze_time("2026-09-12 17:00:00"):
            self.assertFalse(self.menu._employee_window_open())
            self.assertIn("sábado", self.menu._employee_window_message())
            self.assertIn("14:00", self.menu._employee_window_message())
        with freeze_time("2026-09-13 15:00:00"):
            self.assertEqual(self.menu._employee_window_state(), "weekly_closed")
        with freeze_time("2026-09-14 12:00:00"):
            self.assertTrue(self.menu._employee_window_open())

    def test_future_week_is_closed_until_the_advance_week(self):
        later = self.env["lafija.menu.day"].with_user(self.operator).create({
            "date": "2026-09-21", "website_id": self.website.id,
            "product_ids": [Command.set(self.menu.product_ids.ids)],
        })
        later.with_user(self.operator).action_publish()
        with freeze_time("2026-09-08 15:00:00"):
            self.assertEqual(later._employee_window_state(), "future_week_closed")
            self.assertIn("semana anterior", later._employee_window_message())
        with freeze_time("2026-09-14 15:00:00"):
            self.assertTrue(later._employee_window_open())

    def test_cutoffs_are_configurable(self):
        wizard = self.env["lafija.order.window.settings"].with_user(self.operator).create({})
        self.assertEqual(wizard.lf_daily_cutoff, "10:30")
        self.assertEqual(wizard.lf_weekly_close_weekday, "5")
        self.assertEqual(wizard.lf_weekly_close_time, "14:00")
        wizard.write({"lf_daily_cutoff": "11:00", "lf_weekly_close_time": "13:00"})
        wizard.action_save()
        self.assertEqual(self.menu._reference_datetime().strftime("%H:%M"), "14:00")
        with freeze_time("2026-09-14 13:45:00"):
            self.assertTrue(self.menu._employee_window_open())
        with freeze_time("2026-09-14 14:00:00"):
            self.assertFalse(self.menu._employee_window_open())
            self.assertIn("11:00", self.menu._employee_window_message())
        self.assertEqual(self.menu._weekly_close_datetime().strftime("%Y-%m-%d %H:%M"), "2026-09-12 16:00")

    def test_employee_cannot_change_after_1030_operator_can(self):
        self.assertEqual(self.reservation.sudo().current_product_id, self.chicken)
        with freeze_time("2026-09-14 13:31:00"):
            with self.assertRaises(OrderWindowClosed) as error:
                self.service._submit_selections(self.website, [(self.menu.id, self.pork.id)])
            self.assertIn("10:30", str(error.exception))
            self.assertEqual(self.reservation.sudo().current_product_id, self.chicken)
            self.env["lafija.reservation"].with_user(self.operator)._submit_selections(
                self.website, [(self.menu.id, self.pork.id)], employee=self.employee)
        self.reservation.invalidate_recordset()
        self.assertEqual(self.reservation.sudo().current_product_id, self.pork)
        self.assertFalse(self.reservation.sudo().pending_product_id)

    def test_vigente_adds_to_draft_mo_and_two_companies_share_one_order(self):
        plate = self._goods_plate("Pollo 1177 auto")
        self.menu.with_user(self.operator).write({"product_ids": [(4, plate.id)]})
        self.service._submit_selections(self.website, [(self.menu.id, plate.id)])
        first = self.reservation.sudo()
        first.invalidate_recordset()
        mo = first.fulfillment_production_ids.filtered(lambda production: production.state == "draft")
        self.assertEqual(len(mo), 1)
        self.assertEqual(mo.product_id, plate)
        self.assertEqual(mo.product_qty, 1)
        self.assertEqual(mo.lf_meal_date, first.date)

        other, _company = self._other_company_employee("lf1177-mo")
        self.env["lafija.reservation"].with_user(other)._submit_selections(
            self.website, [(self.menu.id, plate.id)])
        second = self.env["lafija.reservation"].search([
            ("employee_partner_id.user_ids", "in", other.id),
            ("menu_id", "=", self.menu.id),
        ], limit=1)
        second.invalidate_recordset()
        first.invalidate_recordset()
        shared = first.fulfillment_production_ids.filtered(lambda production: production.state == "draft")
        self.assertEqual(shared, second.fulfillment_production_ids.filtered(lambda production: production.state == "draft"))
        self.assertEqual(shared.product_qty, 2)
        self.assertEqual(set(shared.lf_reservation_ids.ids), {first.id, second.id})

    def test_dish_change_moves_qty_and_cancel_decreases_draft(self):
        first = self._goods_plate("Milanesa 1177 move")
        second = self._goods_plate("Tarta 1177 move")
        self.menu.with_user(self.operator).write({"product_ids": [(4, first.id), (4, second.id)]})
        self.service._submit_selections(self.website, [(self.menu.id, first.id)])
        reservation = self.reservation.sudo()
        chicken_mo = reservation.fulfillment_production_ids.filtered(
            lambda production: production.product_id == first and production.state == "draft")
        self.assertEqual(chicken_mo.product_qty, 1)
        self.service._submit_selections(self.website, [(self.menu.id, second.id)])
        reservation.invalidate_recordset()
        self.assertEqual(reservation.current_product_id, second)
        self.assertFalse(reservation.fulfillment_production_ids.filtered(
            lambda production: production.product_id == first and production.state == "draft"))
        tart_mo = reservation.fulfillment_production_ids.filtered(
            lambda production: production.product_id == second and production.state == "draft")
        self.assertEqual(tart_mo.product_qty, 1)
        self._resolve("cancel")
        reservation.invalidate_recordset()
        self.assertEqual(reservation.state, "cancelled")
        self.assertFalse(tart_mo.exists() and tart_mo.state == "draft" and reservation in tart_mo.lf_reservation_ids)

    def test_confirmed_mo_remainder_logs_removal_and_new_addition_goes_to_draft(self):
        plate = self._goods_plate("Guiso 1177 conf")
        other = self._goods_plate("Ensalada 1177 conf")
        self.menu.with_user(self.operator).write({"product_ids": [(4, plate.id), (4, other.id)]})
        self.service._submit_selections(self.website, [(self.menu.id, plate.id)])
        reservation = self.reservation.sudo()
        mo = reservation.fulfillment_production_ids.filtered(lambda production: production.state == "draft")
        mo.action_confirm()
        reservation.invalidate_recordset()
        self.assertEqual(reservation.fulfillment_state, "in_progress")
        qty = mo.product_qty
        self.service._submit_selections(self.website, [(self.menu.id, other.id)])
        reservation.invalidate_recordset()
        self.assertEqual(reservation.current_product_id, other)
        self.assertEqual(reservation.fulfillment_state, "to_prepare")
        self.assertFalse(reservation in mo.lf_reservation_ids)
        self.assertEqual(mo.state, "confirmed")
        self.assertEqual(mo.product_qty, qty)
        self.assertTrue(any("V-" in (message.body or "") or "desvincul" in (message.body or "").lower()
                            for message in mo.message_ids))
        draft = reservation.fulfillment_production_ids.filtered(
            lambda production: production.product_id == other and production.state == "draft")
        self.assertTrue(draft)
        self.assertEqual(draft.product_qty, 1)

    def test_edit_accept_pending_adds_to_draft_mo(self):
        plate = self._goods_plate("Cerdo 1177 editar")
        self.menu.with_user(self.operator).write({"product_ids": [(4, plate.id)]})
        self._force_pending(self.reservation, plate)
        reservation = self.reservation.sudo()
        self.assertFalse(reservation.current_product_id)
        self.assertEqual(reservation.pending_product_id, plate)
        self._resolve("accept")
        reservation.invalidate_recordset()
        reservation.invalidate_recordset()
        self.assertEqual(reservation.current_product_id, plate)
        self.assertFalse(reservation.pending_product_id)
        mo = reservation.fulfillment_production_ids.filtered(lambda production: production.state == "draft")
        self.assertEqual(len(mo), 1)
        self.assertEqual(mo.product_id, plate)
        self.assertEqual(mo.product_qty, 1)
        self.assertEqual(reservation.fulfillment_state, "to_prepare")

    def test_employee_change_before_1030_after_list_applies_as_current(self):
        plate = self._goods_plate("Pollo 1177 corte")
        other = self._goods_plate("Cerdo 1177 corte")
        self.menu.with_user(self.operator).write({"product_ids": [(4, plate.id), (4, other.id)]})
        self.service._submit_selections(self.website, [(self.menu.id, plate.id)])
        self._take()
        reservation = self.reservation.sudo()
        with freeze_time("2026-09-14 13:20:00"):
            self.service._submit_selections(self.website, [(self.menu.id, other.id)])
        reservation.invalidate_recordset()
        self.assertEqual(reservation.current_product_id, other)
        self.assertFalse(reservation.pending_product_id)
        drafts = reservation.fulfillment_production_ids.filtered(lambda production: production.state == "draft")
        self.assertEqual(drafts.product_id, other)
