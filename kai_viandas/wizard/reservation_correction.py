import json

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from ..models.identity import check_operator
from ..models.reservation import choice_label, operation_context
from ..models.time_utils import day_label


class Correction(models.TransientModel):
    _name = "lafija.reservation.correction"
    _description = "Corrección operativa de una reserva"

    reservation_id = fields.Many2one("lafija.reservation", "Reserva", required=True, readonly=True)
    operation = fields.Selection([
        ("accept", "Aplicar elección pendiente"), ("replace", "Corregir opción"),
        ("restore", "Restaurar una elección tomada"), ("reject", "Rechazar el cambio de opción"),
        ("cancel", "Cancelar vianda"), ("reassign", "Corregir empresa o día"),
        ("note", "Responder al empleado"),
        ("close_request", "Cerrar solicitud sin cambiar la vianda"),
    ], string="Qué querés hacer", required=True, default="note")
    employee_name = fields.Char(related="reservation_id.employee_partner_id.name", string="Empleado")
    meal_date = fields.Date(related="reservation_id.date", string="Día de la vianda")
    current_choice = fields.Text(related="reservation_id.current_description", string="Elección vigente")
    pending_choice = fields.Text(related="reservation_id.pending_description", string="Elección pendiente de aplicar")
    attention_open = fields.Boolean(related="reservation_id.attention_pending")
    request_text = fields.Text(compute="_compute_request_text", string="Solicitud recibida")
    observed_state = fields.Char(readonly=True)
    conflict_notice = fields.Char(readonly=True)

    def _presented_state(self, record):
        """Referencia de lo mostrado, incluida una consulta o respuesta nueva."""
        latest = self.env['lafija.reservation.event'].search(
            [('reservation_id', '=', record.id)], order='id desc', limit=1)
        return json.dumps([
            record.id, latest.id or 0, record.menu_id.id, record.customer_company_id.id,
            record.state, record.current_product_id.id, record.pending_product_id.id,
            record.current_dessert_id.id, record.pending_dessert_id.id,
            record.current_drink_id.id, record.pending_drink_id.id,
            record.attention_pending, record.current_description, record.pending_description,
            record.current_dessert_description, record.pending_dessert_description,
            record.current_drink_description, record.pending_drink_description,
        ])

    @api.onchange('reservation_id')
    def _onchange_presented_state(self):
        self.observed_state = self._presented_state(self.reservation_id) if self.reservation_id else False
        self.conflict_notice = False

    @api.model_create_multi
    def create(self, values_list):
        # El formulario envía la referencia capturada al abrir (force_save).
        # Quien usa ORM sin formulario captura el estado al crear el asistente.
        values_list = [dict(values) for values in values_list]
        for values in values_list:
            if not values.get('observed_state') and values.get('reservation_id'):
                record = self.env['lafija.reservation'].browse(values['reservation_id'])
                record.check_access('read')
                values['observed_state'] = self._presented_state(record)
        return super().create(values_list)

    def _show_current_state(self, observed_state):
        message = _("Esta reserva cambió mientras la atendías. No se aplicó la actuación. "
                    "Revisá el estado actualizado y confirmá de nuevo; conservamos tu motivo y respuesta.")
        self.write({'observed_state': observed_state, 'conflict_notice': message})
        self.invalidate_recordset(['current_choice', 'pending_choice', 'attention_open',
                                   'request_text', 'employee_name', 'meal_date'])
        return {'type': 'ir.actions.client', 'tag': 'lf_operation_feedback', 'params': {
            'message': message, 'type': 'warning',
            'next': {'type': 'ir.actions.act_window', 'name': _('Editar pedido'), 'res_model': self._name,
                     'res_id': self.id, 'view_mode': 'form', 'target': 'new',
                     'views': [(self.env.ref('kai_viandas.correction_form').id, 'form')]},
        }}

    def _compute_request_text(self):
        for wizard in self:
            history = wizard.reservation_id.event_ids
            last_close = history.filtered(lambda e: e.kind == "closure")[-1:]
            events = history.filtered(lambda e: e.kind == "request" and e.id > (last_close.id or 0))
            wizard.request_text = ('\n\n'.join(events.mapped('received_description'))
                                   if wizard.reservation_id.attention_pending else "Sin solicitud escrita pendiente.")
    product_id = fields.Many2one("product.product", "Plato correcto", domain=[("sale_ok", "=", True)])
    dessert_id = fields.Many2one("product.product", "Postre correcto", domain=[("sale_ok", "=", True)])
    drink_id = fields.Many2one("product.product", "Bebida correcta", domain=[("sale_ok", "=", True)])
    previous_line_id = fields.Many2one("lafija.preparation.line", "Vianda anterior")
    customer_company_id = fields.Many2one("res.partner", "Empresa correcta", domain=[("is_company", "=", True)])
    target_menu_id = fields.Many2one("lafija.menu.day", "Menú y día correctos")
    reason = fields.Text("Motivo interno (obligatorio)", required=True)
    employee_message = fields.Text("Respuesta al empleado", help="Texto operativo, sin importes ni documentos comerciales.")

    def action_apply(self):
        check_operator(self.env)
        self.ensure_one()
        if not (self.reason or "").strip():
            raise ValidationError(_("Indicá el motivo para conservar la historia."))
        record = self.reservation_id
        record.check_access("write")
        record.invalidate_recordset()
        original_menu = record.menu_id
        menus = original_menu | self.target_menu_id if self.operation == "reassign" else original_menu
        menus._lock_for_operation()
        record.invalidate_recordset()
        observed_state = self._presented_state(record)
        changed_since_open = self.observed_state != observed_state
        if changed_since_open and self.operation != 'note':
            return self._show_current_state(observed_state)
        original_company = record.customer_company_id
        before = choice_label(record.current_description, record.current_dessert_description, record.current_drink_description) or ""
        values = {}
        if self.operation == "accept":
            if not (record.pending_product_id or record.pending_dessert_id or record.pending_drink_id):
                raise ValidationError(_("No hay una opción pendiente. Elegí Corregir opción o respondé a la solicitud."))
            values.update(current_product_id=record.pending_product_id.id,
                          current_description=record.pending_description,
                          current_dessert_id=record.pending_dessert_id.id,
                          current_dessert_description=record.pending_dessert_description or False,
                          current_drink_id=record.pending_drink_id.id,
                          current_drink_description=record.pending_drink_description or False,
                          state="active")
        elif self.operation == "replace":
            if not self.product_id or not self.product_id.active or not self.product_id.sale_ok:
                raise ValidationError(_("Elegí un plato activo y vendible."))
            if self.dessert_id and (not self.dessert_id.active or not self.dessert_id.sale_ok):
                raise ValidationError(_("Elegí un postre activo y vendible, o dejalo vacío."))
            if self.drink_id and (not self.drink_id.active or not self.drink_id.sale_ok):
                raise ValidationError(_("Elegí una bebida activa y vendible, o dejala vacía."))
            values.update(current_product_id=self.product_id.id,
                          current_description=self.product_id.description_sale or self.product_id.display_name,
                          current_dessert_id=self.dessert_id.id,
                          current_dessert_description=(self.dessert_id.description_sale or self.dessert_id.display_name) if self.dessert_id else False,
                          current_drink_id=self.drink_id.id,
                          current_drink_description=(self.drink_id.description_sale or self.drink_id.display_name) if self.drink_id else False,
                          state="active")
        elif self.operation == "restore":
            line = self.previous_line_id
            if not line or line.reservation_id != record:
                raise ValidationError(_("Elegí una vianda anterior de esta misma reserva."))
            values.update(current_product_id=line.product_id.id, current_description=line.description,
                          current_dessert_id=line.dessert_id.id,
                          current_dessert_description=line.dessert_description or False,
                          current_drink_id=line.drink_id.id,
                          current_drink_description=line.drink_description or False,
                          state="active")
        elif self.operation == "cancel":
            values["state"] = "cancelled"
        elif self.operation == "reassign":
            if not self.customer_company_id and not self.target_menu_id:
                raise ValidationError(_("Indicá la empresa o el menú que necesitás corregir."))
            if self.customer_company_id:
                if not self.customer_company_id.is_company:
                    raise ValidationError(_("El destinatario comercial debe ser una empresa cliente."))
                values["customer_company_id"] = self.customer_company_id.id
            if self.target_menu_id:
                target = self.target_menu_id
                if self.env["lafija.reservation"].search_count([
                    ("employee_partner_id", "=", record.employee_partner_id.id),
                    ("date", "=", target.date), ("id", "!=", record.id),
                ]):
                    raise ValidationError(_("Ya hay una reserva de ese día. Corregí esa reserva y cancelá la duplicada dejando el motivo."))
                values.update(menu_id=target.id, date=target.date, website_id=target.website_id.id,
                              menu_revision=target.revision)
        if self.operation == "close_request":
            values["attention_pending"] = False
        if self.operation not in ("note", "close_request"):
            values.update(pending_product_id=False, pending_description=False,
                          pending_dessert_id=False, pending_dessert_description=False,
                          pending_drink_id=False, pending_drink_description=False)
        # La hora y las marcas del último acto del empleado no se reescriben.
        record.with_context(**operation_context()).write(values)
        result = f"{dict(self._fields['operation'].selection)[self.operation]}: {self.reason.strip()}"
        if self.operation == "reassign":
            result += (f" | Empresa: {original_company.display_name} → {record.customer_company_id.display_name}"
                       f" | Menú: {original_menu.display_name} → {record.menu_id.display_name}")
        kind = "response" if self.operation == "note" else "closure" if self.operation == "close_request" else "resolution"
        applied = choice_label(record.current_description, record.current_dessert_description, record.current_drink_description)
        record._record_event(self.env.user, fields.Datetime.now(), kind, before,
                             "", applied or "", result)
        defaults = {"accept": "La Fija aplicó tu cambio.", "replace": "La Fija corrigió tu elección.",
                    "restore": "La Fija restauró una elección anterior.", "reject": "La Fija atendió tu solicitud sin aplicar el cambio.",
                    "cancel": "La Fija canceló esta vianda.", "reassign": "La Fija corrigió la atribución de tu reserva.",
                    "note": ("La Fija respondió. Tu solicitud sigue pendiente de resolución." if record.attention_pending
                             else "La Fija respondió sobre tu reserva. No hay una consulta escrita pendiente."),
                    "close_request": "La Fija cerró tu solicitud. La elección de la vianda no cambia."}
        record._post_operational_message((self.employee_message or "").strip() or defaults[self.operation], self.env.user)
        operational_change = bool(set(values) & {
            "current_product_id", "current_dessert_id", "current_drink_id",
            "state", "customer_company_id", "menu_id",
        })
        if operational_change:
            cuts = self.env["lafija.preparation.cut"].search([("menu_id", "in", menus.ids)])
            for cut in cuts:
                cut.with_context(**operation_context())._new_revision(self.reason.strip(), self.env.user)
        summary = {"note": ("Respuesta enviada; la consulta sigue pendiente." if record.attention_pending
                            else "Respuesta enviada; no hay consulta escrita pendiente."),
                   "close_request": "Consulta cerrada; la vianda no cambia."}.get(
                       self.operation, "Corrección aplicada. Revisá la lista y las etiquetas vigentes.")
        if record.attention_pending and self.operation not in ("note", "close_request"):
            summary += " La consulta escrita sigue abierta; cerrala cuando esté resuelta."
        if changed_since_open:
            summary = "La reserva cambió mientras la atendías. " + summary
        return {"type": "ir.actions.client", "tag": "lf_operation_feedback", "params": {
            "message": f"{record.employee_partner_id.name} · {day_label(record.date)}: {summary}",
            "type": "warning" if changed_since_open else "success",
            "close": True,
        }}
