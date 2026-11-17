import json

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .test_identity import LafijaCommon


class ReservationCommon(LafijaCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.ref("base.user_admin").tz = "America/Argentina/Buenos_Aires"
        cls.chicken, cls.pork, cls.fish = cls.env["product.product"].create([
            {"name": name, "description_sale": name, "list_price": price, "type": "consu",
             "categ_id": cls.plate_categ.id, "is_published": False,
             "website_id": cls.env.ref("website.default_website").id}
            for name, price in [("Pollo", 271828.75), ("Cerdo", 314159.25), ("Pescado", 161803.50)]
        ])
        cls.menus = cls.env["lafija.menu.day"].with_user(cls.operator).create([
            {"date": f"2026-09-{day}", "website_id": cls.website.id, "published": True,
             "product_ids": [Command.set([cls.chicken.id, cls.pork.id, cls.fish.id])]}
            for day in range(14, 19)
        ])


@tagged("post_install", "-at_install")
class TestReservation(ReservationCommon):
    def test_week_selection_skips_days_and_does_not_require_native_publication(self):
        employee, _ = self._create_employee()
        with freeze_time("2026-09-08 12:00:00"):
            records = self.env["lafija.reservation"].with_user(employee)._submit_selections(
                self.website, [(self.menus[i].id, self.chicken.id) for i in (0, 1, 3)],
            )
        self.assertEqual([str(day) for day in sorted(records.mapped("date"))], ["2026-09-14", "2026-09-15", "2026-09-17"])
        self.assertEqual(records.sudo().customer_company_id, self.customer)
        self.assertEqual(records.sudo().current_product_id, self.chicken)
        self.assertFalse(self.chicken.is_published)
        self.assertFalse(any(records.mapped("after_reference_time")))
        payload = json.dumps([r._employee_values() for r in records])
        for amount in ("271828.75", "314159.25", "161803.5"):
            self.assertNotIn(amount, payload)

    def test_normal_substitution_keeps_reference_and_event_history(self):
        employee, _ = self._create_employee()
        service = self.env["lafija.reservation"].with_user(employee)
        menu = self.menus[0]
        with freeze_time("2026-09-08 12:00:00"):
            record = service._submit_selections(self.website, [(menu.id, self.chicken.id)])
        reference = record.name
        with freeze_time("2026-09-14 12:30:00"):
            changed = service._submit_selections(self.website, [(menu.id, self.pork.id)])
        self.assertEqual(changed, record)
        self.assertEqual(changed.name, reference)
        self.assertEqual(changed.current_description, "Cerdo")
        self.assertFalse(changed.after_reference_time)
        self.assertEqual(len(record.sudo().event_ids), 2)
        last = record.sudo().event_ids[-1]
        self.assertEqual((last.previous_description, last.received_description, last.applied_description),
                         ("Pollo", "Cerdo", "Cerdo"))
        self.assertEqual(last.actor_id, employee)

    def test_late_before_cut_applies_and_is_detectable(self):
        employee, _ = self._create_employee()
        with freeze_time("2026-09-14 13:02:00"):
            record = self.env["lafija.reservation"].with_user(employee)._submit_selections(
                self.website, [(self.menus[0].id, self.pork.id)],
            )
        self.assertEqual(record.current_description, "Cerdo")
        self.assertTrue(record.after_reference_time)
        self.assertFalse(record.after_preparation_cut)
        self.assertFalse(record.pending)

    def test_wrong_option_and_cross_site_selection_do_not_create_reservation(self):
        employee, _ = self._create_employee()
        other = self.env["product.product"].create({"name": "No pertenece al menú", "type": "consu"})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["lafija.reservation"].with_user(employee)._submit_selections(self.website, [(self.menus[0].id, other.id)])
        with self.assertRaises(AccessError):
            self.env["lafija.reservation"].with_user(self.private)._submit_selections(self.website, [(self.menus[0].id, self.chicken.id)])
        self.assertFalse(self.env["lafija.reservation"].search([]))

    def test_owner_rule_and_server_projection_refuse_another_employee(self):
        employee, _ = self._create_employee()
        other, _ = self._create_employee("abc-other")
        record = self.env["lafija.reservation"].with_user(employee)._submit_selections(self.website, [(self.menus[0].id, self.chicken.id)])
        self.assertFalse(self.env["lafija.reservation"].with_user(other).search([]))
        with self.assertRaises(AccessError):
            record.with_user(other)._employee_values()
        with self.assertRaises(AccessError):
            record.read(["current_product_id"])
        with self.assertRaises(AccessError):
            record.write({"current_description": "Cambio directo"})

    def test_menu_revision_and_selected_description_survive_product_edit(self):
        employee, _ = self._create_employee()
        record = self.env["lafija.reservation"].with_user(employee)._submit_selections(self.website, [(self.menus[0].id, self.chicken.id)])
        menu = self.menus[0]
        old_revision = menu.revision
        self.chicken.description_sale = "Pollo corregido"
        menu.with_user(self.operator).action_refresh_options()
        self.assertEqual(record.current_description, "Pollo")
        self.assertEqual(record.sudo().menu_revision, old_revision)
        self.assertGreater(menu.revision, old_revision)
        self.assertEqual(menu.revision_ids.filtered(lambda r: r.number == old_revision).options[str(self.chicken.id)]["description"], "Pollo")
        with self.assertRaises(AccessError):
            record.sudo().event_ids.unlink()
        with self.assertRaises(AccessError):
            menu.revision_ids.unlink()
