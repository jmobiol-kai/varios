from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
    api_base_url = fields.Char(
        string='API base URL',
        help="OpenAI-compatible root, without /chat/completions. Example shape: https://host.example/v1")
    api_model = fields.Char(string='Model')
    api_key = fields.Char(
        string='API secret', copy=False, groups='kai_whatsapp_ai.group_manager',
        help="Sent only as a bearer token. It is not copied onto suggestions and it is stripped from errors.")
    api_timeout = fields.Integer(string='Timeout (seconds)', default=15)
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
        specific = self.search(domain + [('account_id', '=', account.id)], limit=1)
        if specific:
            return specific
        return self.search(domain + [('account_id', '=', False)], limit=1)


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
