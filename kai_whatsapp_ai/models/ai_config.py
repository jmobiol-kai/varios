from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.kai_whatsapp_ai.services import engine


class KaiWhatsappAiConfig(models.Model):
    """One provider setup per company, optionally narrowed to one WhatsApp account.

    ``enabled`` stays off until someone fills the endpoint and turns it on.
    Turning it on only creates suggestions. Nothing here sends WhatsApp.
    """
    _name = 'kai.whatsapp.ai.config'
    _description = 'WhatsApp AI Provider'
    _order = 'company_id, account_id, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    enabled = fields.Boolean(
        string='Enabled', default=False,
        help="Off: inbound WhatsApp messages do not call the provider and no suggestion is created. "
             "On: a suggestion is prepared for a person to review. The module never sends by itself.")
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True)
    account_id = fields.Many2one(
        'om.whatsapp.account', string='WhatsApp Account', check_company=True, ondelete='cascade',
        help="Empty: this setup is the company fallback. Set: it is used only for that account.")
    client_label = fields.Char(
        string='Client label',
        help="Name used on the monthly usage report. It is copied onto each consultation and does not change past rows.")
    provider_preset = fields.Selection([
        ('manual', 'Manual'),
        ('gemini_flash_lite', 'Gemini 2.5 Flash-Lite'),
        ('grok', 'Grok'),
    ], string='Provider preset', default='manual', groups='kai_whatsapp_ai.group_manager',
        help="Choosing a preset fills the URL and the model. It does not enable the provider and it does not store a key.")
    api_base_url = fields.Char(
        string='API base URL', groups='kai_whatsapp_ai.group_manager',
        help="OpenAI-compatible root, without /chat/completions. "
             "Gemini Flash-Lite: https://generativelanguage.googleapis.com/v1beta/openai")
    api_model = fields.Char(string='Model', groups='kai_whatsapp_ai.group_manager')
    api_key = fields.Char(
        string='API secret', copy=False, groups='kai_whatsapp_ai.group_manager',
        help="Sent only as a bearer token. It is not copied onto suggestions and it is stripped from errors.")
    api_timeout = fields.Integer(
        string='Timeout (seconds)', default=15, groups='kai_whatsapp_ai.group_manager')
    vision_supported = fields.Boolean(
        string='Provider can read photos', default=False, groups='kai_whatsapp_ai.group_manager',
        help="Gemini Flash-Lite can. Grok is left off until you know the endpoint accepts images. "
             "This does not send photos by itself.")
    allow_images = fields.Boolean(
        string='Interpret customer photos', default=False, groups='kai_whatsapp_ai.group_manager',
        help="Off by default. When on, accepted photos are sent to the external provider.")
    max_image_bytes = fields.Integer(
        string='Max photo size (bytes)', default=4 * 1024 * 1024, groups='kai_whatsapp_ai.group_manager')
    allowed_image_mimes = fields.Char(
        string='Allowed photo types', default='image/jpeg,image/png,image/webp',
        groups='kai_whatsapp_ai.group_manager')
    auto_reply_trainer = fields.Boolean(
        string='Responder automáticamente al entrenador', default=False,
        groups='kai_whatsapp_ai.group_manager',
        help="Off: a person sends the trainer's WhatsApp reply. On: an authorized trainer number "
             "receives the reply on WhatsApp. Customer replies are never sent by this option. "
             "The internal Discuss chat with Agente IA replies by itself when the provider is on.")

    @api.onchange('provider_preset')
    def _onchange_provider_preset(self):
        preset = engine.provider_preset(self.provider_preset)
        if not preset:
            return
        self.api_base_url = preset.get('api_base_url') or False
        self.api_model = preset.get('api_model') or False
        self.vision_supported = bool(preset.get('vision_supported'))
        self.allow_images = False
        self.enabled = False
    faq_ids = fields.One2many('kai.whatsapp.ai.faq', 'config_id', string='FAQ')
    catalog_ids = fields.One2many('kai.whatsapp.ai.catalog', 'config_id', string='Catalog')

    _config_account_unique = models.UniqueIndex(
        "(company_id, account_id) WHERE account_id IS NOT NULL")
    _config_company_unique = models.UniqueIndex(
        "(company_id) WHERE account_id IS NULL")

    @api.constrains('enabled', 'api_base_url', 'api_model', 'api_key', 'api_timeout')
    def _check_enabled_has_provider(self):
        for config in self:
            if config.api_timeout and (config.api_timeout < 1 or config.api_timeout > 15):
                raise ValidationError(_("The provider timeout must be between 1 and 15 seconds."))
            if config.enabled and not (config.api_base_url and config.api_model and config.api_key):
                raise ValidationError(_("Set the API base URL, the model and the secret before enabling suggestions."))

    @api.constrains('account_id', 'company_id')
    def _check_account_company(self):
        for config in self:
            if config.account_id and config.account_id.company_id != config.company_id:
                raise ValidationError(_("The WhatsApp account belongs to another company."))

    @api.model
    def _for_account(self, account):
        """Enabled setup for this account, else the enabled company fallback. Never another company."""
        if not account or not account.company_id:
            return self.browse()
        domain = [('enabled', '=', True), ('company_id', '=', account.company_id.id), ('active', '=', True)]
        specific = self.sudo().search(domain + [('account_id', '=', account.id)], limit=1)
        if specific:
            return specific
        return self.sudo().search(domain + [('account_id', '=', False)], limit=1)

    @api.model
    def _enabled_for_company(self, company):
        """Enabled company setup. Account-specific rows are not used for the internal chat."""
        if not company:
            return self.browse()
        return self.sudo().search([
            ('enabled', '=', True), ('active', '=', True),
            ('company_id', '=', company.id), ('account_id', '=', False),
        ], limit=1) or self.sudo().search([
            ('enabled', '=', True), ('active', '=', True), ('company_id', '=', company.id),
        ], limit=1)


