from odoo import fields, models
from odoo.exceptions import AccessError


class OperatorHelp(models.Model):
    _name = 'lafija.help'
    _description = 'Ayuda de La Fija'

    name = fields.Char(default='Ayuda · La Fija', required=True)
    content = fields.Html(compute='_compute_content', sanitize=False)

    def _compute_content(self):
        if not self.env.user.has_group('kai_viandas.group_operator'):
            raise AccessError('Esta ayuda está disponible para el admin La Fija operativo.')
        for record in self:
            # Contenido de confianza, versionado en QWeb; no se edita como dato.
            record.content = self.env['ir.qweb']._render('kai_viandas.help_operator_content')
