from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class KaiWhatsappAiSpec(models.Model):
    """Operator-maintained technical sheet. Unknown means the assistant must not guess."""
    _name = 'kai.whatsapp.ai.spec'
    _description = 'WhatsApp AI Product Sheet'
    _order = 'product_id, id'
    _rec_name = 'product_id'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    product_id = fields.Many2one(
        'product.product', required=True, check_company=True, ondelete='restrict',
        domain="[('sale_ok', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    role = fields.Selection([
        ('jar', 'Jar / container'),
        ('closure', 'Closure'),
        ('other', 'Other'),
    ], string='Role', default='other', required=True)
    capacity = fields.Float(string='Capacity')
    capacity_uom = fields.Char(string='Capacity unit', help="For example ml or g. Leave empty if it is not loaded.")
    material = fields.Selection([
        ('glass', 'Glass'),
        ('pet', 'PET'),
        ('pp', 'PP'),
        ('other', 'Other'),
        ('unknown', 'Not loaded'),
    ], default='unknown', required=True)
    finish = fields.Char(string='Mouth / finish', help="Free text kept for older sheets. Prefer mouth diameter and thread type.")
    mouth_mm = fields.Float(string='Mouth diameter (mm)')
    thread_type = fields.Selection([
        ('to', 'TO / twist-off'),
        ('rosca', 'Screw / rosca'),
        ('other', 'Other'),
        ('unknown', 'Not loaded'),
    ], default='unknown', required=True)
    height_mm = fields.Float(string='Height (mm)')
    diameter_mm = fields.Float(string='Body diameter (mm)')
    colour = fields.Char(string='Colour')
    min_order_qty = fields.Float(string='Minimum order', help="In the product sales unit. Empty means it is not loaded.")
    food_grade = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
        ('unknown', 'Not loaded'),
    ], string='Food grade', default='unknown', required=True)
    hot_fill = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
        ('unknown', 'Not loaded'),
    ], string='Hot fill', default='unknown', required=True)
    pasteurization = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
        ('unknown', 'Not loaded'),
    ], default='unknown', required=True)
    uses = fields.Text(string='Loaded uses', help="Activities this product is loaded for. The assistant repeats this text and does not add others.")
    pack_name = fields.Char(string='Pack name', help="For example Caja. Leave empty if packs are not loaded.")
    pack_units = fields.Float(string='Units per pack', help="How many sales units are in one pack. Empty means the assistant must ask.")

    _spec_product_unique = models.UniqueIndex("(company_id, product_id)")

    @api.constrains('product_id', 'company_id', 'pack_units')
    def _check_product(self):
        for spec in self:
            product = spec.product_id
            if product.company_id and product.company_id != spec.company_id:
                raise ValidationError(_("%s belongs to another company.", product.display_name))
            if spec.pack_units and spec.pack_units <= 0:
                raise ValidationError(_("Units per pack have to be greater than zero."))

    def _public_dict(self):
        self.ensure_one()
        return {
            'role': self.role,
            'capacity': self.capacity or None,
            'capacity_uom': self.capacity_uom or '',
            'material': self.material,
            'finish': self.finish or '',
            'mouth_mm': self.mouth_mm or None,
            'thread_type': self.thread_type,
            'height_mm': self.height_mm or None,
            'diameter_mm': self.diameter_mm or None,
            'colour': self.colour or '',
            'min_order_qty': self.min_order_qty or None,
            'food_grade': self.food_grade,
            'hot_fill': self.hot_fill,
            'pasteurization': self.pasteurization,
            'uses': self.uses or '',
        }


class KaiWhatsappAiAdvisory(models.Model):
    _name = 'kai.whatsapp.ai.advisory'
    _description = 'WhatsApp AI Activity Guide'
    _order = 'activity, sequence, id'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    activity = fields.Char(required=True, help="For example miel, mermelada, cosmética, pickles, salsas.")
    product_id = fields.Many2one(
        'product.product', required=True, check_company=True, ondelete='restrict',
        domain="[('sale_ok', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    note = fields.Text(help="The only recommendation text the assistant may repeat for this activity.")

    @api.constrains('product_id', 'company_id')
    def _check_product(self):
        for row in self:
            if row.product_id.company_id and row.product_id.company_id != row.company_id:
                raise ValidationError(_("%s belongs to another company.", row.product_id.display_name))


class KaiWhatsappAiFit(models.Model):
    _name = 'kai.whatsapp.ai.fit'
    _description = 'WhatsApp AI Jar and Closure Fit'
    _order = 'jar_product_id, id'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    jar_product_id = fields.Many2one(
        'product.product', string='Jar / container', required=True, check_company=True, ondelete='restrict',
        domain="[('sale_ok', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    closure_product_id = fields.Many2one(
        'product.product', string='Closure', required=True, check_company=True, ondelete='restrict',
        domain="[('sale_ok', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    note = fields.Text()

    _fit_unique = models.UniqueIndex("(company_id, jar_product_id, closure_product_id)")

    @api.constrains('jar_product_id', 'closure_product_id', 'company_id')
    def _check_products(self):
        for fit in self:
            if fit.jar_product_id == fit.closure_product_id:
                raise ValidationError(_("The jar and the closure have to be different products."))
            for product in (fit.jar_product_id, fit.closure_product_id):
                if product.company_id and product.company_id != fit.company_id:
                    raise ValidationError(_("%s belongs to another company.", product.display_name))
