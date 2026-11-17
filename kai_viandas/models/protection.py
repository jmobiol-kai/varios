from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.tools import email_normalize_all


COMMERCIAL = {"sale.order", "sale.order.line", "account.move", "account.move.line"}


class AccessPolicy(models.AbstractModel):
    _name = "lafija.access.policy"
    _description = "Política de entrega de documentos de La Fija"

    def _corporate_employee_partners(self, partners):
        return partners.sudo().filtered(lambda p: p.lf_corporate_account or p.lf_customer_company_id
            or p.website_id.lf_corporate_site
            or any(u._lf_is_corporate_subject() for u in p.with_context(active_test=False).user_ids))

    def _is_protected(self, records, seen=None):
        seen = set() if seen is None else seen
        for record in records.sudo():
            key = (record._name, record.id)
            if key in seen:
                continue
            seen.add(key)
            if (record._name.startswith("lafija.")
                    or ("lf_protected" in record and record.lf_protected)
                    or ("lf_origin" in record and record.lf_origin)):
                return True
            if record._name == "ir.attachment":
                model, res_id = record.res_model, record.res_id
            elif record._name == "mail.message":
                model, res_id = record.model, record.res_id
            else:
                model, res_id = False, False
            if model in self.env and res_id:
                if self._is_protected(self.env[model].browse(res_id).exists(), seen):
                    return True
        return False

    def _original_user(self):
        # El retorno privilegiado nunca convierte al visitante en el usuario interno
        # que se usó para renderizar. En HTTP se conserva la identidad de la sesión.
        if request and request.db:
            uid = (request.session.uid or getattr(request, "_lf_bearer_uid", None)
                   or self.env.ref("base.public_user").id)
            return self.env["res.users"].sudo().browse(uid)
        return self.env.user.sudo()

    def _assert_delivery(self, records):
        user = self._original_user()
        if user._lf_is_corporate_subject():
            raise AccessError(_("La cuenta corporativa no permite descargar documentos comerciales o colectivos."))
        if user.share and self._is_protected(records):
            raise AccessError(_("Este documento solo está disponible para la gestión interna de La Fija."))


class ProtectedDocument(models.AbstractModel):
    _name = "lafija.protected.document"
    _description = "Clasificación permanente de documentos corporativos"

    lf_protected = fields.Boolean("Documento corporativo protegido", copy=True, groups="base.group_user", tracking=True)
    lf_reservation_ids = fields.Many2many("lafija.reservation", string="Reservas de origen", copy=True, groups="base.group_user")
    lf_origin = fields.Text("Procedencia conservada", readonly=True, copy=True, groups="base.group_user")

    def _lf_inherited_protection(self):
        self.ensure_one()
        protected = bool(self.lf_reservation_ids)
        if "partner_id" in self and self.partner_id:
            protected |= bool(self.env["lafija.access.policy"]._corporate_employee_partners(self.partner_id))
        if self._name == "account.move":
            protected |= any(self.invoice_line_ids.sale_line_ids.order_id.mapped("lf_protected"))
            protected |= bool(self.reversed_entry_id.lf_protected)
        return protected

    def _lf_freeze_protection(self):
        for record in self.sudo():
            if record.lf_protected or record.lf_origin or record._lf_inherited_protection():
                origin = record.lf_origin or f"{record._name}:{record.id}"
                for reservation in record.lf_reservation_ids:
                    reference = f"reserva:{reservation.id}"
                    if reference not in origin.splitlines():
                        origin += "\n" + reference
                super(ProtectedDocument, record).write({"lf_protected": True, "lf_origin": origin})
                attachments = self.env["ir.attachment"].sudo().search([
                    ("res_model", "=", record._name), ("res_id", "=", record.id),
                ])
                if attachments:
                    attachments._lf_freeze_protection()

    @api.model_create_multi
    def create(self, values_list):
        records = super().create(values_list)
        records._lf_freeze_protection()
        return records

    def write(self, values):
        if "lf_protected" in values and not values["lf_protected"] and any(self.mapped("lf_protected")):
            raise ValidationError(_("La protección de un documento no se retira."))
        if "lf_origin" in values and any(self.mapped("lf_origin")):
            raise ValidationError(_("La procedencia original se conserva."))
        result = super().write(values)
        self._lf_freeze_protection()
        return result

    def copy(self, default=None):
        default = dict(default or {})
        if self.lf_protected:
            default.update(lf_protected=True, lf_origin=self.lf_origin,
                           lf_reservation_ids=[Command.set(self.lf_reservation_ids.ids)])
        return super().copy(default)


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "lafija.protected.document"]

    def _prepare_invoice(self):
        values = super()._prepare_invoice()
        if self.lf_protected:
            values.update(lf_protected=True,
                          lf_reservation_ids=[Command.set(self.lf_reservation_ids.ids)])
        return values

    def _lf_freeze_protection(self):
        super()._lf_freeze_protection()
        moves = self.sudo().filtered("lf_protected").order_line.invoice_lines.move_id
        if moves:
            moves._lf_freeze_protection()


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "lafija.protected.document"]

    def action_post(self):
        # ADHOC puede asignar un CAE ficticio en homologación sin certificados.
        # En la copia neutralizada se exige un rechazo explícito antes de _post.
        if ('afip_ws' in self.env['account.journal']._fields
                and self.env['ir.config_parameter'].sudo().get_param('database.is_ar_neutralized') == 'true'
                and any(self.journal_id.mapped('afip_ws'))):
            raise UserError(_("Esta copia está neutralizada para ARCA. No se pueden validar comprobantes electrónicos, ni siquiera con CAE simulado. Usá un diario Ventas X para la evaluación interna."))
        return super().action_post()


