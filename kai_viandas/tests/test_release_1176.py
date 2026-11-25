"""Presupuesto explícito después de elaborar · 19.0.1.17.6."""
from pathlib import Path
from lxml import etree
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from ..models.reservation import operation_context
from .test_preparation import PreparationCommon
from .test_release_112 import SidesCommon
from .test_release_114 import TestRelease114


@tagged("post_install", "-at_install")
class TestRelease1176(SidesCommon, PreparationCommon):
    def _lines(self, order):
        return order.order_line.filtered(lambda line: not line.display_type and line.product_uom_qty)

    def _goods_plate(self, name):
        return TestRelease114._goods_plate(self, name)

    def _reservation(self):
        return self.reservation.with_user(self.operator)

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

    def _mark_prepared(self, reservations):
        reservations.sudo().with_context(**operation_context()).write({"fulfillment_state": "prepared"})

    def test_views_show_add_button_only_when_elaborated_and_not_added(self):
        views = self.env["lafija.reservation"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.reservation_list").id, "list"],
             [self.env.ref("kai_viandas.reservation_form").id, "form"]]
        )
        list_arch = etree.fromstring(views["views"]["list"]["arch"].encode())
        header = list_arch.xpath("//header/button[@name='action_add_to_quotation']")
        self.assertTrue(header)
        self.assertEqual(header[0].get("string"), "Agregar a presupuesto")
        row = list_arch.xpath("//list/button[@name='action_add_to_quotation']")
        self.assertTrue(row)
        self.assertIn("prepared", row[0].get("invisible"))
        self.assertIn("lf_quotation_id", row[0].get("invisible"))
        presupuesto = list_arch.xpath("//field[@name='lf_quotation_id']")
        self.assertTrue(presupuesto)
        self.assertEqual(presupuesto[0].get("string"), "Presupuesto")
        self.assertEqual(presupuesto[0].get("widget"), "lf_quotation_link")
        self.assertNotEqual(presupuesto[0].get("column_invisible"), "True")

        form_arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        form_btn = form_arch.xpath("//header//button[@name='action_add_to_quotation']")
        self.assertTrue(form_btn)
        self.assertIn("prepared", form_btn[0].get("invisible"))

        help_arch = self.env.ref("kai_viandas.help_operator_content").arch
        self.assertIn("Agregar a presupuesto", help_arch)
        self.assertIn("un presupuesto en borrador por empresa y día", help_arch)
        self.assertIn("columna <strong>Monto</strong>", help_arch)
        self.assertIn("Pedidos → Ventas", help_arch)
        self.assertIn("Nuevo pedido", help_arch)

        from odoo.modules.module import get_module_path
        js = (Path(get_module_path("kai_viandas")) / "static" / "src" / "reservation_list.js").read_text()
        self.assertIn('LINK_LABEL = "Nuevo pedido"', js)
        self.assertIn("default_customer_company_id", js)
        self.assertIn("default_date", js)
        self.assertIn('scopeName: "day"', js)
        self.assertIn('scopeName: "company"', js)
        self.assertIn('scopeName: "list"', js)

        module = self.env["ir.module.module"].search([("name", "=", "kai_viandas")], limit=1)
        self.assertTrue(module.latest_version.startswith("19.0.2."), module.latest_version)

    def test_no_automatic_quotation_on_confirm_or_elaborate_or_take_list(self):
        self.assertFalse(self.reservation._lf_daily_orders())
        self.assertFalse(self.reservation.sudo().lf_quotation_id)
        self.assertEqual(self.reservation.sudo().lf_amount, 0)
        self.service._submit_selections(
            self.website, [(self.menu.id, self.chicken.id, self.flan.id, self.water.id)])
        self.assertFalse(self.reservation._lf_daily_orders())
        cut = self._take()
        self.assertFalse(self.reservation._lf_daily_orders())
        self.reservation.with_user(self.operator).action_elaborate()
        self.assertFalse(self.reservation._lf_daily_orders())
        self.assertEqual(cut, self.menu.cut_ids[:1])

        with self.assertRaises(ValidationError):
            self.reservation.with_user(self.operator).action_add_to_quotation()

    def test_add_to_quotation_builds_draft_by_company_and_shows_amount(self):
        self.flan.list_price = 2800
        self.water.list_price = 1800
        self.service._submit_selections(
            self.website, [(self.menu.id, self.chicken.id, self.flan.id, self.water.id)])
        self._take()
        self._mark_prepared(self.reservation)
        before = self.env["sale.order"].search_count([])
        self.reservation.with_user(self.operator).action_add_to_quotation()
        order = self.reservation._lf_daily_orders()
        self.assertEqual(len(order), 1)
        self.assertEqual(order.state, "draft")
        self.assertEqual(order.partner_id, self.customer)
        self.assertEqual(order.lf_preparation_date, self.reservation.date)
        self.assertEqual(self.env["sale.order"].search_count([]), before + 1)
        self.assertEqual(self.reservation.sudo().lf_quotation_id, order)
        self.assertTrue(self.reservation.sudo().lf_quotation_added)
        lines = self._lines(order)
        self.assertEqual(set(lines.product_id.ids), {self.chicken.id, self.flan.id, self.water.id})
        self.assertAlmostEqual(lines.filtered(lambda line: line.product_id == self.flan).price_unit, 2800, places=2)
        self.assertAlmostEqual(lines.filtered(lambda line: line.product_id == self.water).price_unit, 1800, places=2)
        expected = sum(lines.mapped("price_unit"))
        self.assertAlmostEqual(self.reservation.sudo().lf_amount, expected, places=2)

        # Reagregar no duplica el presupuesto.
        self.reservation.with_user(self.operator).action_add_to_quotation()
        self.assertEqual(self.reservation._lf_daily_orders(), order)
        self.assertEqual(order.state, "draft")

        # Un cambio o una cancelación de una vianda ya agregada ajusta el borrador.
        self.env["lafija.reservation.correction"].with_user(self.operator).create({
            "reservation_id": self.reservation.id,
            "operation": "replace",
            "reason": "Cambio de plato 1176",
            "product_id": self.pork.id,
            "dessert_id": self.flan.id,
            "drink_id": self.water.id,
        }).action_apply()
        # Tras el cambio vuelve a Por elaborar: sigue en el presupuesto y se ajustan las líneas.
        order = self.reservation._lf_daily_orders()
        self.assertEqual(len(order), 1)
        lines = self._lines(order)
        self.assertIn(self.pork, lines.product_id)
        self.assertNotIn(self.chicken, lines.product_id)

    def test_multi_company_selection_groups_mo_by_dish_and_quotation_by_company(self):
        salad = self._goods_plate("Ensalada 1176")
        merluza = self._goods_plate("Merluza 1176")
        self.menu.with_user(self.operator).write({
            "product_ids": [Command.link(salad.id), Command.link(merluza.id)],
        })
        self._resolve("replace", product_id=salad.id)
        first = self._reservation()
        employee_a, company_a = self._other_company_employee("lf1176-a")
        self.env["lafija.reservation"].with_user(employee_a)._submit_selections(
            self.website, [(self.menu.id, salad.id)])
        second = self.env["lafija.reservation"].search([
            ("employee_partner_id.user_ids", "in", employee_a.id),
            ("menu_id", "=", self.menu.id),
        ], limit=1)
        employee_b, company_b = self._other_company_employee("lf1176-b")
        self.env["lafija.reservation"].with_user(employee_b)._submit_selections(
            self.website, [(self.menu.id, merluza.id)])
        third = self.env["lafija.reservation"].search([
            ("employee_partner_id.user_ids", "in", employee_b.id),
            ("menu_id", "=", self.menu.id),
        ], limit=1)
        self.assertNotEqual(first.customer_company_id, company_a)
        self.assertNotEqual(company_a, company_b)

        selected = (first | second | third).with_user(self.operator)
        selected.action_elaborate()
        first.invalidate_recordset()
        second.invalidate_recordset()
        third.invalidate_recordset()
        salad_mo = (first | second).fulfillment_production_ids.filtered(lambda mo: mo.state != "cancel")
        merluza_mo = third.fulfillment_production_ids.filtered(lambda mo: mo.state != "cancel")
        self.assertEqual(len(salad_mo), 1)
        self.assertEqual(salad_mo, first.fulfillment_production_ids)
        self.assertEqual(salad_mo, second.fulfillment_production_ids)
        self.assertEqual(salad_mo.product_qty, 2)
        self.assertEqual(salad_mo.product_id, salad)
        self.assertEqual(len(merluza_mo), 1)
        self.assertEqual(merluza_mo.product_qty, 1)
        self.assertNotEqual(salad_mo, merluza_mo)
        self.assertFalse(first._lf_daily_orders())
        self.assertFalse(second._lf_daily_orders())
        self.assertFalse(third._lf_daily_orders())

        for mo in salad_mo | merluza_mo:
            for move in mo.move_raw_ids:
                if "quantity" in move._fields:
                    move.quantity = move.product_uom_qty
                else:
                    move.quantity_done = move.product_uom_qty
            mo.sudo().button_mark_done()
        self.assertEqual(first.fulfillment_state, "prepared")
        self.assertEqual(second.fulfillment_state, "prepared")
        self.assertEqual(third.fulfillment_state, "prepared")

        # Primera y segunda (mismo plato, distintas empresas): una OF y dos presupuestos.
        # Para acumular cantidad en el presupuesto, una segunda vianda de la misma empresa.
        extra, _ = self._create_employee("lf1176-extra")
        self.env["lafija.reservation"].with_user(extra)._submit_selections(
            self.website, [(self.menu.id, salad.id)])
        fourth = self.env["lafija.reservation"].search([
            ("employee_partner_id", "=", extra.partner_id.id),
            ("menu_id", "=", self.menu.id),
        ], limit=1)
        self.assertTrue(fourth)
        self.assertEqual(fourth.customer_company_id, first.customer_company_id)
        if not fourth.current_product_id:
            # Después de tomar la lista, el pedido queda pendiente hasta que el operador lo confirme.
            self.env["lafija.reservation.correction"].with_user(self.operator).create({
                "reservation_id": fourth.id,
                "operation": "replace",
                "reason": "Confirmar vianda 1176 misma empresa",
                "product_id": salad.id,
            }).action_apply()
            fourth.invalidate_recordset()
        self.assertEqual(fourth.current_product_id, salad)
        self._mark_prepared(fourth)
        (selected | fourth).with_user(self.operator).action_add_to_quotation()
        first.invalidate_recordset()
        second.invalidate_recordset()
        third.invalidate_recordset()
        fourth.invalidate_recordset()
        order_first = first._lf_daily_orders()
        order_second = second._lf_daily_orders()
        order_third = third._lf_daily_orders()
        self.assertTrue(order_first and order_second and order_third)
        self.assertEqual(order_first.state, "draft")
        self.assertEqual(order_second.state, "draft")
        self.assertEqual(order_third.state, "draft")
        self.assertNotEqual(order_first, order_second)
        self.assertNotEqual(order_second, order_third)
        self.assertNotEqual(order_first, order_third)
        self.assertEqual(order_first.partner_id, first.customer_company_id)
        self.assertEqual(order_second.partner_id, company_a)
        self.assertEqual(order_third.partner_id, company_b)
        self.assertEqual(self._lines(order_first).product_id, salad)
        self.assertEqual(self._lines(order_second).product_id, salad)
        self.assertEqual(self._lines(order_third).product_id, merluza)
        self.assertEqual(self._lines(order_first).product_uom_qty, 2)
        self.assertEqual(self._lines(order_second).product_uom_qty, 1)
        self.assertEqual(self._lines(order_third).product_uom_qty, 1)
        self.assertEqual(fourth._lf_daily_orders(), order_first)

    def test_nuevo_pedido_defaults_company_and_day_week(self):
        from datetime import date
        reservation = self.reservation.sudo()
        day = reservation.date
        week = day - __import__("datetime").timedelta(days=day.weekday())
        company = reservation.customer_company_id
        values = self.env["lafija.employee.order"].with_user(self.operator).with_context(
            default_customer_company_id=company.id,
            default_date=day,
            default_focus_date=day,
        ).default_get(["customer_company_id", "week_start", "focus_date", "employee_id"])
        self.assertEqual(values.get("customer_company_id"), company.id)
        self.assertEqual(values.get("week_start"), week)
        self.assertEqual(values.get("focus_date"), day)
        self.assertFalse(values.get("employee_id"))

        wizard = self.env["lafija.employee.order"].with_user(self.operator).with_context(
            default_customer_company_id=company.id,
            default_date=day,
            default_focus_date=day,
        ).new({
            "customer_company_id": company.id,
            "week_start": week,
            "focus_date": day,
        })
        wizard.employee_id = self.employee.partner_id
        wizard._onchange_employee()
        self.assertEqual(wizard.week_start, week)
        self.assertTrue(wizard.line_ids)
        focused = wizard.line_ids.filtered("is_focus")
        self.assertTrue(focused)
        self.assertEqual(focused.date, day)

