from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import html2plaintext

from .identity import check_operator
from .reservation import check_operation, operation_context
from .time_utils import business_datetime, business_tz, day_label
from .operation_labels import safe_operation_label


class MenuDay(models.Model):
    _inherit = "lafija.menu.day"

    cut_ids = fields.One2many("lafija.preparation.cut", "menu_id", "Lista tomada", readonly=True)

    def write(self, values):
        if set(values) & {"date", "website_id"} and (self.reservation_ids or self.cut_ids):
            raise ValidationError(_("Este menú ya tiene historia. Creá el menú correcto y corregí las reservas afectadas con motivo."))
        return super().write(values)

    def action_take_list(self):
        check_operator(self.env)
        self.ensure_one()
        self.check_access("write")
        self._lock_for_operation()
        cut = self.env["lafija.preparation.cut"].search([("menu_id", "=", self.id)], limit=1)
        if not cut:
            cut = self.env["lafija.preparation.cut"].sudo().with_context(**operation_context()).create({
                "menu_id": self.id, "date": self.date, "website_id": self.website_id.id,
                "taken_at": fields.Datetime.now(), "taken_by": self.env.uid,
            })
            cut._new_revision("Primera lista para preparación", self.env.user)
        return {"type": "ir.actions.act_window", "res_model": "lafija.preparation.cut",
                "res_id": cut.id, "view_mode": "form", "target": "current"}

    def action_open_fulfillment(self):
        check_operator(self.env)
        self.ensure_one()
        cut = self.cut_ids[:1]
        if not cut:
            raise ValidationError(_("Todavía no se tomó la lista de preparación de este menú."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "lafija.preparation.cut",
            "res_id": cut.id,
            "view_mode": "form",
            "view_id": self.env.ref("kai_viandas.cut_form").id,
            "target": "current",
            "name": cut.display_name,
            "context": {**self.env.context, "lf_open_fulfillment": True},
        }


class Cut(models.Model):
    _name = "lafija.preparation.cut"
    _description = "Lista tomada para preparación"
    _order = "date desc, id desc"

    name = fields.Char("Lista de preparación", compute="_compute_name", store=True)
    menu_id = fields.Many2one("lafija.menu.day", "Menú del día", required=True, ondelete="restrict", readonly=True)
    date = fields.Date("Fecha", required=True, readonly=True)
    website_id = fields.Many2one("website", "Sitio corporativo", required=True, readonly=True)
    taken_at = fields.Datetime("Tomada el", required=True, readonly=True)
    taken_by = fields.Many2one("res.users", "Tomada por", required=True, readonly=True)
    revision_ids = fields.One2many("lafija.preparation.revision", "cut_id", "Listas conservadas", readonly=True)
    current_revision_id = fields.Many2one("lafija.preparation.revision", "Revisión actual", readonly=True)
    pending_ids = fields.One2many(related="menu_id.reservation_ids", string="Reservas del día", readonly=True)

    _menu_unique = models.Constraint("unique(menu_id)", "La primera lista de ese menú ya fue tomada.")

    @api.depends("date")
    def _compute_name(self):
        for cut in self:
            cut.name = f"Preparación {cut.date}"

    @api.model_create_multi
    def create(self, values_list):
        check_operation(self.env)
        return super().create(values_list)

    def write(self, values):
        check_operation(self.env)
        if set(values) - {"current_revision_id"}:
            raise AccessError(_("La primera toma de lista se conserva."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("La lista tomada y sus revisiones se conservan."))

    def _new_revision(self, reason, actor):
        self.ensure_one()
        check_operation(self.env)
        previous = self.current_revision_id
        revision = self.env["lafija.preparation.revision"].sudo().with_context(**operation_context()).create({
            "cut_id": self.id, "number": previous.number + 1 if previous else 1,
            "previous_id": previous.id, "reason": reason, "actor_id": actor.id,
            "occurred_at": fields.Datetime.now(),
        })
        reservations = self.env["lafija.reservation"].sudo().search([
            ("menu_id", "=", self.menu_id.id), ("state", "=", "active"), ("current_product_id", "!=", False),
        ], order="customer_company_id, employee_partner_id, id")
        self.env["lafija.preparation.line"].sudo().with_context(**operation_context()).create([
            {"revision_id": revision.id, "reservation_id": r.id, "date": r.date,
             "employee_partner_id": r.employee_partner_id.id, "employee_name": r.employee_partner_id.name,
             "customer_company_id": r.customer_company_id.id, "company_name": r.customer_company_id.name,
             "product_id": r.current_product_id.id, "description": r.current_description,
             "dessert_id": r.current_dessert_id.id, "dessert_description": r.current_dessert_description or False,
             "drink_id": r.current_drink_id.id, "drink_description": r.current_drink_description or False,
             "after_reference_time": r.after_reference_time, "after_preparation_cut": r.after_preparation_cut}
            for r in reservations
        ])
        self.sudo().with_context(**operation_context()).write({"current_revision_id": revision.id})
        return revision


class PreparationRevision(models.Model):
    _name = "lafija.preparation.revision"
    _description = "Revisión de preparación conservada"
    _order = "number desc, id desc"

    name = fields.Char("Lista y revisión", compute="_compute_name", store=True)
    cut_id = fields.Many2one("lafija.preparation.cut", "Lista tomada", required=True, ondelete="restrict")
    number = fields.Integer("Revisión", required=True)
    previous_id = fields.Many2one("lafija.preparation.revision", "Revisión anterior", ondelete="restrict")
    actor_id = fields.Many2one("res.users", "Quién", required=True)
    occurred_at = fields.Datetime("Cuándo", required=True)
    reason = fields.Text("Motivo", required=True)
    line_ids = fields.One2many("lafija.preparation.line", "revision_id", "Viandas", readonly=True)

    _number_unique = models.Constraint("unique(cut_id, number)", "Esta revisión ya existe.")

    @api.depends("cut_id.name", "number")
    def _compute_name(self):
        for revision in self:
            revision.name = f"{revision.cut_id.name} · R{revision.number}"

    @api.model_create_multi
    def create(self, values_list):
        check_operation(self.env)
        return super().create(values_list)

    def write(self, values):
        raise AccessError(_("La revisión tomada no se modifica. Registrá una corrección."))

    def unlink(self):
        raise AccessError(_("Las revisiones de preparación no se eliminan."))


class PreparationLine(models.Model):
    _name = "lafija.preparation.line"
    _description = "Vianda de una revisión de preparación"
    _order = "company_name, employee_name, id"

    revision_id = fields.Many2one("lafija.preparation.revision", "Revisión", required=True, ondelete="restrict")
    reservation_id = fields.Many2one("lafija.reservation", "Reserva", required=True, ondelete="restrict")
    date = fields.Date("Fecha", required=True)
    employee_partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict")
    employee_name = fields.Char("Empleado", required=True)
    customer_company_id = fields.Many2one("res.partner", required=True, ondelete="restrict")
    company_name = fields.Char("Empresa", required=True)
    product_id = fields.Many2one("product.product", required=True, ondelete="restrict")
    description = fields.Text("Opción elegida", required=True)
    dessert_id = fields.Many2one("product.product", "Postre", ondelete="restrict")
    dessert_description = fields.Text("Postre elegido")
    drink_id = fields.Many2one("product.product", "Bebida", ondelete="restrict")
    drink_description = fields.Text("Bebida elegida")
    after_reference_time = fields.Boolean("Después del corte diario")
    after_preparation_cut = fields.Boolean("Después de tomar la lista")

    _reservation_unique = models.Constraint("unique(revision_id, reservation_id)", "Una etiqueta por vianda en cada revisión.")

    @api.model_create_multi
    def create(self, values_list):
        check_operation(self.env)
        return super().create(values_list)

    def write(self, values):
        raise AccessError(_("La vianda tomada se conserva. Usá la corrección de su reserva."))

    def unlink(self):
        raise AccessError(_("La procedencia de una vianda no se elimina."))


class MailMessage(models.Model):
    _inherit = "mail.message"

    lf_employee_visible = fields.Boolean("Respuesta operativa visible", groups="base.group_user", copy=False)

    @api.model_create_multi
    def create(self, values_list):
        if any(v.get("lf_employee_visible") for v in values_list):
            check_operation(self.env)
        return super().create(values_list)

    def write(self, values):
        if "lf_employee_visible" in values:
            check_operation(self.env)
        return super().write(values)


class Reservation(models.Model):
    _inherit = "lafija.reservation"

    def _request_correction(self, text):
        self.ensure_one()
        self._employee_values()  # Autorización por propietario antes de elevar permisos.
        record = self.sudo()
        if not self.env.user._lf_can_use_site(record.website_id):
            raise AccessError(_("La cuenta no está habilitada."))
        text = (text or "").strip()
        if not text or len(text) > 4000:
            raise ValidationError(_("Escribí el cambio que necesitás, hasta 4000 caracteres."))
        record.menu_id._lock_for_operation()
        moment = fields.Datetime.now()
        record.with_context(**operation_context()).write({
            "attention_pending": True, "last_employee_change_at": moment,
            "after_reference_time": moment > record.menu_id._reference_datetime(),
            "after_preparation_cut": record._has_preparation_cut(),
        })
        record._record_event(self.env.user, moment, "request", record.current_description, text,
                             record.current_description, "Solicitud recibida, pendiente de atención")
        record._post_operational_message(text, self.env.user)

    def _post_operational_message(self, text, actor):
        self.ensure_one()
        message = self.sudo().with_context(**operation_context()).message_post(
            body=Markup("<p>{}</p>").format(text), author_id=actor.partner_id.id,
            subtype_xmlid="mail.mt_note",
        )
        message.with_context(**operation_context()).write({"lf_employee_visible": True})
        return message

    def _employee_values(self):
        result = super()._employee_values()
        messages = self.env["mail.message"].sudo().search([
            ("model", "=", self._name), ("res_id", "=", self.id), ("lf_employee_visible", "=", True),
        ], order="id")
        result["date_label"] = day_label(self.date)
        start = self.date - timedelta(days=self.date.weekday())
        result['week_start'] = str(start)
        result['week_start_label'] = f'{start:%d/%m}'
        partner = self.env.user.sudo().partner_id
        result["identity"] = f'{partner.name} · {partner.lf_customer_company_id.name}'
        result["timezone"] = business_tz(self.env)
        result["last_change"] = business_datetime(self.env, self.last_employee_change_at)
        result["after_cut"] = self.sudo()._has_preparation_cut()
        result["messages"] = [{"date": business_datetime(self.env, m.date), "text": html2plaintext(m.body or ""),
                               "author": "Vos" if m.author_id == self.env.user.partner_id else "La Fija"}
                              for m in messages]
        result["request_answered"] = bool(result["attention_pending"] and messages and
                                         messages[-1].author_id != partner)
        # La proyección conserva el autor propio, sin entregar usuarios ni datos comerciales.
        events = self.sudo().event_ids
        result["choices"] = [{"date": business_datetime(self.env, e.occurred_at),
                              "text": "Cambio anulado" if e.kind == "withdrawal" else e.received_description if e.kind == "choice" else "",
                              "author": "Vos" if e.kind in ("choice", "withdrawal") else "La Fija",
                              "outcome": f"Cambio que se anuló: {e.received_description}. Sigue vigente {e.applied_description}."
                              if e.kind == "withdrawal" else ("Recibido para revisión" if e.after_preparation_cut and "Pendiente" in (e.result or "") else "Elección aplicada")
                              if e.kind == "choice" else safe_operation_label(e.result)}
                             for e in events if e.kind in ("choice", "withdrawal", "response", "resolution", "closure")]
        result["request_closed"] = bool(events.filtered(lambda e: e.kind == "closure")) and not self.sudo().attention_pending
        return result

    def action_correct(self):
        check_operator(self.env)
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Editar pedido"),
                "res_model": "lafija.reservation.correction", "view_mode": "form", "target": "new",
                "context": {"default_reservation_id": self.id,
                            "default_operation": "accept" if self.pending_product_id else "note"}}
