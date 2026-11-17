import secrets

from odoo import api, Command, fields, models, tools, _
from odoo.exceptions import AccessError, ValidationError


# Un objeto Python no puede ser fabricado con el contexto de una llamada RPC.
_IDENTITY_OPERATION = object()


def identity_context():
    return {
        "_lf_identity_operation": _IDENTITY_OPERATION,
        "no_reset_password": True,
    }


def in_identity_operation(env):
    return env.context.get("_lf_identity_operation") is _IDENTITY_OPERATION


def check_operator(env):
    if not env.user.has_group("kai_viandas.group_operator"):
        raise AccessError(env._("Esta acción corresponde al admin La Fija operativo."))


class Website(models.Model):
    _inherit = "website"

    lf_corporate_site = fields.Boolean("Sitio corporativo de La Fija", copy=False)

    def write(self, values):
        result = super().write(values)
        if "lf_corporate_site" in values:
            self.env.registry.clear_cache()
        return result


class Partner(models.Model):
    _inherit = "res.partner"

    lf_corporate_account = fields.Boolean(
        "Cuenta corporativa de La Fija", copy=False, tracking=True,
        groups="base.group_user",
    )
    lf_customer_company_id = fields.Many2one(
        "res.partner", "Empresa cliente", domain=[("is_company", "=", True)],
        ondelete="restrict", copy=False, tracking=True, groups="base.group_user",
    )
    lf_enabled = fields.Boolean(
        "Habilitado para viandas", copy=False, tracking=True, groups="base.group_user",
    )
    lf_new_login = fields.Char(
        "Usuario", store=False, copy=False, groups="kai_viandas.group_operator",
    )
    lf_new_password = fields.Char(
        "Contraseña del portal", store=False, copy=False,
        default=lambda self: str(secrets.randbelow(900000) + 100000),
        groups="kai_viandas.group_operator",
    )
    lf_account_status = fields.Selection([
        ("missing", "Sin cuenta"), ("new", "Sin primer ingreso"),
        ("used", "Ya ingresó"), ("disabled", "Deshabilitado"),
        ("review", "Revisar acceso"),
    ], string="Estado de acceso", compute="_compute_lf_account_status", groups="base.group_user")

    @api.depends("lf_enabled", "lf_corporate_account", "lf_customer_company_id", "website_id",
                 "user_ids.active", "user_ids.login_date", "user_ids.group_ids")
    def _compute_lf_account_status(self):
        for partner in self:
            users = partner.sudo().with_context(active_test=False).user_ids
            if not users:
                state = "missing"
            elif len(users) != 1:
                state = "review"
            elif not users.active or not partner.lf_enabled:
                state = "disabled"
            elif not users._lf_can_use_site(partner.website_id):
                state = "review"
            else:
                state = "used" if users.login_date else "new"
            partner.lf_account_status = state

    def _lf_check_editor(self):
        if in_identity_operation(self.env):
            return
        if self.env.su and not self.env.user._lf_is_corporate_subject():
            return
        raise AccessError(_("Usá la ficha del empleado o Cambiar contraseña para modificar la cuenta corporativa."))

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        if self.env.context.get("lf_employee_form") and "website_id" in names and not values.get("website_id"):
            sites = self.env["website"].search([("lf_corporate_site", "=", True)], limit=2)
            if len(sites) == 1:
                values["website_id"] = sites.id
        return values

    def _lf_create_employees_from_form(self, prepared):
        check_operator(self.env)
        partners = self.env["res.partner"]
        for login, password, values in prepared:
            company = self.env["res.partner"].browse(values.get("lf_customer_company_id"))
            website = self.env["website"].browse(values.get("website_id"))
            partner, _user = self.env["lafija.employee.onboarding"]._create_identity(
                name=values.get("name"), login=login, password=password,
                company=company, website=website, reason="Alta de empleado",
            )
            partners |= partner
        return partners

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("lf_employee_form") and not in_identity_operation(self.env):
            prepared = []
            for values in values_list:
                values = dict(values)
                login = values.pop("lf_new_login", None)
                password = values.pop("lf_new_password", None)
                prepared.append((login, password, values))
            return self._lf_create_employees_from_form(prepared)
        values_list = [dict(values) for values in values_list]
        for values in values_list:
            values.pop("lf_new_login", None)
            values.pop("lf_new_password", None)
        if any(set(values) & {"lf_corporate_account", "lf_customer_company_id", "lf_enabled"}
               for values in values_list):
            self._lf_check_editor()
        records = super().create(values_list)
        if not in_identity_operation(self.env):
            records._lf_check_identity()
        return records

    def _lf_write_from_employee_form(self, values):
        check_operator(self.env)
        values = {key: value for key, value in values.items()
                  if key not in {"lf_corporate_account", "parent_id", "is_company", "email"}}
        if "lf_customer_company_id" in values:
            company = self.env["res.partner"].browse(values["lf_customer_company_id"])
            if not company.exists() or not company.is_company:
                raise ValidationError(_("Elegí una empresa cliente."))
        if "website_id" in values:
            website = self.env["website"].browse(values["website_id"])
            if not website.exists() or not website.lf_corporate_site:
                raise ValidationError(_("Elegí un sitio corporativo."))
        for partner in self.sudo():
            if not (partner.lf_corporate_account or partner.lf_customer_company_id):
                raise ValidationError(_("Este contacto no es una cuenta corporativa de La Fija."))
        ctx = identity_context()
        result = self.sudo().with_context(**ctx).write(values)
        notes = []
        if "lf_enabled" in values:
            notes.append(_("Habilitar") if values["lf_enabled"] else _("Deshabilitar"))
        if set(values) & {"lf_customer_company_id", "website_id"}:
            notes.append(_("Corregir empresa y sitio"))
        for partner in self.sudo().with_context(active_test=False):
            users = partner.user_ids
            if "lf_enabled" in values and users:
                users.with_context(**ctx).write({"active": bool(values["lf_enabled"])})
            users.with_context(**ctx)._lf_check_identity()
            if notes:
                partner.message_post(
                    body=_("Acceso corporativo: %(operation)s", operation=", ".join(str(n) for n in notes)),
                    author_id=self.env.user.partner_id.id, subtype_xmlid="mail.mt_note",
                )
        return result

    def write(self, values):
        values = dict(values)
        values.pop("lf_new_login", None)
        values.pop("lf_new_password", None)
        identity_fields = {
            "lf_corporate_account", "lf_customer_company_id", "lf_enabled",
            "parent_id", "is_company", "website_id", "email",
        }
        if (self.env.context.get("lf_employee_form") and not in_identity_operation(self.env)
                and set(values) & identity_fields):
            return self._lf_write_from_employee_form(values)
        if set(values) & identity_fields:
            if set(values) & {"lf_corporate_account", "lf_customer_company_id", "lf_enabled"}:
                self._lf_check_editor()
            elif self.sudo().filtered(lambda p: p.lf_corporate_account or p.lf_customer_company_id):
                self._lf_check_editor()
        result = super().write(values)
        if set(values) & identity_fields:
            self.env.registry.clear_cache()
            try:
                if not in_identity_operation(self.env):
                    self._lf_check_identity()
                    self.sudo().user_ids._lf_check_identity()
            finally:
                # La validación puede haber llenado cachés con un estado rechazado.
                self.env.registry.clear_cache()
        return result

    def _lf_check_identity(self):
        for partner in self.sudo():
            parent = partner.parent_id
            if parent and (parent.lf_corporate_account or parent.lf_customer_company_id
                           or any(u._lf_is_corporate_subject() for u in parent.with_context(active_test=False).user_ids)):
                raise ValidationError(_("Un empleado corporativo no puede tener subcontactos: compartirían su acceso."))
            corporate = bool(partner.lf_corporate_account or partner.lf_customer_company_id or partner.lf_enabled)
            if partner.email_normalized and partner.with_context(active_test=False).user_ids:
                others = self.sudo().with_context(active_test=False).search([
                    ("email_normalized", "=", partner.email_normalized), ("id", "!=", partner.id), ("user_ids", "!=", False),
                ])
                if any(bool(p.lf_corporate_account or p.lf_customer_company_id) != corporate for p in others):
                    raise ValidationError(_("Las cuentas particulares y corporativas deben usar emails distintos."))
            if not (partner.lf_corporate_account or partner.lf_customer_company_id or partner.lf_enabled):
                continue
            if (not partner.lf_corporate_account or partner.parent_id or partner.is_company
                    or partner.child_ids
                    or not partner.lf_customer_company_id.is_company
                    or partner.lf_customer_company_id == partner
                    or not partner.website_id.lf_corporate_site):
                raise ValidationError(_("La cuenta corporativa necesita un contacto independiente, empresa y sitio corporativo."))
            users = partner.with_context(active_test=False).user_ids
            if len(users) > 1 or (partner.lf_enabled and len(users) != 1):
                raise ValidationError(_("Cada empleado habilitado debe tener una única cuenta individual."))

    def action_lf_manage_access(self):
        check_operator(self.env)
        self.ensure_one()
        partner = self.sudo()
        users = partner.with_context(active_test=False).user_ids
        if not (partner.lf_corporate_account or partner.lf_customer_company_id
                or any(user._lf_is_corporate_subject() for user in users)):
            raise ValidationError(_("Este contacto no es una cuenta corporativa de La Fija."))
        return {
            "type": "ir.actions.act_window", "name": _("Gestionar acceso"),
            "res_model": "lafija.employee.access", "view_mode": "form", "target": "new",
            "context": {
                "default_employee_id": self.id,
                "default_operation": "enable" if partner.lf_account_status == "disabled" else "update",
                "default_customer_company_id": partner.lf_customer_company_id.id,
                "default_website_id": partner.website_id.id,
            },
        }

    def action_lf_create_employee(self):
        check_operator(self.env)
        action = self.env["ir.actions.act_window"]._for_xml_id("kai_viandas.employee_access_action")
        # Solo reutilizar una empresa elegida explícitamente, nunca la primera de la base.
        companies = self.mapped("lf_customer_company_id")
        sites = self.mapped("website_id")
        action["context"] = {
            "default_customer_company_id": companies.id if len(companies) == 1 else False,
            "default_website_id": sites.id if len(sites) == 1 else False,
        }
        if not action["context"]["default_website_id"]:
            action["context"].pop("default_website_id")
        return action

    def action_lf_change_password(self):
        check_operator(self.env)
        if not self:
            raise ValidationError(_("Seleccioná al menos un empleado."))
        users = self.env["res.users"]
        for partner in self.sudo().with_context(active_test=False):
            emp_users = partner.user_ids
            if (len(emp_users) != 1 or not emp_users.share
                    or not (partner.lf_corporate_account or emp_users._lf_is_corporate_subject())):
                raise ValidationError(
                    _("Seleccioná empleados corporativos con su cuenta individual.")
                )
            users |= emp_users
        wizard = self.env["change.password.wizard"].sudo().with_context(
            active_model="res.users",
            active_ids=users.ids,
            lf_change_employee_password=True,
        ).create({
            "user_ids": [Command.create({"user_id": user.id, "user_login": user.login})
                         for user in users],
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Cambiar contraseña"),
            "res_model": "change.password.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "view_id": self.env.ref("base.change_password_wizard_view").id,
            "target": "new",
            "context": {"lf_change_employee_password": True},
        }


class Users(models.Model):
    _inherit = "res.users"

    @tools.ormcache("self.id")
    def _lf_is_corporate_subject(self):
        self.ensure_one()
        user = self.sudo()
        partner = user.partner_id
        return bool(
            user.has_group("kai_viandas.group_corporate_employee")
            or partner.lf_corporate_account or partner.lf_customer_company_id
            or user.website_id.lf_corporate_site
        )

    def _lf_can_use_site(self, website):
        self.ensure_one()
        user = self.sudo()
        partner = user.partner_id
        return bool(
            user.active and user.share
            and user.has_group("kai_viandas.group_corporate_employee")
            and partner.lf_corporate_account and partner.lf_enabled
            and not partner.parent_id and not partner.is_company
            and not partner.child_ids
            and partner.lf_customer_company_id.is_company
            and website.lf_corporate_site and user.website_id == website
        )

    def _lf_check_identity(self):
        for user in self.sudo():
            user.partner_id._lf_check_identity()
            if not user._lf_is_corporate_subject():
                continue
            partner = user.partner_id
            if (not user.share or not user.has_group("kai_viandas.group_corporate_employee")
                    or not partner.lf_corporate_account):
                raise ValidationError(_("Grupo y marca corporativa deben establecerse juntos mediante Gestionar acceso."))

    @api.model_create_multi
    def create(self, values_list):
        users = super().create(values_list)
        self.env.registry.clear_cache()
        try:
            if not in_identity_operation(self.env):
                users._lf_check_identity()
        finally:
            self.env.registry.clear_cache()
        return users

    def write(self, values):
        sensitive = {"password", "login", "email", "group_ids", "partner_id", "website_id", "active"}
        if set(values) & sensitive:
            corporate = self.filtered(lambda user: user._lf_is_corporate_subject())
            if corporate:
                corporate.partner_id._lf_check_editor()
        result = super().write(values)
        if set(values) & sensitive:
            self.env.registry.clear_cache()
            try:
                if not in_identity_operation(self.env):
                    self._lf_check_identity()
            finally:
                self.env.registry.clear_cache()
        return result

    def _notify_security_setting_update(self, subject, content, mail_values=None, **kwargs):
        ordinary = self.filtered(lambda user: not user._lf_is_corporate_subject())
        if not ordinary:
            return self.env["mail.mail"]
        return super(Users, ordinary)._notify_security_setting_update(
            subject, content, mail_values=mail_values, **kwargs,
        )


class Groups(models.Model):
    _inherit = "res.groups"

    def write(self, values):
        membership_change = bool(set(values) & {"user_ids", "all_user_ids", "implied_ids"})
        before = self.sudo().all_user_ids if membership_change else self.env["res.users"]
        result = super().write(values)
        if membership_change:
            self.env.registry.clear_cache()
            try:
                if not in_identity_operation(self.env):
                    (before | self.sudo().all_user_ids)._lf_check_identity()
            finally:
                self.env.registry.clear_cache()
        return result


class ChangePasswordUser(models.TransientModel):
    _inherit = "change.password.user"

    def change_password_button(self):
        corporate = self.filtered(lambda line: line.user_id.sudo()._lf_is_corporate_subject())
        ordinary = self - corporate
        if ordinary:
            super(ChangePasswordUser, ordinary).change_password_button()
        if not corporate:
            return
        if not (self.env.user.has_group("kai_viandas.group_operator")
                or self.env.user.has_group("base.group_erp_manager")):
            raise AccessError(_("Esta acción corresponde al admin La Fija operativo."))
        ctx = identity_context()
        for line in corporate:
            if not (line.new_passwd or "").strip():
                continue
            user = line.user_id.sudo().with_context(**ctx)
            user._change_password(line.new_passwd)
            user.partner_id.signup_cancel()
            user.partner_id.message_post(
                body=_("Acceso corporativo: Cambiar contraseña"),
                author_id=self.env.user.partner_id.id, subtype_xmlid="mail.mt_note",
            )
        self.env.registry.clear_cache()
        corporate.write({"new_passwd": False})
