import io

from odoo import Command
from odoo.tools.pdf import PdfFileWriter
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .test_preparation import PreparationCommon
from .test_pages import PagesCommon


@tagged("post_install", "-at_install")
class TestDocuments(PreparationCommon):
    def setUp(self):
        super().setUp()
        self.order = self.env["sale.order"].create({
            "partner_id": self.customer.id, "lf_reservation_ids": [Command.set(self.reservation.ids)],
            "order_line": [Command.create({"product_id": self.chicken.id, "product_uom_qty": 1, "price_unit": 271828.75})],
        })

    def test_protection_survives_copy_relink_and_cannot_be_removed(self):
        self.assertTrue(self.order.lf_protected)
        self.assertIn(f"reserva:{self.reservation.id}", self.order.lf_origin)
        copied = self.order.copy({"lf_protected": False, "lf_origin": False, "lf_reservation_ids": [Command.clear()]})
        self.assertTrue(copied.lf_protected)
        self.assertEqual(copied.lf_reservation_ids, self.order.lf_reservation_ids)
        attachment = self.env["ir.attachment"].create({
            "name": "Factura protegida", "raw": b"IMPORTE PRIVADO 271828.75",
            "res_model": "sale.order", "res_id": self.order.id, "public": True,
        })
        self.assertTrue(attachment.lf_protected)
        original = attachment.lf_origin
        attachment.write({"res_model": "res.partner", "res_id": self.private.partner_id.id})
        self.assertEqual(attachment.lf_origin, original)
        copy = attachment.copy({"res_model": False, "res_id": False, "lf_protected": False})
        self.assertTrue(copy.lf_protected)
        for record in (self.order, attachment):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                record.write({"lf_protected": False})
        with self.assertRaises(AccessError):
            attachment.with_user(self.private).read(["raw"])
        with self.assertRaises(AccessError):
            self.env["ir.binary"].with_user(self.private)._find_record(res_id=attachment.id, access_token=attachment.generate_access_token()[0])
        with self.assertRaises(AccessError):
            self.env["lafija.access.policy"].with_user(self.private)._assert_delivery(self.order.with_user(1))

    def test_false_values_cannot_remove_a_manual_protection(self):
        # Sin reserva/enlace que pudiera volver a marcar por accidente el documento.
        order = self.env["sale.order"].create({"partner_id": self.customer.id, "lf_protected": True})
        journal = self.env["account.journal"].create({"name": "Protección manual", "code": "LFPM", "type": "sale"})
        invoice = self.env["account.move"].create({"partner_id": self.customer.id,
            "move_type": "out_invoice", "journal_id": journal.id, "lf_protected": True})
        attachment = self.env["ir.attachment"].create({"name": "Manual", "raw": b"271828.75", "lf_protected": True})
        for record in (order, invoice, attachment):
            origin = record.lf_origin
            for value in (False, None, 0, ""):
                with self.subTest(model=record._name, value=value):
                    with self.assertRaises(ValidationError), self.cr.savepoint():
                        record.write({"lf_protected": value})
                    self.assertTrue(record.lf_protected)
                    self.assertEqual(record.lf_origin, origin)
        # Un registro ordinario puede seguir guardando su booleano falso nativo.
        ordinary = self.env["sale.order"].create({"partner_id": self.customer.id})
        ordinary.write({"lf_protected": None})
        self.assertFalse(ordinary.lf_protected)

    def test_line_access_uses_document_protection_even_if_related_cache_is_wrong(self):
        self.order.partner_id = self.private.partner_id
        line = self.order.order_line
        # Simular una columna related desactualizada. La regla debe consultar al padre.
        self.env.flush_all()
        self.cr.execute("UPDATE sale_order_line SET lf_protected = false WHERE id = %s", [line.id])
        line.invalidate_recordset(flush=False)
        self.assertFalse(line.lf_protected, "El caso requiere una columna realmente desactualizada")
        with self.assertRaises(AccessError):
            line.with_user(self.private).read(["price_unit"])

    def test_all_invoice_types_remain_denied_when_attributed_to_employee_without_marker(self):
        journals = {kind: self.env["account.journal"].create({"name": f"Diario {kind} P2", "code": code, "type": kind})
                    for kind, code in [("sale", "LFP2S"), ("purchase", "LFP2P")]}
        for move_type in ("out_invoice", "out_refund", "in_invoice", "in_refund"):
            invoice = self.env["account.move"].create({"move_type": move_type, "partner_id": self.employee.partner_id.id,
                "journal_id": journals["sale" if move_type.startswith("out") else "purchase"].id})
            self.cr.execute("UPDATE account_move SET lf_protected = false WHERE id = %s", [invoice.id])
            invoice.invalidate_recordset()
            with self.assertRaises(AccessError):
                invoice.with_user(self.employee).read(["amount_total"])
            with self.assertRaises(AccessError):
                self.env["lafija.access.policy"].with_user(self.employee)._assert_delivery(invoice.sudo())

    def test_commercial_recipients_and_explicit_email_are_filtered_before_delivery(self):
        # Simular un contacto heredado con email; A no permite producirlo en el alta.
        email = "corporate@example.test"
        self.cr.execute("UPDATE res_partner SET email = %s, email_normalized = %s WHERE id = %s", [email, email, self.employee.partner_id.id])
        self.employee.partner_id.invalidate_recordset()
        self.order.message_subscribe(partner_ids=[self.employee.partner_id.id, self.private.partner_id.id])
        self.assertNotIn(self.employee.partner_id, self.order.message_partner_ids)
        mail = self.env["mail.mail"].create({
            "subject": "Factura", "body_html": "<p>IMPORTE 271828.75</p>",
            "email_from": "lafija@example.test", "email_to": email, "email_cc": self.private.email,
            "model": "sale.order", "res_id": self.order.id,
        })
        outgoing = mail._prepare_outgoing_list()
        self.assertTrue(outgoing)
        addresses = [address for part in outgoing for address in part["email_to"] + part["email_cc"]]
        self.assertNotIn(email, str(addresses))
        self.assertIn(self.private.email, str(addresses))


