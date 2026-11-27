from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.kai_whatsapp_ai.services import engine


class KaiWhatsappAiProviderRate(models.Model):
    """Operator estimate of the provider price. Not a vendor invoice."""
    _name = 'kai.whatsapp.ai.provider.rate'
    _description = 'WhatsApp AI Provider Rate'
    _order = 'date_start desc, id desc'

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    account_id = fields.Many2one('om.whatsapp.account', check_company=True, ondelete='cascade')
    provider_preset = fields.Selection([
        ('manual', 'Manual'),
        ('gemini_flash_lite', 'Gemini 3.5 Flash-Lite'),
        ('grok', 'Grok'),
    ], required=True, default='manual', groups='kai_whatsapp_ai.group_cost_viewer')
    model_name = fields.Char(string='Model', required=True, groups='kai_whatsapp_ai.group_cost_viewer')
    date_start = fields.Datetime(required=True)
    date_end = fields.Datetime()
    input_rate_set = fields.Boolean(string='Price input tokens', groups='kai_whatsapp_ai.group_cost_viewer')
    input_per_million = fields.Float(
        string='USD per 1M input tokens', digits=(16, 6), groups='kai_whatsapp_ai.group_cost_viewer')
    output_rate_set = fields.Boolean(string='Price output tokens', groups='kai_whatsapp_ai.group_cost_viewer')
    output_per_million = fields.Float(
        string='USD per 1M output tokens', digits=(16, 6), groups='kai_whatsapp_ai.group_cost_viewer')
    cached_rate_set = fields.Boolean(string='Price cached tokens', groups='kai_whatsapp_ai.group_cost_viewer')
    cached_per_million = fields.Float(
        string='USD per 1M cached tokens', digits=(16, 6), groups='kai_whatsapp_ai.group_cost_viewer')
    thinking_rate_set = fields.Boolean(string='Price thinking tokens', groups='kai_whatsapp_ai.group_cost_viewer')
    thinking_per_million = fields.Float(
        string='USD per 1M thinking tokens', digits=(16, 6), groups='kai_whatsapp_ai.group_cost_viewer')

    def _as_engine_row(self):
        self.ensure_one()
        return {
            'id': self.id,
            'company_id': self.company_id.id,
            'account_id': self.account_id.id or False,
            'provider_preset': self.provider_preset,
            'model_name': self.model_name,
            'date_start': self.date_start,
            'date_end': self.date_end,
            'name': self.name,
            'input_per_million': self.input_per_million if self.input_rate_set else None,
            'output_per_million': self.output_per_million if self.output_rate_set else None,
            'cached_per_million': self.cached_per_million if self.cached_rate_set else None,
            'thinking_per_million': self.thinking_per_million if self.thinking_rate_set else None,
        }


class KaiWhatsappAiBillableRate(models.Model):
    """What the operator bills per consultation. Empty until a rate is saved."""
    _name = 'kai.whatsapp.ai.billable.rate'
    _description = 'WhatsApp AI Client Rate'
    _order = 'date_start desc, id desc'

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    account_id = fields.Many2one('om.whatsapp.account', check_company=True, ondelete='cascade')
    client_label = fields.Char()
    date_start = fields.Datetime(required=True)
    date_end = fields.Datetime()
    currency_id = fields.Many2one('res.currency', required=True)
    amount_per_consultation = fields.Monetary(currency_field='currency_id', required=True)

    def _as_engine_row(self):
        self.ensure_one()
        return {
            'id': self.id,
            'company_id': self.company_id.id,
            'account_id': self.account_id.id or False,
            'client_label': self.client_label or '',
            'date_start': self.date_start,
            'date_end': self.date_end,
            'amount': self.amount_per_consultation,
            'currency': self.currency_id.name or '',
            'currency_id': self.currency_id.id,
        }


