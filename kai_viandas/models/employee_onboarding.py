"""Alta propia compartida; los métodos privados no son una API de importación."""
import hashlib

from odoo import api, Command, models, _
from odoo.exceptions import ValidationError

from .identity import check_operator, identity_context


class EmployeeOnboarding(models.AbstractModel):
    _name = 'lafija.employee.onboarding'
    _description = 'Alta individual de identidad corporativa'

    @api.model
    def _lock_logins(self, logins):
        # Por identificador, también entre sitios. No cambiar la unicidad nativa.
        # No esperar un padrón largo desde una petición de alta individual.
        for login in sorted(set(logins)):
            key = int.from_bytes(hashlib.sha256(login.encode()).digest()[:8], 'big', signed=True)
            self.env.cr.execute('SELECT pg_try_advisory_xact_lock(%s)', [key])
            if not self.env.cr.fetchone()[0]:
                raise ValidationError(_('Otra alta está usando uno de estos usuarios. Volvé a validar e intentá nuevamente.'))

    @api.model
    def _existing_logins(self, logins):
        if not logins:
            return set()
        # La transacción HTTP puede tener una foto anterior a la adquisición del
        # bloqueo. Leer también una conexión nueva detecta el alta ya confirmada.
        # La conexión actual incluye las cuentas aún sin confirmar de este lote.
        sql = 'SELECT login FROM res_users WHERE login = ANY(%s)'
        self.env['res.users'].flush_model(['login'])
        self.env.cr.execute(sql, [list(logins)])
        found = {row[0] for row in self.env.cr.fetchall()}
        with self.env.registry.cursor() as fresh:
            fresh.execute(sql, [list(logins)])
            found.update(row[0] for row in fresh.fetchall())
        return found

    @api.model
    def _create_identity(self, *, name, login, password, company, website, reason, batch_reference=None):
        check_operator(self.env)
        name, login = (name or '').strip(), (login or '').strip()
        if not name or not login:
            raise ValidationError(_('Completá nombre y usuario.'))
        if not (password or '').strip():
            raise ValidationError(_('Completá la contraseña.'))
        if not company.exists().is_company or not website.exists().lf_corporate_site:
            raise ValidationError(_('Elegí una empresa cliente y un sitio corporativo.'))
        self._lock_logins([login])
        if self._existing_logins([login]):
            raise ValidationError(_('Ese usuario ya está en uso. Elegí otro identificador.'))
        ctx = identity_context()
        partner = self.env['res.partner'].sudo().with_context(**ctx).create({
            'name': name, 'email': False, 'parent_id': False, 'is_company': False,
            'lf_corporate_account': True, 'lf_enabled': True,
            'lf_customer_company_id': company.id, 'website_id': website.id,
        })
        user = self.env['res.users'].sudo().with_context(**ctx).create({
            'partner_id': partner.id, 'login': login, 'password': password, 'email': False,
            'group_ids': [Command.set([self.env.ref('base.group_portal').id,
                                       self.env.ref('kai_viandas.group_corporate_employee').id])],
        })
        partner.signup_cancel()
        self.env.registry.clear_cache()
        user._lf_check_identity()
        body = _('Acceso corporativo: Alta de empleado. Motivo: %(reason)s', reason=reason)
        if batch_reference:
            body += _(' Lote: %(batch)s.', batch=batch_reference)
        partner.message_post(body=body, author_id=self.env.user.partner_id.id, subtype_xmlid='mail.mt_note')
        return partner, user