@tagged("post_install", "-at_install")
class TestDocumentPages(PagesCommon):
    def test_pdf_first_page_ownership_token_cannot_bypass_protection(self):
        writer = PdfFileWriter()
        writer.add_blank_page(width=200, height=200)
        output = io.BytesIO()
        writer.write(output)
        order = self.env["sale.order"].create({"partner_id": self.customer.id, "lf_protected": True})
        protected = self.env["ir.attachment"].create({
            "name": "protegido.pdf", "raw": output.getvalue(), "mimetype": "application/pdf",
            "res_model": "sale.order", "res_id": order.id, "public": True})
        ordinary = self.env["ir.attachment"].create({
            "name": "particular.pdf", "raw": output.getvalue(), "mimetype": "application/pdf",
            "res_model": "res.partner", "res_id": self.private.partner_id.id})
        self._anonymous()
        for attachment, allowed in ((protected, False), (ordinary, True)):
            token = attachment._get_ownership_token()
            response = self.url_open(f"/mail/attachment/pdf_first_page/{attachment.id}?access_token={token}",
                                     headers={"Host": "public.test"})
            if allowed:
                self.assertEqual(response.status_code, 200, response.text[:500])
                self.assertTrue(response.content.startswith(b"%PDF"))
            else:
                self.assertNotEqual(response.status_code, 200, response.text[:500])
                self.assertFalse(response.content.startswith(b"%PDF"))

    def test_protected_token_pdf_and_public_binary_are_denied_to_external_users(self):
        order = self.env["sale.order"].create({
            "partner_id": self.customer.id, "lf_protected": True,
            "order_line": [Command.create({"product_id": self.product.id, "product_uom_qty": 1, "price_unit": 271828.75})],
        })
        token = order._portal_ensure_token()
        attachment = self.env["ir.attachment"].create({
            "name": "protected.pdf", "raw": b"%PDF PRIVADO 271828.75", "public": True,
            "res_model": "sale.order", "res_id": order.id,
        })
        file_token = attachment.generate_access_token()[0]
        self._anonymous()
        for login in (None, self.private.login):
            self.authenticate(login, "fixture" if login else None)
            self.opener.cookies.set("session_id", self.session.sid, domain="public.test")
            for path in (f"/my/orders/{order.id}?access_token={token}",
                         f"/my/orders/{order.id}?access_token={token}&report_type=pdf",
                         f"/web/content/{attachment.id}?access_token={file_token}",
                         f"/report/pdf/sale.report_saleorder/{order.id}"):
                with self.subTest(login=login, path=path):
                    result = self.url_open(path, headers={"Host": "public.test"}, allow_redirects=False)
                    self.assertNotEqual(result.status_code, 200, result.text[:1000])
                    self.assertNotIn(b"271828.75", result.content)

    def test_private_legitimate_order_token_and_file_still_work(self):
        order = self.env["sale.order"].create({"partner_id": self.private.partner_id.id,
            "order_line": [Command.create({"product_id": self.product.id, "product_uom_qty": 1, "price_unit": 42})]})
        token = order._portal_ensure_token()
        attachment = self.env["ir.attachment"].create({"name": "public-test.txt", "raw": b"DOCUMENTO PARTICULAR",
            "res_model": "sale.order", "res_id": order.id})
        file_token = attachment.generate_access_token()[0]
        self._anonymous()
        headers = {"Host": "public.test"}
        response = self.url_open(f"/my/orders/{order.id}?access_token={token}", headers=headers)
        self.assertEqual(response.status_code, 200, response.text[:1000])
        response = self.url_open(f"/web/content/{attachment.id}?access_token={file_token}", headers=headers)
        self.assertEqual(response.status_code, 200, response.text[:1000])
        self.assertEqual(response.content, b"DOCUMENTO PARTICULAR")
