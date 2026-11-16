from odoo import api, fields, models

from odoo.addons.kai_whatsapp_ai.services import engine


class KaiWhatsappAiRestriction(models.Model):
    """Admin-only limits. They outrank trainer rules and are not shown to the trainer."""
    _name = 'kai.whatsapp.ai.restriction'
    _description = 'WhatsApp AI Restriction'
    _order = 'sequence, id'

    name = fields.Char(string='Tema', required=True)
    audience = fields.Selection([
        ('trainer', 'Entrenador'),
        ('customer', 'Clientes'),
        ('both', 'Ambos'),
    ], string='Audiencia', required=True, default='trainer', index=True)
    description = fields.Text(string='Qué está prohibido')
    reply_text = fields.Text(
        string='Respuesta al rechazar',
        default=engine.DEFAULT_RESTRICTION_REPLY,
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True)

    def _as_engine_row(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name or '',
            'audience': self.audience,
            'description': self.description or '',
            'reply_text': self.reply_text or '',
            'active': self.active,
            'sequence': self.sequence,
            'company_id': self.company_id.id,
        }

    @api.model
    def _for_prompt(self, company, audience):
        """Rows for the prompt. sudo: the trainer must not be able to read this model."""
        if not company:
            return []
        rows = self.sudo().search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ])
        return engine.active_restrictions(
            [row._as_engine_row() for row in rows], audience, company_id=company.id)

    @api.model
    def _seed_company_named(self, company_name=None):
        """Create the 00IA seeds once. noupdate: an existing xmlid or the same topic is left as-is."""
        company_name = company_name or engine.SEED_COMPANY_NAME
        company = self.env['res.company'].sudo().search([('name', '=', company_name)], limit=1)
        if not company:
            return
        ModelData = self.env['ir.model.data'].sudo()
        for item in engine.SEED_RESTRICTIONS:
            existing = ModelData.search([
                ('module', '=', 'kai_whatsapp_ai'),
                ('name', '=', item['xmlid']),
            ], limit=1)
            if existing and self.sudo().browse(existing.res_id).exists():
                continue
            found = self.sudo().search([
                ('company_id', '=', company.id),
                ('name', '=', item['name']),
                ('audience', '=', item['audience']),
            ], limit=1)
            if found:
                continue
            record = self.sudo().create({
                'name': item['name'],
                'audience': item['audience'],
                'description': item['description'],
                'reply_text': item['reply_text'],
                'sequence': item['sequence'],
                'company_id': company.id,
                'active': True,
            })
            if existing:
                existing.write({'res_id': record.id, 'model': self._name, 'noupdate': True})
            else:
                ModelData.create({
                    'module': 'kai_whatsapp_ai',
                    'name': item['xmlid'],
                    'model': self._name,
                    'res_id': record.id,
                    'noupdate': True,
                })
