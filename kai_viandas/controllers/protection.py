from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.mail.controllers.attachment import AttachmentController
from odoo.addons.account.controllers.download_docs import AccountDocumentDownloadController


class ProtectedPortal(CustomerPortal):
    def _document_check_access(self, model_name, document_id, access_token=None):
        document = request.env[model_name].sudo().browse(document_id).exists()
        request.env["lafija.access.policy"]._assert_delivery(document)
        return super()._document_check_access(model_name, document_id, access_token=access_token)


class ProtectedAccountTokens(AuthSignupHome):
    def get_auth_signup_qcontext(self):
        values = super().get_auth_signup_qcontext()
        token = values.get("token")
        if token:
            partner = request.env["res.partner"].sudo()._signup_retrieve_partner(token, check_validity=True, raise_exception=False)
            if partner and request.env["lafija.access.policy"]._corporate_employee_partners(partner):
                raise AccessError("La Fija gestiona el restablecimiento de esta cuenta.")
        return values


class ProtectedAttachmentPreview(AttachmentController):
    def _get_pdf_first_page_response(self, attachment):
        # Esta ruta nativa extrae bytes directamente después de validar un token
        # de ownership; no pasa por ir.binary ni por _to_http_stream.
        request.env["lafija.access.policy"]._assert_delivery(attachment)
        return super()._get_pdf_first_page_response(attachment)


class ProtectedAccountingDownloads(AccountDocumentDownloadController):
    @http.route()
    def download_invoice_attachments(self, attachments):
        request.env["lafija.access.policy"]._assert_delivery(attachments)
        return super().download_invoice_attachments(attachments)

    @http.route()
    def download_invoice_documents_filetype(self, invoices, filetype, allow_fallback=True):
        request.env["lafija.access.policy"]._assert_delivery(invoices)
        return super().download_invoice_documents_filetype(invoices, filetype, allow_fallback=allow_fallback)

    @http.route()
    def download_move_attachments(self, moves):
        request.env["lafija.access.policy"]._assert_delivery(moves)
        return super().download_move_attachments(moves)
