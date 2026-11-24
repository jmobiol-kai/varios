import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)

GROUP = 'kai_portal_set_password.group_portal_set_password'


class PortalPasswordWizard(models.TransientModel):
    _name = 'kai.portal.password.wizard'
    _description = 'Establecer contraseña de portal'

    partner_id = fields.Many2one('res.partner', string='Contacto', required=True, readonly=True)
    login = fields.Char(string='Usuario (login)', required=True,
                        help='Se usa solo si hay que crear el usuario de portal. Por defecto, el correo del contacto.')
    existing_user_id = fields.Many2one('res.users', string='Usuario existente',
                                       compute='_compute_existing_user', compute_sudo=True)
    user_status = fields.Char(string='Estado', compute='_compute_existing_user', compute_sudo=True)
    new_password = fields.Char(string='Nueva contraseña', required=True)
    confirm_password = fields.Char(string='Confirmar contraseña', required=True)

    # ------------------------------------------------------------------
    def _check_allowed(self):
        if not (self.env.su or self.env.user.has_group(GROUP)):
            raise AccessError(_('No tiene permiso para establecer contraseñas de portal.'))

    @api.model
    def default_get(self, fields_list):
        self._check_allowed()
        res = super().default_get(fields_list)
        ctx = self.env.context
        partner_ids = ctx.get('active_ids') or ([ctx['active_id']] if ctx.get('active_id') else [])
        if ctx.get('active_model') == 'res.partner' and partner_ids:
            if len(partner_ids) > 1:
                raise UserError(_('Seleccione un solo contacto.'))
            partner = self.env['res.partner'].browse(partner_ids[0])
            res['partner_id'] = partner.id
            user = partner.sudo().with_context(active_test=False).user_ids[:1]
            res['login'] = user.login if user else (email_normalize(partner.email or '') or partner.email or False)
        return res

    @api.depends('partner_id')
    def _compute_existing_user(self):
        for wiz in self:
            users = wiz.partner_id.with_context(active_test=False).user_ids
            user = users[:1]
            wiz.existing_user_id = user
            if not users:
                wiz.user_status = _('Sin usuario: se creará un usuario de portal (sin enviar correo).')
            elif len(users) > 1:
                wiz.user_status = _('El contacto tiene más de un usuario: no se puede usar este asistente.')
            elif not user.share or user._is_internal():
                wiz.user_status = _('Usuario INTERNO: no se puede cambiar su contraseña desde aquí.')
            elif user.has_group('base.group_portal') and user.active:
                wiz.user_status = _('Usuario de portal activo: se cambiará la contraseña.')
            else:
                wiz.user_status = _('Usuario de portal inactivo: se reactivará como portal y se cambiará la contraseña.')

    # ------------------------------------------------------------------
    def _get_or_create_portal_user(self):
        """Devuelve (en sudo) el usuario de portal del contacto, creándolo si no existe.
        Nunca devuelve ni modifica usuarios internos."""
        self.ensure_one()
        partner_sudo = self.partner_id.sudo()
        group_portal = self.env.ref('base.group_portal')
        group_public = self.env.ref('base.group_public')
        users = partner_sudo.with_context(active_test=False).user_ids
        if len(users) > 1:
            raise UserError(_('El contacto "%s" tiene más de un usuario.', partner_sudo.display_name))
        user_sudo = users
        if user_sudo:
            if not user_sudo.share or user_sudo._is_internal() or user_sudo.id in (1, 2) \
                    or user_sudo.has_group('base.group_user'):
                raise UserError(_('El contacto "%s" tiene un usuario interno: no se puede cambiar su contraseña desde aquí.',
                                  partner_sudo.display_name))
            if not user_sudo.active or not user_sudo.has_group('base.group_portal'):
                user_sudo.write({'active': True, 'groups_id': [(4, group_portal.id), (3, group_public.id)]})
        else:
            login = email_normalize(self.login or '') or (self.login or '').strip()
            if not login:
                raise UserError(_('Indique un usuario (login) para el contacto.'))
            if self.env['res.users'].sudo().with_context(active_test=False).search_count([('login', '=ilike', login)]):
                raise UserError(_('Ya existe un usuario con el login "%s".', login))
            company = self.env.company
            user_sudo = self.env['res.users'].sudo().with_context(
                no_reset_password=True, mail_create_nolog=True, mail_notrack=True,
            ).with_company(company.id)._create_user_from_template({
                'login': login,
                'email': email_normalize(partner_sudo.email or '') or partner_sudo.email or False,
                'partner_id': partner_sudo.id,
                'company_id': company.id,
                'company_ids': [(6, 0, company.ids)],
            })
            if not user_sudo.has_group('base.group_portal'):
                user_sudo.write({'groups_id': [(4, group_portal.id), (3, group_public.id)]})
        # Verificación final defensiva
        if not user_sudo.share or user_sudo._is_internal() or not user_sudo.has_group('base.group_portal'):
            raise UserError(_('El usuario resultante no es solo de portal; operación cancelada.'))
        return user_sudo

    def action_confirm(self):
        self.ensure_one()
        self._check_allowed()
        if not self.new_password or self.new_password != self.confirm_password:
            raise ValidationError(_('Las contraseñas no coinciden.'))
        user_sudo = self._get_or_create_portal_user()
        user_sudo.with_context(no_reset_password=True, mail_notrack=True, kai_no_security_mail=True).write({'password': self.new_password})
        _logger.info('Portal password set by uid %s for portal user %s (partner %s)',
                     self.env.uid, user_sudo.id, self.partner_id.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Contraseña de portal establecida'),
                'message': _('Usuario: %s', user_sudo.login),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
