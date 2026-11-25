"""19.0.2.0.1: un usuario de ventas sin rol La Fija puede confirmar y duplicar pedidos."""
from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRelease2001(TransactionCase):
    def setUp(self):
        super().setUp()
        self.salesman = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Vendedor sin rol La Fija", "login": "vendedor_acl@example.com",
            "group_ids": [Command.set([
                self.env.ref("base.group_user").id, self.env.ref("sales_team.group_sale_salesman").id])],
        })
        self.assertNotIn(self.env.ref("kai_viandas.group_operator"), self.salesman.group_ids)
        product = self.env["product.product"].search([("sale_ok", "=", True)], limit=1)
        partner = self.env["res.partner"].create({"name": "Cliente ACL"})
        self.order = self.env["sale.order"].create({
            "partner_id": partner.id, "user_id": self.salesman.id,
            "order_line": [Command.create({"product_id": product.id, "product_uom_qty": 1})],
        })

    def test_field_has_no_groups(self):
        self.assertFalse(self.env["sale.order"]._fields["lf_preparation_date"].groups)

    def test_salesman_reads_and_confirms(self):
        order = self.order.with_user(self.salesman)
        order.read(["lf_preparation_date"])
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    def test_salesman_duplicates(self):
        copy = self.order.with_user(self.salesman).copy()
        self.assertTrue(copy.exists())