class SaleLine(models.Model):
    _inherit = "sale.order.line"

    lf_protected = fields.Boolean(related="order_id.lf_protected", store=True, groups="base.group_user")


class AccountLine(models.Model):
    _inherit = "account.move.line"

    lf_protected = fields.Boolean(related="move_id.lf_protected", store=True, groups="base.group_user")

    @api.model_create_multi
    def create(self, values_list):
        records = super().create(values_list)
        records.move_id._lf_freeze_protection()
        return records

    def write(self, values):
        result = super().write(values)
        if set(values) & {"move_id", "sale_line_ids"}:
            self.move_id._lf_freeze_protection()
        return result


class Attachment(models.Model):
    _inherit = "ir.attachment"

    lf_protected = fields.Boolean("Archivo corporativo protegido", copy=True, groups="base.group_user")
    lf_origin = fields.Text("Procedencia conservada", readonly=True, copy=True, groups="base.group_user")

    def _lf_freeze_protection(self):
        policy = self.env["lafija.access.policy"]
        for attachment in self.sudo():
            if policy._is_protected(attachment):
                super(Attachment, attachment).write({
                    "lf_protected": True,
                    "lf_origin": attachment.lf_origin or f"{attachment.res_model}:{attachment.res_id}",
                })

    @api.model_create_multi
    def create(self, values_list):
        records = super().create(values_list)
        records._lf_freeze_protection()
        return records

    def write(self, values):
        if "lf_protected" in values and not values["lf_protected"] and any(self.mapped("lf_protected")):
            raise ValidationError(_("La protección del archivo se conserva."))
        if "lf_origin" in values and any(self.mapped("lf_origin")):
            raise ValidationError(_("La procedencia del archivo se conserva."))
        # Antes de desvincular se fija el origen; después se incorpora el nuevo origen
        # cuando un archivo común se vincula a un documento protegido.
        self._lf_freeze_protection()
        result = super().write(values)
        self._lf_freeze_protection()
        return result

    def copy(self, default=None):
        default = dict(default or {})
        if self.env["lafija.access.policy"]._is_protected(self):
            default.update(lf_protected=True, lf_origin=self.lf_origin or f"{self.res_model}:{self.res_id}")
        return super().copy(default)

    def _to_http_stream(self):
        self.env["lafija.access.policy"]._assert_delivery(self)
        return super()._to_http_stream()