class KaiWhatsappAiFaq(models.Model):
    _name = 'kai.whatsapp.ai.faq'
    _description = 'WhatsApp AI FAQ'
    _order = 'sequence, id'

    config_id = fields.Many2one('kai.whatsapp.ai.config', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='config_id.company_id', store=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    question = fields.Char(required=True, translate=True)
    answer = fields.Text(
        required=True, translate=True,
        help="The text a reviewer may send. Write only facts you want repeated. "
             "Hours, payment and delivery stay empty until you type them here.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('config_id'):
                continue
            company_id = vals.get('company_id') or self.env.company.id
            config = self.env['kai.whatsapp.ai.config'].sudo().search([
                ('company_id', '=', company_id), ('account_id', '=', False),
            ], limit=1) or self.env['kai.whatsapp.ai.config'].sudo().search([
                ('company_id', '=', company_id),
            ], limit=1)
            if not config:
                raise UserError(_("An administrator has to set up the assistant before an FAQ answer can be saved."))
            vals['config_id'] = config.id
        return super().create(vals_list)


class KaiWhatsappAiCatalog(models.Model):
    _name = 'kai.whatsapp.ai.catalog'
    _description = 'WhatsApp AI Catalog Product'
    _order = 'sequence, id'

    config_id = fields.Many2one('kai.whatsapp.ai.config', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='config_id.company_id', store=True, index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', required=True, check_company=True, ondelete='restrict',
        domain="[('sale_ok', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")

    _catalog_product_unique = models.UniqueIndex("(config_id, product_id)")

    @api.constrains('product_id', 'company_id')
    def _check_product_company(self):
        for line in self:
            product = line.product_id
            if not product.sale_ok:
                raise ValidationError(_("%s is not sold.", product.display_name))
            if product.company_id and product.company_id != line.company_id:
                raise ValidationError(_("%s belongs to another company.", product.display_name))
