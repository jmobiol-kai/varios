import secrets

from odoo import api, Command, fields, models, _
from odoo.exceptions import ValidationError

from ..models.identity import check_operator, identity_context


DEFAULT_REASONS = {
    "create": "Alta de empleado",
    "reset": "Restablecimiento de contraseña",
    "disable": "Deshabilitación",
    "enable": "Habilitación",
    "update": "Corrección de empresa y sitio",
}


class EmployeeAccess(models.TransientModel):
    _name = "lafija.employee.access"
    _description = "Alta y recuperación de acceso corporativo"
    _transient_max_hours = 1

    operation = fields.Selection([
        ("create", "Alta de empleado"), ("update", "Corregir empresa y sitio"),
        ("reset", "Restablecer contraseña"), ("disable", "Deshabilitar"),
        ("enable", "Habilitar"),
    ], string="Operación de acceso", required=True, default="create")
    employee_id = fields.Many2one("res.partner", "Empleado", readonly=True)
    name = fields.Char("Nombre del empleado")
    login = fields.Char("Usuario")
    customer_company_id = fields.Many2one(
        "res.partner", "Empresa cliente", domain=[("is_company", "=", True)],
    )
    website_id = fields.Many2one(
        "website", "Sitio corporativo", domain=[("lf_corporate_site", "=", True)],
    )
    new_password = fields.Char("Nueva contraseña", default=lambda self: str(secrets.randbelow(900000) + 100000), copy=False)
    reason = fields.Char("Motivo")
    credential_bundle = fields.Text("Acceso para entregar", compute="_compute_credentials")
    existing_login = fields.Char("Usuario", compute="_compute_credentials")

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        if 'website_id' in names and not values.get('website_id'):
            sites = self.env['website'].search([('lf_corporate_site', '=', True)], limit=2)
            if len(sites) == 1:
                values['website_id'] = sites.id
        return values

    @api.depends("login", "employee_id", "new_password", "operation")
    def _compute_credentials(self):
        for wizard in self:
            users = wizard.employee_id.sudo().with_context(active_test=False).user_ids
            wizard.existing_login = users[:1].login or ""
            login = wizard.login if wizard.operation == "create" else wizard.existing_login
            wizard.credential_bundle = (
                f"Usuario: {login or ''}\nContraseña: {wizard.new_password}"
                if wizard.new_password and wizard.operation in ("create", "reset") else ""
            )

    def action_apply(self):
        check_operator(self.env)
        self.ensure_one()
        reason = (self.reason or "").strip() or DEFAULT_REASONS[self.operation]
        actor = self.env.user
        ctx = identity_context()
        if self.operation in ("create", "reset") and not (self.new_password or "").strip():
            raise ValidationError(_("Completá la contraseña."))
        if self.operation in ("create", "update"):
            if not self.customer_company_id.is_company or not self.website_id.lf_corporate_site:
                raise ValidationError(_("Elegí una empresa cliente y un sitio corporativo."))
        if self.operation == "create":
            if self.employee_id:
                raise ValidationError(_("El alta crea un contacto independiente nuevo."))
            partner, user = self.env['lafija.employee.onboarding']._create_identity(
                name=self.name, login=self.login, password=self.new_password,
                company=self.customer_company_id, website=self.website_id, reason=reason)
        else:
            partner = self.employee_id.sudo().with_context(**ctx)
            users = partner.with_context(active_test=False).user_ids
            if (len(users) != 1 or not users.share
                    or not (partner.lf_corporate_account or users._lf_is_corporate_subject())):
                raise ValidationError(_("Seleccioná un empleado corporativo con su cuenta individual."))
            user = users.with_context(**ctx)
            partner.write({"lf_corporate_account": True})
            if self.operation == "reset":
                user.write({"password": self.new_password})
            elif self.operation == "disable":
                partner.write({"lf_enabled": False})
                user.write({"active": False})
            elif self.operation == "enable":
                partner.write({"lf_enabled": True})
                user.write({"active": True})
            elif self.operation == "update":
                partner.write({
                    "lf_customer_company_id": self.customer_company_id.id,
                    "website_id": self.website_id.id,
                    "parent_id": False, "email": False,
                })
            user.write({"group_ids": [Command.set([
                self.env.ref("base.group_portal").id,
                self.env.ref("kai_viandas.group_corporate_employee").id,
            ])]})
        if self.operation != 'create':
            partner.signup_cancel()
            self.env.registry.clear_cache()
            user._lf_check_identity()
            partner.message_post(
                body=_("Acceso corporativo: %(operation)s. Motivo: %(reason)s",
                       operation=dict(self._fields["operation"].selection)[self.operation], reason=reason),
                author_id=actor.partner_id.id, subtype_xmlid="mail.mt_note",
            )
        # La contraseña transitoria no queda en el asistente ni en el historial.
        self.write({"new_password": False})
        action = {
            "type": "ir.actions.act_window", "res_model": "res.partner",
            "res_id": partner.id, "view_mode": "form", "target": "main",
            "views": [(self.env.ref("kai_viandas.employee_form").id, "form")],
        }
        if self.env.context.get('lf_access_feedback'):
            return {'type': 'ir.actions.client', 'tag': 'lf_operation_feedback', 'params': {
                'next': action, 'message': 'Operación de acceso completada. Los datos vigentes se muestran en la ficha.',
            }}
        return action