class Binary(models.AbstractModel):
    _inherit = "ir.binary"

    def _find_record(self, xmlid=None, res_model="ir.attachment", res_id=None, access_token=None, field=None):
        record = (self.env.ref(xmlid, False) if xmlid else
                  self.env[res_model].sudo().browse(res_id).exists() if res_model in self.env and res_id else False)
        if record:
            self.env["lafija.access.policy"]._assert_delivery(record)
        return super()._find_record(xmlid, res_model, res_id, access_token, field)

    def _get_stream_from(self, record, *args, **kwargs):
        self.env["lafija.access.policy"]._assert_delivery(record)
        return super()._get_stream_from(record, *args, **kwargs)


class Reports(models.Model):
    _inherit = "ir.actions.report"

    def _lf_check_report(self, report_ref, docids):
        report = self._get_report(report_ref)
        model = report.model
        if model in self.env:
            self.env["lafija.access.policy"]._assert_delivery(self.env[model].sudo().browse(docids or []).exists())

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        self._lf_check_report(report_ref, [res_ids] if isinstance(res_ids, int) else res_ids)
        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

    def _render_qweb_html(self, report_ref, docids, data=None):
        self._lf_check_report(report_ref, docids)
        return super()._render_qweb_html(report_ref, docids, data=data)

    def _render_qweb_text(self, report_ref, docids, data=None):
        self._lf_check_report(report_ref, docids)
        return super()._render_qweb_text(report_ref, docids, data=data)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def message_subscribe(self, partner_ids=None, subtype_ids=None):
        if self._name in COMMERCIAL and partner_ids:
            partners = self.env["res.partner"].browse(partner_ids)
            partner_ids = (partners - self.env["lafija.access.policy"]._corporate_employee_partners(partners)).ids
        return super().message_subscribe(partner_ids=partner_ids, subtype_ids=subtype_ids)

    def _notify_get_recipients(self, message, msg_vals=False, **kwargs):
        recipients = super()._notify_get_recipients(message, msg_vals=msg_vals, **kwargs)
        if self._name in COMMERCIAL:
            partners = self.env["res.partner"].browse([r["id"] for r in recipients])
            blocked = set(self.env["lafija.access.policy"]._corporate_employee_partners(partners).ids)
            recipients = [r for r in recipients if r["id"] not in blocked]
        return recipients


class Mail(models.Model):
    _inherit = "mail.mail"

    def _prepare_outgoing_list(self, mail_server=False, doc_to_followers=None):
        result = super()._prepare_outgoing_list(mail_server=mail_server, doc_to_followers=doc_to_followers)
        policy = self.env["lafija.access.policy"]
        protected = policy._is_protected(self.attachment_ids)
        if self.model in self.env and self.res_id:
            protected |= policy._is_protected(self.env[self.model].browse(self.res_id).exists())
        if self.model not in COMMERCIAL and not protected:
            return result
        emails = set(email_normalize_all(",".join(value or "" for value in
                     (self.email_to, self.email_cc, *self.recipient_ids.mapped("email")))))
        partners = self.env["res.partner"].sudo().with_context(active_test=False).search([("email_normalized", "in", list(emails))])
        blocked = set(policy._corporate_employee_partners(partners).mapped("email_normalized"))
        safe = []
        for mail in result:
            for key in ("email_to", "email_cc"):
                mail[key] = [address for address in mail[key] if not set(email_normalize_all(address)) & blocked]
            if not mail["email_to"] and not mail["email_cc"]:
                continue
            mail["email_to_normalized"] = email_normalize_all(",".join(mail["email_to"] + mail["email_cc"]))
            mail["email_to_raw"] = ",".join(mail["email_to"])
            safe.append(mail)
        return safe