class KaiWhatsappAiConsultation(models.Model):
    """One billable incoming customer text. Retries do not create another."""
    _name = 'kai.whatsapp.ai.consultation'
    _description = 'WhatsApp AI Consultation'
    _order = 'occurred_at desc, id desc'

    suggestion_id = fields.Many2one('kai.whatsapp.ai.suggestion', ondelete='set null', index=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    account_id = fields.Many2one('om.whatsapp.account', ondelete='cascade', index=True)
    channel_id = fields.Many2one('discuss.channel', ondelete='set null')
    message_id = fields.Many2one('mail.message', ondelete='set null')
    whatsapp_message_id = fields.Char(index=True)
    partner_id = fields.Many2one('res.partner', string='Customer')
    occurred_at = fields.Datetime(required=True, index=True)
    client_label = fields.Char(readonly=True)
    consultation_count = fields.Integer(string='Consultations', default=1, readonly=True)
    billable_known = fields.Boolean(readonly=True, groups='kai_whatsapp_ai.group_manager')
    billable_currency_id = fields.Many2one(
        'res.currency', readonly=True,
        default=lambda self: self.env.ref('base.ARS', raise_if_not_found=False),
        groups='kai_whatsapp_ai.group_trainer,kai_whatsapp_ai.group_cost_viewer')
    billable_amount = fields.Monetary(
        currency_field='billable_currency_id', readonly=True,
        groups='kai_whatsapp_ai.group_trainer,kai_whatsapp_ai.group_cost_viewer')
    billable_rate_id = fields.Many2one(
        'kai.whatsapp.ai.billable.rate', readonly=True, groups='kai_whatsapp_ai.group_manager')
    has_image = fields.Boolean(string='Photo', readonly=True)
    call_ids = fields.One2many('kai.whatsapp.ai.call', 'consultation_id')
    provider_cost_usd = fields.Float(
        string='Provider cost (USD)', digits=(16, 6),
        compute='_compute_provider_cost_usd', store=True,
        groups='kai_whatsapp_ai.group_cost_viewer')

    _PROVIDER_COST_FIELDS = frozenset({'provider_cost_usd'})

    _consultation_whatsapp_unique = models.UniqueIndex(
        "(account_id, whatsapp_message_id) WHERE whatsapp_message_id IS NOT NULL")
    _consultation_message_unique = models.UniqueIndex(
        "(message_id) WHERE message_id IS NOT NULL")

    @api.depends('call_ids.cost_usd', 'call_ids.cost_known')
    def _compute_provider_cost_usd(self):
        for consultation in self:
            calls = consultation.sudo().call_ids.filtered('cost_known')
            consultation.provider_cost_usd = sum(calls.mapped('cost_usd'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Consultations are recorded from inbound WhatsApp messages."))
        ars = self.env.ref('base.ARS', raise_if_not_found=False)
        for vals in vals_list:
            vals.setdefault('consultation_count', 1)
            if ars:
                vals['billable_currency_id'] = ars.id
        return super().create(vals_list)

    def write(self, vals):
        if self.env.su and set(vals).issubset(self._PROVIDER_COST_FIELDS):
            return super().write(vals)
        raise UserError(_("A consultation cannot be changed."))

    def unlink(self):
        if not self.env.su:
            raise UserError(_("A consultation cannot be deleted."))
        return super().unlink()


class KaiWhatsappAiCall(models.Model):
    """One immutable provider attempt. The secret is never stored here."""
    _name = 'kai.whatsapp.ai.call'
    _description = 'WhatsApp AI Provider Call'
    _order = 'occurred_at desc, id desc'

    consultation_id = fields.Many2one('kai.whatsapp.ai.consultation', required=True, ondelete='restrict', index=True)
    suggestion_id = fields.Many2one('kai.whatsapp.ai.suggestion', ondelete='set null', index=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    account_id = fields.Many2one('om.whatsapp.account', ondelete='restrict', index=True)
    occurred_at = fields.Datetime(required=True, index=True)
    attempt = fields.Integer(required=True)
    outcome = fields.Selection([('success', 'Succeeded'), ('failed', 'Failed')], required=True)
    latency_ms = fields.Integer()
    provider_preset = fields.Selection([
        ('manual', 'Manual'),
        ('gemini_flash_lite', 'Gemini 3.5 Flash-Lite'),
        ('grok', 'Grok'),
    ], required=True, groups='kai_whatsapp_ai.group_cost_viewer')
    provider_label = fields.Char(required=True, groups='kai_whatsapp_ai.group_cost_viewer')
    model_name = fields.Char(string='Model', required=True, groups='kai_whatsapp_ai.group_cost_viewer')
    endpoint_host = fields.Char(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    error_sanitized = fields.Char(readonly=True)
    client_label = fields.Char(readonly=True)
    input_known = fields.Boolean(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    input_tokens = fields.Integer(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    input_tokens_display = fields.Char(
        string='Input tokens', compute='_compute_token_display', groups='kai_whatsapp_ai.group_cost_viewer')
    output_known = fields.Boolean(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    output_tokens = fields.Integer(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    output_tokens_display = fields.Char(
        string='Output tokens', compute='_compute_token_display', groups='kai_whatsapp_ai.group_cost_viewer')
    cached_known = fields.Boolean(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    cached_tokens = fields.Integer(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    cached_tokens_display = fields.Char(
        string='Cached tokens', compute='_compute_token_display', groups='kai_whatsapp_ai.group_cost_viewer')
    thinking_known = fields.Boolean(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    thinking_tokens = fields.Integer(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    thinking_tokens_display = fields.Char(
        string='Thinking tokens', compute='_compute_token_display', groups='kai_whatsapp_ai.group_cost_viewer')
    cost_display = fields.Char(
        string='Estimated USD', compute='_compute_token_display', groups='kai_whatsapp_ai.group_cost_viewer')

    @api.depends(
        'input_known', 'input_tokens', 'output_known', 'output_tokens',
        'cached_known', 'cached_tokens', 'thinking_known', 'thinking_tokens',
        'cost_known', 'cost_usd')
    def _compute_token_display(self):
        for call in self:
            call.input_tokens_display = str(call.input_tokens) if call.input_known else ''
            call.output_tokens_display = str(call.output_tokens) if call.output_known else ''
            call.cached_tokens_display = str(call.cached_tokens) if call.cached_known else ''
            call.thinking_tokens_display = str(call.thinking_tokens) if call.thinking_known else ''
            call.cost_display = f'{call.cost_usd:.6f}' if call.cost_known else ''

    rate_id = fields.Many2one(
        'kai.whatsapp.ai.provider.rate', readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    rate_name = fields.Char(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    input_per_million = fields.Float(digits=(16, 6), readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    output_per_million = fields.Float(digits=(16, 6), readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    cached_per_million = fields.Float(digits=(16, 6), readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    thinking_per_million = fields.Float(digits=(16, 6), readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    cost_known = fields.Boolean(readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    cost_usd = fields.Float(
        string='Estimated USD', digits=(16, 6), readonly=True, groups='kai_whatsapp_ai.group_cost_viewer')
    image_count = fields.Integer(readonly=True)
    image_tokens_known = fields.Boolean(readonly=True)
    image_tokens = fields.Integer(readonly=True)
    is_training = fields.Boolean(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Provider calls are recorded by the server."))
        for vals in vals_list:
            for key in ('api_key', 'authorization', 'secret'):
                vals.pop(key, None)
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_("A provider call log cannot be changed."))

    def unlink(self):
        if not self.env.su:
            raise UserError(_("A provider call log cannot be deleted."))
        return super().unlink()


class KaiWhatsappAiUsageWizard(models.TransientModel):
    _name = 'kai.whatsapp.ai.usage.wizard'
    _description = 'WhatsApp AI Monthly Usage'

    month = fields.Selection([
        ('1', 'January'), ('2', 'February'), ('3', 'March'), ('4', 'April'),
        ('5', 'May'), ('6', 'June'), ('7', 'July'), ('8', 'August'),
        ('9', 'September'), ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], required=True, default=lambda self: str(self._today_parts()[0]))
    year = fields.Integer(required=True, default=lambda self: self._today_parts()[1])
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    account_id = fields.Many2one('om.whatsapp.account')
    client_label = fields.Char()

    @api.model
    def _today_parts(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(self.env.user.tz or 'UTC')
        now = datetime.now(timezone.utc).astimezone(tz)
        return now.month, now.year

    def _bounds(self):
        self.ensure_one()
        return engine.month_bounds_utc(int(self.year), int(self.month), self.env.user.tz or 'UTC')

    def _domain(self, field_name):
        self.ensure_one()
        start, end = self._bounds()
        domain = [(field_name, '>=', start), (field_name, '<', end)]
        if self.company_id:
            domain.append(('company_id', '=', self.company_id.id))
        if self.account_id:
            domain.append(('account_id', '=', self.account_id.id))
        if self.client_label:
            domain.append(('client_label', '=', self.client_label))
        return domain

    def action_open_consultations(self):
        self.ensure_one()
        return self._open('kai.whatsapp.ai.consultation', self._domain('occurred_at'), 'Consultations')

    def action_open_calls(self):
        self.ensure_one()
        self._check_cost_viewer()
        return self._open('kai.whatsapp.ai.call', self._domain('occurred_at'), 'Provider calls')

    def action_fill_totals(self):
        self.ensure_one()
        start, end = self._bounds()
        consultations = self.env['kai.whatsapp.ai.consultation'].search(self._domain('occurred_at'))
        sends = self.env['kai.whatsapp.ai.suggestion'].search(
            self._domain('reply_sent_at') + [('reply_sent', '=', True)])
        quotations = self.env['kai.whatsapp.ai.suggestion'].search(
            self._domain('quotation_at') + [('sale_order_id', '!=', False)])
        customer = engine.aggregate_customer(
            [self._consultation_row(row) for row in consultations],
            [self._suggestion_row(row) for row in sends],
            [self._suggestion_row(row) for row in quotations],
        )
        Total = self.env['kai.whatsapp.ai.usage.total']
        Total.search([('create_uid', '=', self.env.uid)]).unlink()
        sees_cost = self.env.user.has_group('kai_whatsapp_ai.group_cost_viewer')
        calls = self.env['kai.whatsapp.ai.call']
        provider_rows = []
        if sees_cost:
            calls = calls.search(self._domain('occurred_at'))
            provider_rows = engine.aggregate_provider([self._call_row(row) for row in calls])
        created = Total
        for row in customer:
            created |= Total.create(self._customer_vals(row))
        if sees_cost:
            for row in provider_rows:
                created |= Total.sudo().create(self._provider_vals(row))
        action = self._open('kai.whatsapp.ai.usage.total', [('id', 'in', created.ids)], 'Monthly totals')
        if not sees_cost:
            action['view_id'] = self.env.ref('kai_whatsapp_ai.kai_whatsapp_ai_usage_total_view_list_customer').id
            action['views'] = [(action['view_id'], 'list')]
        return action

    def _check_cost_viewer(self):
        if not self.env.user.has_group('kai_whatsapp_ai.group_cost_viewer'):
            raise UserError(_("Only the cost viewer can open provider usage."))

    def _open(self, model, domain, name):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,pivot',
            'domain': domain,
            'target': 'current',
        }

    def _consultation_row(self, row):
        return {
            'company_id': row.company_id.id,
            'account_id': row.account_id.id,
            'client_label': row.client_label or '',
            'has_image': row.has_image,
            'billable_known': row.billable_known,
            'billable_amount': row.billable_amount if row.billable_known else None,
            'billable_currency': row.billable_currency_id.name or '',
        }

    def _suggestion_row(self, row):
        label = row.consultation_id.client_label or row.config_id.client_label or ''
        return {'company_id': row.company_id.id, 'account_id': row.account_id.id, 'client_label': label}

    def _call_row(self, row):
        return {
            'company_id': row.company_id.id,
            'account_id': row.account_id.id,
            'client_label': row.client_label or '',
            'provider_label': row.provider_label,
            'model': row.model_name,
            'attempt': row.attempt,
            'outcome': row.outcome,
            'input_known': row.input_known, 'input_tokens': row.input_tokens,
            'output_known': row.output_known, 'output_tokens': row.output_tokens,
            'cached_known': row.cached_known, 'cached_tokens': row.cached_tokens,
            'thinking_known': row.thinking_known, 'thinking_tokens': row.thinking_tokens,
            'cost_known': row.cost_known,
            'cost_usd': row.cost_usd if row.cost_known else None,
            'image_count': row.image_count,
            'image_known': row.image_tokens_known,
            'image_tokens': row.image_tokens,
        }

    def _customer_vals(self, row):
        currency = self.env['res.currency'].search([('name', '=', row['billable_currency'])], limit=1)
        return {
            'company_id': row['company_id'],
            'account_id': row['account_id'],
            'client_label': row['client_label'],
            'consultations': row['consultations'],
            'image_consultations': row.get('image_consultations') or 0,
            'sends': row['sends'],
            'quotations': row['quotations'],
            'billable_amount': row['billable_amount'],
            'billable_unknown': row['billable_unknown'],
            'billable_currency_id': currency.id,
            'line_kind': 'customer',
        }

    def _provider_vals(self, row):
        vals = self._customer_vals({
            'company_id': row['company_id'], 'account_id': row['account_id'],
            'client_label': row['client_label'],
            'consultations': 0, 'image_consultations': 0, 'sends': 0, 'quotations': 0,
            'billable_amount': 0.0, 'billable_unknown': 0, 'billable_currency': '',
        })
        vals.update({
            'line_kind': 'provider',
            'provider_label': row['provider_label'],
            'model_name': row['model'],
            'attempted': row['attempted'],
            'succeeded': row['succeeded'],
            'failed': row['failed'],
            'retries': row['retries'],
            'input_tokens': row['input_tokens'],
            'input_unknown': row['input_unknown'],
            'output_tokens': row['output_tokens'],
            'output_unknown': row['output_unknown'],
            'cached_tokens': row['cached_tokens'],
            'cached_unknown': row['cached_unknown'],
            'thinking_tokens': row['thinking_tokens'],
            'thinking_unknown': row['thinking_unknown'],
            'estimated_cost_usd': row['estimated_cost_usd'],
            'cost_unknown': row['cost_unknown'],
            'image_count': row.get('image_count') or 0,
            'image_tokens': row.get('image_tokens') or 0,
            'image_unknown': row.get('image_unknown') or 0,
        })
        return vals


class KaiWhatsappAiUsageTotal(models.TransientModel):
    _name = 'kai.whatsapp.ai.usage.total'
    _description = 'WhatsApp AI Usage Total'

    line_kind = fields.Selection([('customer', 'Customer summary'), ('provider', 'Provider detail')], required=True)
    company_id = fields.Many2one('res.company')
    account_id = fields.Many2one('om.whatsapp.account')
    client_label = fields.Char()
    consultations = fields.Integer()
    image_consultations = fields.Integer()
    sends = fields.Integer()
    quotations = fields.Integer()
    billable_amount = fields.Monetary(
        currency_field='billable_currency_id',
        groups='kai_whatsapp_ai.group_trainer,kai_whatsapp_ai.group_cost_viewer')
    billable_unknown = fields.Integer(groups='kai_whatsapp_ai.group_manager')
    billable_currency_id = fields.Many2one(
        'res.currency', groups='kai_whatsapp_ai.group_trainer,kai_whatsapp_ai.group_cost_viewer')
    provider_label = fields.Char(groups='kai_whatsapp_ai.group_cost_viewer')
    model_name = fields.Char(string='Model', groups='kai_whatsapp_ai.group_cost_viewer')
    attempted = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    succeeded = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    failed = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    retries = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    input_tokens = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    input_unknown = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    output_tokens = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    output_unknown = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    cached_tokens = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    cached_unknown = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    thinking_tokens = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    thinking_unknown = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    estimated_cost_usd = fields.Float(digits=(16, 6), groups='kai_whatsapp_ai.group_cost_viewer')
    cost_unknown = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    image_count = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    image_tokens = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
    image_unknown = fields.Integer(groups='kai_whatsapp_ai.group_cost_viewer')
