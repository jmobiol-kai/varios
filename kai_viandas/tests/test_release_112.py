from io import BytesIO

from freezegun import freeze_time
from lxml import html
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools.pdf import PdfReader

from .test_pages import PagesCommon
from .test_preparation import PreparationCommon
from .test_reservation import ReservationCommon


class SidesCommon(ReservationCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Category = cls.env["product.category"]
        cls.plate_categ = Category.search([("complete_name", "=", "Viandas")], limit=1) or Category.create({"name": "Viandas"})
        cls.dessert_categ = Category.search([("complete_name", "=", "Postre Vianda")], limit=1) or Category.create({"name": "Postre Vianda"})
        cls.drink_categ = Category.search([("complete_name", "=", "Bebida Vianda")], limit=1) or Category.create({"name": "Bebida Vianda"})
        cls.flan, cls.brownie, cls.water, cls.soda = cls.env["product.product"].create([
            {"name": name, "description_sale": name, "list_price": price, "type": "consu",
             "categ_id": category.id, "sale_ok": True}
            for name, price, category in (
                ("Flan de prueba", 0, cls.dessert_categ),
                ("Brownie de prueba", 0, cls.dessert_categ),
                ("Agua de prueba", 0, cls.drink_categ),
                ("Gaseosa de prueba", 0, cls.drink_categ),
            )
        ])
        cls.chicken.categ_id = cls.plate_categ
        cls.pork.categ_id = cls.plate_categ
        cls.fish.categ_id = cls.plate_categ
        cls.menus.with_user(cls.operator).write({
            "dessert_ids": [Command.set([cls.flan.id, cls.brownie.id])],
            "drink_ids": [Command.set([cls.water.id, cls.soda.id])],
        })


@tagged("post_install", "-at_install")
class TestRelease112(SidesCommon, PreparationCommon):
    def setUp(self):
        # PreparationCommon already creates a reservation of chicken without sides.
        super().setUp()

    def test_employee_chooses_plate_dessert_and_drink_independently(self):
        employee, _ = self._create_employee("abc-sides-choice")
        service = self.env["lafija.reservation"].with_user(employee)
        with freeze_time("2026-09-08 12:00:00"):
            record = service._submit_selections(self.website, [(self.menus[1].id, self.pork.id, self.flan.id, self.water.id)])
        self.assertEqual(record.sudo().current_product_id, self.pork)
        self.assertEqual(record.sudo().current_dessert_id, self.flan)
        self.assertEqual(record.sudo().current_drink_id, self.water)
        self.assertEqual(record._employee_values()["current_label"], "Cerdo · Flan de prueba · Agua de prueba")
        with freeze_time("2026-09-08 12:10:00"):
            service._submit_selections(self.website, [(self.menus[1].id, self.pork.id, 0, self.soda.id)])
        self.assertFalse(record.sudo().current_dessert_id)
        self.assertEqual(record.sudo().current_drink_id, self.soda)
        self.assertEqual(record.current_description, "Cerdo")

    def test_dessert_or_drink_without_published_option_is_rejected(self):
        employee, _ = self._create_employee("abc-sides-invalid")
        other = self.env["product.product"].create({
            "name": "Postre ajeno", "categ_id": self.dessert_categ.id, "sale_ok": True, "type": "consu",
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["lafija.reservation"].with_user(employee)._submit_selections(
                self.website, [(self.menus[0].id, self.chicken.id, other.id, 0)])

    def test_change_after_cut_pends_the_whole_triple(self):
        self.assertEqual(self.reservation.current_description, "Pollo")
        cut = self._take()
        with freeze_time("2026-09-14 13:10:00"):
            self.service._submit_selections(self.website, [(self.menu.id, self.chicken.id, self.brownie.id, self.water.id)])
        self.assertEqual(self.reservation.current_description, "Pollo")
        self.assertFalse(self.reservation.sudo().current_dessert_id)
        self.assertEqual(self.reservation.sudo().pending_product_id, self.chicken)
        self.assertEqual(self.reservation.sudo().pending_dessert_id, self.brownie)
        self.assertEqual(self.reservation.sudo().pending_drink_id, self.water)
        self.assertTrue(self.reservation.pending)
        self.assertEqual(cut.current_revision_id.line_ids.product_id, self.chicken)
        self.assertFalse(cut.current_revision_id.line_ids.dessert_id)
        self._resolve("accept")
        line = self.menu.cut_ids.current_revision_id.line_ids.filtered(lambda l: l.reservation_id == self.reservation)
        self.assertEqual(line.dessert_id, self.brownie)
        self.assertEqual(line.drink_id, self.water)
        with freeze_time("2026-09-14 13:20:00"):
            self.service._submit_selections(self.website, [(self.menu.id, self.pork.id, self.flan.id, self.soda.id)])
        self.service._submit_selections(self.website, [(self.menu.id, self.chicken.id, self.brownie.id, self.water.id)],
                                        withdraw_current={self.menu.id: (self.chicken.id, self.brownie.id, self.water.id)})
        self.assertFalse(self.reservation.sudo().pending_product_id)
        self.assertEqual(self.reservation.sudo().current_dessert_id, self.brownie)

    def test_day_sheet_and_labels_include_sides_without_changing_page_size(self):
        with freeze_time("2026-09-08 12:00:00"):
            self.service._submit_selections(self.website, [(self.menu.id, self.chicken.id, self.flan.id, self.water.id)])
        cut = self._take()
        sheet = self.env["report.kai_viandas.day_sheet"].with_user(self.operator)._get_report_values(
            cut.current_revision_id.ids)["sheets"][0]
        self.assertEqual({p["name"]: p["quantity"] for p in sheet["products"]}, {"Pollo": 1})
        self.assertEqual({p["name"]: p["quantity"] for p in sheet["desserts"]}, {"Flan de prueba": 1})
        self.assertEqual({p["name"]: p["quantity"] for p in sheet["drinks"]}, {"Agua de prueba": 1})
        self.assertEqual(sheet["companies"][0]["lines"][0]["dessert"], "Flan de prueba")
        batch = self.env["lafija.label.print"].browse(
            cut.current_revision_id.with_user(self.operator).action_print_labels()["res_id"])
        document, _ = self.env["ir.actions.report"].with_user(self.operator)._render_qweb_html(
            "kai_viandas.report_labels", batch.ids)
        lines = html.fromstring(document).xpath('//div[contains(@class, "lf-label-line")]')
        self.assertEqual([block.text_content() for block in lines],
                         ["14/09 · ABC de prueba", "Juan de prueba", "Pollo", "Flan de prueba · Agua de prueba"])
        pages = PdfReader(BytesIO(batch.attachment_id.raw)).pages
        self.assertEqual(len(pages), 1)
        self.assertAlmostEqual(float(pages[0].mediabox.width), 83, places=2)
        self.assertAlmostEqual(float(pages[0].mediabox.height), 255, places=2)
        text = pages[0].extract_text()
        self.assertIn("Pollo", text)
        self.assertIn("Flan", text)
        self.assertIn("Agua", text)

    def test_quotation_bills_only_the_plate_and_annex_lists_sides(self):
        with freeze_time("2026-09-08 12:00:00"):
            self.service._submit_selections(self.website, [(self.menu.id, self.chicken.id, self.flan.id, self.water.id)])
        self._take()
        with freeze_time("2026-10-01 15:00:00"):
            batch = self.env["lafija.quotation.preparation"].with_user(self.operator).create({
                "customer_company_id": self.customer.id,
            })
            batch.action_refresh()
        self.assertEqual({p["id"]: p["quantity"] for p in batch.snapshot["products"]}, {self.chicken.id: 1})
        self.assertEqual({p["id"]: p["quantity"] for p in batch.snapshot["desserts"]}, {self.flan.id: 1})
        self.assertEqual({p["id"]: p["quantity"] for p in batch.snapshot["drinks"]}, {self.water.id: 1})
        batch.action_prepare()
        # El pedido diario, reutilizado al preparar el período, factura el plato
        # y lleva postre y bebida a precio 0 (no se crea un segundo pedido).
        lines = batch.order_id.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty)
        self.assertIn(self.chicken, lines.product_id)
        self.assertGreater(lines.filtered(lambda l: l.product_id == self.chicken).price_unit, 0)
        self.assertEqual(lines.filtered(lambda l: l.product_id == self.flan).price_unit, 0)
        self.assertEqual(lines.filtered(lambda l: l.product_id == self.water).price_unit, 0)

    def test_mixed_menu_options_are_split_by_category(self):
        menu = self.env["lafija.menu.day"].with_user(self.operator).with_context(_lf_skip_category_check=True).create({
            "date": "2026-09-21", "website_id": self.website.id, "published": True,
            "product_ids": [Command.set([self.chicken.id, self.flan.id, self.water.id])],
        })
        # Odoo 19 filtra el domain al escribir: reproducir la mezcla histórica en la tabla.
        self.env.cr.execute(
            """
            INSERT INTO lafija_menu_day_product_product_rel (lafija_menu_day_id, product_product_id)
            VALUES (%s, %s), (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            [menu.id, self.flan.id, menu.id, self.water.id],
        )
        menu.invalidate_recordset(["product_ids", "dessert_ids", "drink_ids"])
        changed = menu._split_mixed_options()
        self.assertEqual(changed, menu)
        self.assertEqual(menu.product_ids, self.chicken)
        self.assertEqual(menu.dessert_ids, self.flan)
        self.assertEqual(menu.drink_ids, self.water)
        self.assertIn(str(self.flan.id), menu.dessert_snapshot)
        self.assertNotIn(str(self.flan.id), menu.option_snapshot)


@tagged("post_install", "-at_install")
class TestRelease112Pages(PagesCommon):
    def test_week_page_renders_three_choice_groups(self):
        dessert_categ = self.env["product.category"].search([("complete_name", "=", "Postre Vianda")], limit=1) or self.env["product.category"].create({"name": "Postre Vianda"})
        drink_categ = self.env["product.category"].search([("complete_name", "=", "Bebida Vianda")], limit=1) or self.env["product.category"].create({"name": "Bebida Vianda"})
        dessert = self.env["product.product"].create({"name": "Flan portal", "description_sale": "Flan portal", "sale_ok": True, "type": "consu", "categ_id": dessert_categ.id})
        drink = self.env["product.product"].create({"name": "Agua portal", "description_sale": "Agua portal", "sale_ok": True, "type": "consu", "categ_id": drink_categ.id})
        self.menus[0].with_user(self.operator).write({
            "dessert_ids": [Command.set(dessert.ids)],
            "drink_ids": [Command.set(drink.ids)],
        })
        employee, _ = self._create_employee("abc-sides-page")
        response = self._real_login(employee.login, "employee-password-123")
        self.assertEqual(response.status_code, 303, response.text)
        page = self.url_open("/my/viandas?week=2026-09-14")
        self.assertEqual(page.status_code, 200, page.text)
        document = html.fromstring(page.content)
        self.assertTrue(document.xpath('//legend[contains(text(), "Elegí el menú")]'))
        self.assertTrue(document.xpath('//legend[contains(text(), "Elegí el postre")]'))
        self.assertTrue(document.xpath('//legend[contains(text(), "Elegí la bebida")]'))
        self.assertTrue(document.xpath(f'//input[@name="menu_{self.menus[0].id}"]'))
        self.assertTrue(document.xpath(f'//input[@name="dessert_{self.menus[0].id}"][@value="{dessert.id}"]'))
        self.assertTrue(document.xpath(f'//input[@name="drink_{self.menus[0].id}"][@value="{drink.id}"]'))
        self.assertTrue(document.xpath('//strong[text()="Sin postre"]'))
        self.assertTrue(document.xpath('//strong[text()="Sin bebida"]'))
        # Los demás días de la semana no tienen postre ni bebida: un solo grupo.
        self.assertEqual(len(document.xpath("//fieldset[@class='options']")), 5)
        token = document.xpath("//input[@name='csrf_token']/@value")[0]
        saved = self.url_open("/my/viandas/reservar", data={
            "csrf_token": token, "week": "2026-09-14",
            f"menu_{self.menus[0].id}": str(self.product.id),
            f"dessert_{self.menus[0].id}": str(dessert.id),
            f"drink_{self.menus[0].id}": str(drink.id),
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertIn("elección guardada", saved.text)
        self.assertIn("Flan portal", saved.text)
        self.assertIn("Agua portal", saved.text)
        record = self.env["lafija.reservation"].search([("employee_partner_id", "=", employee.partner_id.id)], limit=1)
        self.assertEqual(record.sudo().current_dessert_id, dessert)
        self.assertEqual(record.sudo().current_drink_id, drink)
