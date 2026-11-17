from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, tagged

from .test_preparation import PreparationCommon
from .test_release_112 import SidesCommon


@tagged("post_install", "-at_install")
class TestRelease113(SidesCommon):
    def _wizard(self, employee, **values):
        return self.env["lafija.employee.order"].with_user(self.operator).create({
            "customer_company_id": self.customer.id,
            "employee_id": employee.partner_id.id,
            **values,
        })

    def test_hoy_button_opens_employee_order_wizard_for_the_operator(self):
        missing = self.env["ir.model.data"].sudo().search([
            ("module", "=", "kai_viandas"),
            ("name", "=", "menu_employee_order"),
        ])
        self.assertFalse(missing)
        action = self.env.ref("kai_viandas.employee_order_action")
        opened = self.env["lafija.reservation"].with_user(self.operator).action_create_client_orders()
        self.assertEqual(opened["id"], action.id)
        self.assertEqual(opened["res_model"], "lafija.employee.order")
        employee, _ = self._create_employee("abc-order-menu")
        with self.assertRaises(AccessError):
            self.env["lafija.employee.order"].with_user(employee).create({
                "customer_company_id": self.customer.id,
                "employee_id": employee.partner_id.id,
            })

    def test_operator_loads_week_for_employee_with_operator_origin(self):
        employee, _ = self._create_employee("abc-order-load")
        wizard = self._wizard(employee)
        self.assertEqual(wizard.week_start, fields.Date.to_date("2026-09-14"))
        self.assertEqual(wizard.line_ids.mapped("date"), self.menus.mapped("date"))
        monday = wizard.line_ids.filtered(lambda line: line.date == fields.Date.to_date("2026-09-14"))
        tuesday = wizard.line_ids.filtered(lambda line: line.date == fields.Date.to_date("2026-09-15"))
        monday.write({"product_id": self.chicken.id, "dessert_id": self.flan.id, "drink_id": self.water.id})
        tuesday.write({"product_id": self.pork.id, "dessert_id": False, "drink_id": self.soda.id})
        wizard.action_confirm()
        records = self.env["lafija.reservation"].sudo().search([
            ("employee_partner_id", "=", employee.partner_id.id),
        ], order="date")
        self.assertEqual(records.mapped("date"), [fields.Date.to_date("2026-09-14"), fields.Date.to_date("2026-09-15")])
        monday_res = records[0]
        self.assertEqual((monday_res.current_product_id, monday_res.current_dessert_id, monday_res.current_drink_id),
                         (self.chicken, self.flan, self.water))
        self.assertEqual(monday_res.event_ids[-1].actor_id, self.operator)
        self.assertIn("Cargado por operador", monday_res.event_ids[-1].result)
        self.assertTrue(monday_res.message_ids.filtered(lambda m: "Cargado por operador" in (m.body or "")))
        self.assertEqual(records[1].current_product_id, self.pork)
        self.assertFalse(records[1].current_dessert_id)
        self.assertEqual(records[1].current_drink_id, self.soda)

    def test_preloads_existing_reservation_and_skips_a_day_without_plate(self):
        employee, _ = self._create_employee("abc-order-preload")
        self.env["lafija.reservation"].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.chicken.id, self.flan.id, self.water.id)])
        wizard = self._wizard(employee)
        monday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[0])
        self.assertEqual((monday.product_id, monday.dessert_id, monday.drink_id),
                         (self.chicken, self.flan, self.water))
        self.assertIn("Pollo", monday.current_label or "")
        monday.product_id = False
        monday.dessert_id = False
        monday.drink_id = False
        tuesday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[1])
        tuesday.product_id = self.pork
        wizard.action_confirm()
        existing = self.env["lafija.reservation"].sudo().search([
            ("employee_partner_id", "=", employee.partner_id.id), ("menu_id", "=", self.menus[0].id)])
        self.assertEqual(existing.current_product_id, self.chicken)
        self.assertEqual(existing.current_dessert_id, self.flan)
        created = self.env["lafija.reservation"].sudo().search([
            ("employee_partner_id", "=", employee.partner_id.id), ("menu_id", "=", self.menus[1].id)])
        self.assertEqual(created.current_product_id, self.pork)

    def test_dessert_or_drink_without_plate_is_rejected(self):
        employee, _ = self._create_employee("abc-order-sides")
        wizard = self._wizard(employee)
        monday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[0])
        monday.write({"product_id": False, "dessert_id": self.flan.id, "drink_id": False})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.action_confirm()

    def test_employee_must_belong_to_the_selected_company(self):
        employee, _ = self._create_employee("abc-order-company")
        other = self.env["res.partner"].create({"name": "Otra empresa 113", "is_company": True})
        with self.assertRaises(ValidationError):
            self.env["lafija.employee.order"].with_user(self.operator).create({
                "customer_company_id": other.id,
                "employee_id": employee.partner_id.id,
            })

    def test_week_navigation_rebuilds_the_days(self):
        employee, _ = self._create_employee("abc-order-week")
        later = self.env["lafija.menu.day"].with_user(self.operator).create({
            "date": "2026-09-21", "website_id": self.website.id, "published": True,
            "product_ids": [(6, 0, self.chicken.ids)],
            "dessert_ids": [(6, 0, self.flan.ids)],
            "drink_ids": [(6, 0, self.water.ids)],
        })
        wizard = self._wizard(employee)
        self.assertEqual(wizard.week_start, fields.Date.to_date("2026-09-14"))
        wizard.action_next_week()
        self.assertEqual(wizard.week_start, fields.Date.to_date("2026-09-21"))
        self.assertEqual(wizard.line_ids.menu_id, later)
        wizard.action_previous_week()
        self.assertEqual(wizard.week_start, fields.Date.to_date("2026-09-14"))
        self.assertEqual(set(wizard.line_ids.menu_id.ids), set(self.menus.ids))


    def test_saving_keeps_choices_and_form_can_be_confirmed_again(self):
        employee, _ = self._create_employee("abc-order-resave")
        week = fields.Date.to_date("2026-09-14")
        wizard = self.env["lafija.employee.order"].with_user(self.operator).create({
            "customer_company_id": self.customer.id,
            "employee_id": employee.partner_id.id,
            "week_start": week,
            "line_ids": [(0, 0, {
                "menu_id": self.menus[0].id, "date": self.menus[0].date, "date_label": "Lunes 14/09",
                "product_id": self.chicken.id, "dessert_id": self.flan.id, "drink_id": self.water.id,
            })],
        })
        monday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[0])
        self.assertEqual((monday.product_id, monday.dessert_id, monday.drink_id),
                         (self.chicken, self.flan, self.water))
        result = wizard.action_confirm()
        self.assertEqual(result["params"]["next"]["res_id"], wizard.id)
        monday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[0])
        self.assertEqual((monday.product_id, monday.dessert_id, monday.drink_id),
                         (self.chicken, self.flan, self.water))
        self.assertTrue(monday.reservation_id)
        self.assertIn("Pollo", monday.current_label)
        record = monday.reservation_id
        wizard.action_confirm()
        self.assertEqual(record.current_product_id, self.chicken)
        monday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[0])
        monday.write({"product_id": self.pork.id, "dessert_id": False, "drink_id": self.soda.id})
        wizard.action_confirm()
        record.invalidate_recordset()
        self.assertEqual((record.current_product_id, record.current_dessert_id, record.current_drink_id),
                         (self.pork, self.env["product.product"], self.soda))
        monday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[0])
        self.assertEqual((monday.product_id, monday.dessert_id, monday.drink_id),
                         (self.pork, self.env["product.product"], self.soda))

    def _wizard_spec(self):
        return {
            "customer_company_id": {"fields": {"display_name": {}}},
            "employee_id": {"fields": {"display_name": {}}},
            "week_start": {},
            "week_label": {},
            "notice": {},
            "line_ids": {"fields": {
                "menu_id": {"fields": {"display_name": {}}, "context": {"lf_day_label": 1}},
                "date": {},
                "date_label": {},
                "product_id": {"fields": {"display_name": {}}},
                "dessert_id": {"fields": {"display_name": {}}},
                "drink_id": {"fields": {"display_name": {}}},
                "current_label": {},
                "reservation_id": {"fields": {"display_name": {}}},
                "past": {},
                "after_cut": {},
            }},
        }


    def _many2one_id(self, value):
        if not value:
            return False
        if isinstance(value, dict):
            return value.get("id")
        if isinstance(value, (list, tuple)):
            return value[0]
        return value

    def _many2one_name(self, value):
        if not value:
            return ""
        if isinstance(value, dict):
            return value.get("display_name") or ""
        if isinstance(value, (list, tuple)) and len(value) > 1:
            return value[1] or ""
        return ""

    def test_list_view_allows_adding_and_removing_lines(self):
        views = self.env["lafija.employee.order"].with_user(self.operator).get_views(
            [[self.env.ref("kai_viandas.employee_order_form").id, "form"]])
        arch = etree.fromstring(views["views"]["form"]["arch"].encode())
        listing = arch.xpath("//field[@name='line_ids']/list")[0]
        self.assertEqual(listing.get("editable"), "bottom")
        self.assertNotEqual(listing.get("create"), "0")
        self.assertNotEqual(listing.get("delete"), "0")
        self.assertTrue(listing.xpath("./field[@name='menu_id']"))
        self.assertNotEqual(listing.xpath("./field[@name='menu_id']")[0].get("column_invisible"), "1")

    def test_web_save_applies_reservation_and_returns_day_and_current_label(self):
        employee, _ = self._create_employee("abc-order-websave")
        # Como el cliente: web_save sin date_label ni current_label (son readonly/computados).
        rows = self.env["lafija.employee.order"].with_user(self.operator).web_save({
            "customer_company_id": self.customer.id,
            "employee_id": employee.partner_id.id,
            "week_start": "2026-09-14",
            "line_ids": [
                Command.create({
                    "menu_id": self.menus[0].id,
                    "product_id": self.chicken.id,
                    "dessert_id": self.flan.id,
                    "drink_id": self.water.id,
                }),
                Command.create({
                    "menu_id": self.menus[1].id,
                    "product_id": self.pork.id,
                }),
            ],
        }, self._wizard_spec())
        lines = rows[0]["line_ids"]
        by_menu = {self._many2one_id(line["menu_id"]): line for line in lines}
        monday = by_menu[self.menus[0].id]
        tuesday = by_menu[self.menus[1].id]
        self.assertEqual(monday["date_label"], "Lunes 14/09")
        self.assertIn("Lunes", self._many2one_name(monday["menu_id"]))
        self.assertTrue(monday["current_label"])
        self.assertIn("Pollo", monday["current_label"])
        self.assertTrue(monday["reservation_id"])
        self.assertEqual(tuesday["date_label"], "Martes 15/09")
        self.assertIn("Cerdo", tuesday["current_label"] or "")
        # Releer el formulario como al reabrir.
        reread = self.env["lafija.employee.order"].browse(rows[0]["id"]).with_user(self.operator).web_read(self._wizard_spec())[0]
        monday = next(line for line in reread["line_ids"] if self._many2one_id(line["menu_id"]) == self.menus[0].id)
        self.assertEqual(monday["date_label"], "Lunes 14/09")
        self.assertIn("Pollo", monday["current_label"])
        records = self.env["lafija.reservation"].sudo().search([
            ("employee_partner_id", "=", employee.partner_id.id),
        ], order="date")
        self.assertEqual(records.mapped("date"), [fields.Date.to_date("2026-09-14"), fields.Date.to_date("2026-09-15")])
        self.assertEqual(
            (records[0].current_product_id, records[0].current_dessert_id, records[0].current_drink_id),
            (self.chicken, self.flan, self.water),
        )
        self.assertEqual(records[1].current_product_id, self.pork)

    def test_form_add_line_and_delete_line_does_not_touch_existing_reservation(self):
        employee, _ = self._create_employee("abc-order-addline")
        self.env["lafija.reservation"].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.chicken.id, self.flan.id, self.water.id)])
        form = Form(self.env["lafija.employee.order"].with_user(self.operator), view="kai_viandas.employee_order_form")
        form.customer_company_id = self.customer
        form.employee_id = employee.partner_id
        # Quitar el martes precargado (2.º renglón: 14 al 18/09) y volver a agregarlo a mano.
        form.line_ids.remove(1)
        with form.line_ids.new() as line:
            line.menu_id = self.menus[1]
            line.product_id = self.pork
        wizard = form.save()
        tuesday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[1])
        self.assertEqual(tuesday.date_label, "Martes 15/09")
        self.assertEqual(tuesday.product_id, self.pork)
        # Confirmar el martes; el lunes (reserva previa) no se toca aunque también esté en la grilla.
        monday_before = self.env["lafija.reservation"].sudo().search([
            ("employee_partner_id", "=", employee.partner_id.id), ("menu_id", "=", self.menus[0].id)])
        event_before = monday_before.event_ids[-1:].id
        wizard.action_confirm()
        monday_after = monday_before.sudo()
        self.assertEqual(monday_after.current_product_id, self.chicken)
        self.assertEqual(monday_after.event_ids[-1:].id, event_before)
        created = self.env["lafija.reservation"].sudo().search([
            ("employee_partner_id", "=", employee.partner_id.id), ("menu_id", "=", self.menus[1].id)])
        self.assertEqual(created.current_product_id, self.pork)
        tuesday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[1])
        self.assertEqual(tuesday.date_label, "Martes 15/09")
        self.assertIn("Cerdo", tuesday.current_label or "")

    def test_deleting_a_line_before_confirm_does_not_cancel_existing_reservation(self):
        employee, _ = self._create_employee("abc-order-delline")
        self.env["lafija.reservation"].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.chicken.id, False, False)])
        wizard = self._wizard(employee)
        monday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[0])
        monday.unlink()
        tuesday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[1])
        tuesday.product_id = self.pork
        wizard.action_confirm()
        existing = self.env["lafija.reservation"].sudo().search([
            ("employee_partner_id", "=", employee.partner_id.id), ("menu_id", "=", self.menus[0].id)])
        self.assertEqual(existing.state, "active")
        self.assertEqual(existing.current_product_id, self.chicken)
        # Después de guardar, la precarga vuelve a mostrar el lunes con lo vigente.
        monday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menus[0])
        self.assertEqual(monday.date_label, "Lunes 14/09")
        self.assertIn("Pollo", monday.current_label or "")


    def test_unsaved_new_line_has_no_days_when_all_published_are_already_listed(self):
        employee, _ = self._create_employee("abc-order-nodays")
        wizard = self.env["lafija.employee.order"].with_user(self.operator).new({
            "customer_company_id": self.customer.id,
            "employee_id": employee.partner_id.id,
            "week_start": "2026-09-14",
        })
        wizard.line_ids = [Command.create(values) for values in wizard._line_values_for_week(
            wizard.employee_id, wizard.week_start)]
        self.assertFalse(wizard.can_add_line)
        wizard.line_ids = [Command.create({})]
        empty = wizard.line_ids.filtered(lambda line: not line.menu_id)
        self.assertTrue(empty)
        self.assertFalse(empty.available_menu_ids)
        found = self.env["lafija.menu.day"].with_context(lf_day_label=1).with_user(self.operator).name_search(
            "", [("id", "in", empty.available_menu_ids.ids)], operator="ilike", limit=16)
        self.assertFalse(found)

    def test_unsaved_new_line_name_search_returns_the_unused_published_day(self):
        employee, _ = self._create_employee("abc-order-extraday")
        wizard = self.env["lafija.employee.order"].with_user(self.operator).new({
            "customer_company_id": self.customer.id,
            "employee_id": employee.partner_id.id,
            "week_start": "2026-09-14",
        })
        values = wizard._line_values_for_week(wizard.employee_id, wizard.week_start)
        # Deja el martes afuera, como si no estuviera en la grilla o se hubiera quitado.
        values = [line for line in values if line["menu_id"] != self.menus[1].id]
        wizard.line_ids = [Command.create(line) for line in values]
        self.assertTrue(wizard.can_add_line)
        wizard.line_ids = [Command.create({})]
        empty = wizard.line_ids.filtered(lambda line: not line.menu_id)
        available_ids = empty.available_menu_ids._origin.ids or empty.available_menu_ids.ids
        self.assertEqual(available_ids, self.menus[1].ids)
        found = self.env["lafija.menu.day"].with_context(lf_day_label=1).with_user(self.operator).name_search(
            "", [("id", "in", available_ids)], operator="ilike", limit=16)
        self.assertEqual([row[0] for row in found], self.menus[1].ids)
        self.assertIn("Martes", found[0][1])

    def test_onchange_employee_sets_can_add_line_when_the_week_is_complete(self):
        employee, _ = self._create_employee("abc-order-onchange-notice")
        result = self.env["lafija.employee.order"].with_user(self.operator).onchange(
            {"customer_company_id": self.customer.id, "employee_id": employee.partner_id.id},
            ["employee_id"],
            {
                "customer_company_id": {},
                "employee_id": {},
                "website_id": {},
                "week_start": {},
                "can_add_line": {},
                "line_ids": {"fields": {"menu_id": {}, "available_menu_ids": {}}},
            },
        )
        value = result.get("value") or {}
        self.assertFalse(value.get("can_add_line"))


@tagged("post_install", "-at_install")
class TestRelease113Cut(SidesCommon, PreparationCommon):
    def test_change_after_cut_pends_the_whole_triple_and_keeps_operator_origin(self):
        self._take()
        wizard = self.env["lafija.employee.order"].with_user(self.operator).create({
            "customer_company_id": self.customer.id,
            "employee_id": self.employee.partner_id.id,
        })
        monday = wizard.line_ids.filtered(lambda line: line.menu_id == self.menu)
        self.assertEqual(monday.product_id, self.chicken)
        monday.write({"product_id": self.pork.id, "dessert_id": self.brownie.id, "drink_id": self.water.id})
        wizard.action_confirm()
        record = self.reservation.sudo()
        self.assertEqual(record.current_product_id, self.chicken)
        self.assertFalse(record.current_dessert_id)
        self.assertEqual(record.pending_product_id, self.pork)
        self.assertEqual(record.pending_dessert_id, self.brownie)
        self.assertEqual(record.pending_drink_id, self.water)
        self.assertIn("Cargado por operador", record.event_ids[-1].result)
        self.assertEqual(record.event_ids[-1].actor_id, self.operator)
