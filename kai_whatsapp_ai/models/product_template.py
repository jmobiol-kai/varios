from odoo import _, fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    kai_spec_ids = fields.One2many('kai.whatsapp.ai.spec', 'product_id', string='Ficha técnica')
    kai_fit_ids = fields.One2many('kai.whatsapp.ai.fit', 'jar_product_id', string='Compatibilidades')

    def action_kai_open_spec(self):
        """Open this variant's sheet, creating the empty row the first time."""
        self.ensure_one()
        spec = self.env['kai.whatsapp.ai.spec'].search([
            ('product_id', '=', self.id),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not spec:
            spec = self.env['kai.whatsapp.ai.spec'].create({
                'product_id': self.id,
                'company_id': self.env.company.id,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ficha técnica'),
            'res_model': 'kai.whatsapp.ai.spec',
            'res_id': spec.id,
            'view_mode': 'form',
            'target': 'current',
        }


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    kai_spec_id = fields.Many2one('kai.whatsapp.ai.spec', compute='_compute_kai_spec_id')
    kai_capacity = fields.Float(related='kai_spec_id.capacity', readonly=False, string='Capacidad')
    kai_capacity_uom = fields.Char(related='kai_spec_id.capacity_uom', readonly=False, string='Unidad')
    kai_material = fields.Selection(related='kai_spec_id.material', readonly=False, string='Material')
    kai_finish = fields.Char(related='kai_spec_id.finish', readonly=False, string='Boca / terminación')
    kai_mouth_mm = fields.Float(related='kai_spec_id.mouth_mm', readonly=False, string='Diámetro de boca (mm)')
    kai_thread_type = fields.Selection(related='kai_spec_id.thread_type', readonly=False, string='Tipo de rosca')
    kai_height_mm = fields.Float(related='kai_spec_id.height_mm', readonly=False, string='Alto (mm)')
    kai_diameter_mm = fields.Float(related='kai_spec_id.diameter_mm', readonly=False, string='Diámetro (mm)')
    kai_food_grade = fields.Selection(related='kai_spec_id.food_grade', readonly=False, string='Apto alimento')
    kai_hot_fill = fields.Selection(related='kai_spec_id.hot_fill', readonly=False, string='Llenado en caliente')
    kai_pasteurization = fields.Selection(related='kai_spec_id.pasteurization', readonly=False, string='Pasteurización')
    kai_uses = fields.Text(related='kai_spec_id.uses', readonly=False, string='Usos')
    kai_verified = fields.Boolean(related='kai_spec_id.verified', readonly=False, string='Verificado')
    kai_verification_note = fields.Text(
        related='kai_spec_id.verification_note', readonly=False, string='Nota de verificación')
    kai_fit_ids = fields.One2many(
        related='product_variant_id.kai_fit_ids', readonly=False, string='Compatibilidades')

    def _compute_kai_spec_id(self):
        Spec = self.env['kai.whatsapp.ai.spec']
        for template in self:
            variant = template.product_variant_id
            template.kai_spec_id = Spec.search([
                ('product_id', '=', variant.id),
                ('company_id', '=', self.env.company.id),
            ], limit=1) if variant else False

    def action_kai_ensure_spec(self):
        """Create the sheet for the single variant the first time the tab needs it."""
        self.ensure_one()
        variant = self.product_variant_id
        if not variant:
            return False
        return variant.action_kai_open_spec()
