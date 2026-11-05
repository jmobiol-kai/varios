import logging
import time
from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import plaintext2html

from odoo.addons.kai_whatsapp_ai.services import engine

_logger = logging.getLogger(__name__)


class KaiWhatsappAiSuggestion(models.Model):
    _name = 'kai.whatsapp.ai.suggestion'
    _description = 'WhatsApp AI Suggestion'
    _order = 'id desc'
    _rec_name = 'inbound_body'

    config_id = fields.Many2one('kai.whatsapp.ai.config', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='config_id.company_id', store=True, index=True)
    account_id = fields.Many2one('om.whatsapp.account', required=True, ondelete='cascade', index=True)
    channel_id = fields.Many2one('discuss.channel', ondelete='set null', index=True)
    message_id = fields.Many2one('mail.message', ondelete='set null', index=True)
    whatsapp_message_id = fields.Char(index=True, copy=False)
    consultation_id = fields.Many2one('kai.whatsapp.ai.consultation', readonly=True, copy=False)
    reply_sent_at = fields.Datetime(readonly=True, copy=False)
    quotation_at = fields.Datetime(readonly=True, copy=False)
    partner_id = fields.Many2one(
        'res.partner', string='Customer',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    inbound_body = fields.Text(readonly=True)
    intent = fields.Selection([
        ('faq', 'FAQ'),
        ('catalog', 'Catalog'),
        ('order', 'Order'),
        ('unknown', 'Unknown'),
    ], readonly=True)
    needs_human = fields.Boolean(readonly=True)
    clarification = fields.Char(readonly=True)
    suggested_reply = fields.Text(string='Reply to review')
    provider_error = fields.Char(readonly=True)
    state = fields.Selection([
        ('review', 'To review'),
        ('discarded', 'Discarded'),
    ], default='review', required=True, index=True)
    generation_state = fields.Selection([
        ('pending', 'Queued'),
        ('done', 'Ready'),
        ('error', 'Provider error'),
    ], default='pending', required=True, index=True, readonly=True)
    reply_sent = fields.Boolean(readonly=True, copy=False)
    sale_order_id = fields.Many2one('sale.order', string='Draft quotation', readonly=True, copy=False)
    line_ids = fields.One2many('kai.whatsapp.ai.suggestion.line', 'suggestion_id')
    quotation_ready = fields.Boolean(compute='_compute_quotation_ready')

    _suggestion_message_unique = models.UniqueIndex("(message_id) WHERE message_id IS NOT NULL")
    _suggestion_whatsapp_unique = models.UniqueIndex(
        "(account_id, whatsapp_message_id) WHERE whatsapp_message_id IS NOT NULL")

    @api.depends('state', 'intent', 'partner_id', 'partner_id.company_id', 'sale_order_id',
                 'channel_id.om_whatsapp_partner_id', 'company_id', 'config_id.catalog_ids.product_id',
                 'line_ids.quantity', 'line_ids.product_id', 'line_ids.uom_id', 'line_ids.product_id.uom_id',
                 'line_ids.product_id.sale_ok', 'line_ids.product_id.company_id')
    def _compute_quotation_ready(self):
        for suggestion in self:
            suggestion.quotation_ready = suggestion._quotation_is_valid()

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Suggestions are created from inbound WhatsApp messages."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if set(vals) - {'suggested_reply', 'partner_id'}:
                raise UserError(_("Only the reply text and the customer can be edited."))
            if 'partner_id' in vals:
                partner = self.env['res.partner'].browse(vals['partner_id']).exists() if vals['partner_id'] else self.env['res.partner']
                for suggestion in self:
                    suggestion._check_partner_value(partner)
        return super().write(vals)

    def _check_partner_value(self, partner):
        self.ensure_one()
        if not partner:
            return
        if partner.company_id and partner.company_id != self.company_id:
            raise UserError(_("The customer belongs to another company."))
        channel_partner = self.channel_id.om_whatsapp_partner_id
        if channel_partner and partner != channel_partner:
            raise UserError(_("The customer must be the contact of this WhatsApp conversation."))

    def _quotation_is_valid(self):
        self.ensure_one()
        partner = self.partner_id
        company = self.company_id
        pricelist = partner.with_company(company).property_product_pricelist if partner else False
        catalog_ids = set(self.config_id.catalog_ids.product_id.ids)
        lines = []
        for line in self.line_ids:
            product = line.product_id
            lines.append({
                'product_id': product.id,
                'sale_ok': bool(product.sale_ok) if product else False,
                'product_company_id': product.company_id.id if product and product.company_id else False,
                'product_uom_id': product.uom_id.id if product and product.uom_id else False,
                'uom_id': line.uom_id.id,
                'quantity': line.quantity,
                'in_catalog': bool(product) and product.id in catalog_ids,
            })
        return engine.validated_quotation(
            discarded=self.state == 'discarded',
            intent=self.intent,
            partner_id=partner.id,
            partner_company_id=partner.company_id.id if partner and partner.company_id else False,
            company_id=company.id,
            channel_partner_id=self.channel_id.om_whatsapp_partner_id.id or False,
            has_pricelist=bool(pricelist),
            pricelist_company_id=pricelist.company_id.id if pricelist and pricelist.company_id else False,
            existing_order_id=self.sale_order_id.id,
            lines=lines,
        )

    @api.model
    def _register_inbound(self, account, message, body, from_me=False):
        """Create one suggestion for a client message. Never sends WhatsApp."""
        if not message:
            return self.browse()
        config = self.env['kai.whatsapp.ai.config']._for_account(account)
        outgoing = bool(message._om_whatsapp_notifications())
        whatsapp_id = message.om_whatsapp_id or False
        already = bool(whatsapp_id and self.search_count([
            ('account_id', '=', account.id), ('whatsapp_message_id', '=', whatsapp_id),
        ]))
        if not engine.should_register(
            enabled=bool(config),
            from_me=from_me,
            has_outgoing_notification=outgoing,
            already_registered=already,
        ):
            return self.browse()
        inbound = engine.strip_markup(body or message.body)
        if not inbound:
            return self.browse()
        channel = self.env['discuss.channel'].browse(message.res_id).exists() if message.model == 'discuss.channel' else self.env['discuss.channel']
        suggestion = self.create({
            'config_id': config.id,
            'account_id': account.id,
            'channel_id': channel.id if channel else False,
            'message_id': message.id,
            'whatsapp_message_id': whatsapp_id,
            'partner_id': channel.om_whatsapp_partner_id.id if channel and channel.om_whatsapp_partner_id else False,
            'inbound_body': inbound,
            'state': 'review',
            'generation_state': 'pending',
            'needs_human': True,
        })
        suggestion._create_consultation(config, account, channel, message, whatsapp_id)
        return suggestion

    def _create_consultation(self, config, account, channel, message, whatsapp_id):
        self.ensure_one()
        moment = fields.Datetime.now()
        rates = self.env['kai.whatsapp.ai.billable.rate'].sudo().search([
            ('company_id', '=', account.company_id.id),
        ])
        chosen = engine.select_dated(
            [rate._as_engine_row() for rate in rates], moment, account.company_id.id, account.id)
        vals = {
            'suggestion_id': self.id,
            'company_id': account.company_id.id,
            'account_id': account.id,
            'channel_id': channel.id if channel else False,
            'message_id': message.id,
            'whatsapp_message_id': whatsapp_id,
            'partner_id': self.partner_id.id,
            'occurred_at': moment,
            'client_label': (chosen or {}).get('client_label') or config.client_label or '',
            'billable_known': bool(chosen),
            'billable_amount': chosen['amount'] if chosen else 0.0,
            'billable_currency_id': chosen['currency_id'] if chosen else False,
            'billable_rate_id': chosen['id'] if chosen else False,
        }
        consultation = self.env['kai.whatsapp.ai.consultation'].create(vals)
        self.sudo().write({'consultation_id': consultation.id})

    def _channel_context(self):
        self.ensure_one()
        if not self.channel_id:
            return [{"direction": "customer", "body": self.inbound_body or ""}]
        messages = self.env['mail.message'].search([
            ('model', '=', 'discuss.channel'),
            ('res_id', '=', self.channel_id.id),
            ('message_type', '=', 'om_whatsapp'),
            ('id', '<=', self.message_id.id or 0),
        ], order='id desc', limit=engine.MAX_MESSAGES)
        context = []
        for item in reversed(messages):
            direction = 'company' if item._om_whatsapp_notifications() else 'customer'
            context.append({'direction': direction, 'body': item.body})
        return context or [{"direction": "customer", "body": self.inbound_body or ""}]

    def _catalog_rows(self):
        self.ensure_one()
        rows = []
        company = self.company_id
        partner = self.partner_id
        pricelist = partner.with_company(company).property_product_pricelist if partner else False
        stock_known = 'free_qty' in self.env['product.product']._fields
        for line in self.config_id.catalog_ids:
            product = line.product_id
            if not product or not product.sale_ok:
                continue
            if product.company_id and product.company_id != company:
                continue
            price = None
            currency = company.currency_id.name or ''
            if pricelist:
                amount = pricelist.with_company(company)._get_product_price(
                    product.with_company(company), 1.0, uom=product.uom_id)
                price = float(amount)
                currency = pricelist.currency_id.name or currency
            free_qty = None
            if stock_known:
                free_qty = float(product.with_company(company).free_qty)
            rows.append({
                'id': product.id,
                'name': product.display_name,
                'code': product.default_code or '',
                'uom_id': product.uom_id.id,
                'uom_name': product.uom_id.name or '',
                'price': price,
                'currency': currency,
                'free_qty': free_qty,
                'company_id': product.company_id.id or False,
                'sale_ok': True,
            })
        return rows

    def _faq_rows(self):
        self.ensure_one()
        return [{
            'id': faq.id,
            'question': faq.question,
            'answer': faq.answer,
            'active': faq.active,
            'company_id': faq.company_id.id,
        } for faq in self.config_id.faq_ids if faq.active]

    def _provider_may_run(self, from_queue):
        """Enabled, same company and account, and not already generated. Does not read the secret until allowed."""
        self.ensure_one()
        config = self.config_id
        enabled = bool(
            config.enabled and config.active
            and config.company_id == self.company_id
            and self.account_id.company_id == self.company_id
            and (not config.account_id or config.account_id == self.account_id)
        )
        if not enabled:
            return False
        return engine.should_call_provider(
            enabled=True,
            configured=engine.provider_is_configured(config.api_base_url, config.api_model, config.sudo().api_key),
            generation_state=self.generation_state,
            from_queue=from_queue,
        )

    def _generate_bounded(self, from_queue=False):
        """Call the provider with a short timeout. Never sends WhatsApp or creates a sale."""
        for suggestion in self:
            if not suggestion._provider_may_run(from_queue):
                if suggestion.generation_state == 'pending':
                    suggestion.sudo().write({
                        'generation_state': 'error',
                        'intent': 'unknown',
                        'needs_human': True,
                        'provider_error': engine.PROVIDER_MISSING,
                        'suggested_reply': engine.HANDOFF,
                    })
                continue
            config = suggestion.config_id
            catalog = engine.public_catalog(suggestion._catalog_rows(), suggestion.company_id.id)
            faqs = engine.public_faqs(suggestion._faq_rows(), suggestion.company_id.id)
            context = engine.trim_context(suggestion._channel_context())
            messages = engine.build_messages(context, catalog, faqs)
            timeout = min(max(int(config.api_timeout or 15), 1), 15)
            started = time.perf_counter()
            usage = engine.parse_usage('')
            try:
                raw = engine.post_chat(
                    config.api_base_url, config.sudo().api_key, config.api_model, messages, timeout=timeout)
                usage = engine.parse_usage(raw)
                decision = engine.interpret(raw, context=context, catalog=catalog, faqs=faqs)
                decision['error'] = decision.get('error') or ''
                outcome = 'failed' if decision.get('error') else 'success'
                error_text = decision.get('error') or ''
            except engine.ProviderError as error:
                outcome = 'failed'
                error_text = str(error)
                decision = engine._decision('unknown', [], None, engine.PROVIDER_BAD, needs_human=True, error=error_text)
            except Exception:
                _logger.exception("WhatsApp AI: provider call failed for suggestion %s", suggestion.id)
                outcome = 'failed'
                error_text = engine.PROVIDER_BAD
                decision = engine._decision('unknown', [], None, engine.PROVIDER_BAD, needs_human=True, error=error_text)
            latency_ms = int((time.perf_counter() - started) * 1000)
            suggestion._log_call(config, outcome, usage, latency_ms, error_text)
            suggestion._apply_decision(decision)
            suggestion.sudo().write({'generation_state': 'done' if not decision.get('error') else 'error'})

    def _log_call(self, config, outcome, usage, latency_ms, error_text):
        self.ensure_one()
        if not self.consultation_id:
            return
        secret = config.sudo().api_key
        preset = engine.provider_preset(config.provider_preset)
        moment = fields.Datetime.now()
        rates = self.env['kai.whatsapp.ai.provider.rate'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('model_name', '=', config.api_model),
            ('provider_preset', '=', config.provider_preset or 'manual'),
        ])
        chosen = engine.select_dated(
            [rate._as_engine_row() for rate in rates], moment, self.company_id.id, self.account_id.id,
            extra={'model_name': config.api_model, 'provider_preset': config.provider_preset or 'manual'})
        estimate = engine.estimate_provider_cost(usage, chosen)
        attempt = self.env['kai.whatsapp.ai.call'].sudo().search_count([
            ('consultation_id', '=', self.consultation_id.id),
        ]) + 1
        self.env['kai.whatsapp.ai.call'].sudo().create({
            'consultation_id': self.consultation_id.id,
            'suggestion_id': self.id,
            'company_id': self.company_id.id,
            'account_id': self.account_id.id,
            'occurred_at': moment,
            'attempt': attempt,
            'outcome': outcome,
            'latency_ms': max(latency_ms, 0),
            'provider_preset': config.provider_preset or 'manual',
            'provider_label': (preset or {}).get('provider_label') or 'Manual',
            'model_name': config.api_model or '',
            'endpoint_host': urlparse(config.api_base_url or '').hostname or '',
            'error_sanitized': engine.sanitize_provider_error(error_text, secret),
            'client_label': self.consultation_id.client_label or '',
            'input_known': usage['input_known'],
            'input_tokens': usage['input_tokens'] or 0,
            'output_known': usage['output_known'],
            'output_tokens': usage['output_tokens'] or 0,
            'cached_known': usage['cached_known'],
            'cached_tokens': usage['cached_tokens'] or 0,
            'thinking_known': usage['thinking_known'],
            'thinking_tokens': usage['thinking_tokens'] or 0,
            'rate_id': chosen['id'] if chosen else False,
            'rate_name': chosen.get('name') if chosen else False,
            'input_per_million': chosen['input_per_million'] if chosen and chosen.get('input_per_million') is not None else 0.0,
            'output_per_million': chosen['output_per_million'] if chosen and chosen.get('output_per_million') is not None else 0.0,
            'cached_per_million': chosen['cached_per_million'] if chosen and chosen.get('cached_per_million') is not None else 0.0,
            'thinking_per_million': chosen['thinking_per_million'] if chosen and chosen.get('thinking_per_million') is not None else 0.0,
            'cost_known': estimate['known'],
            'cost_usd': estimate['usd'] if estimate['known'] else 0.0,
        })

    def action_generate(self):
        """A person asks for the suggestion. This does not send it."""
        for suggestion in self:
            suggestion._check_open()
            suggestion._generate_bounded(from_queue=False)

    @api.model
    def _cron_generate_suggestions(self, limit=5):
        """Prepare a few queued suggestions. Never sends and never creates a quotation."""
        limit = min(max(int(limit or 5), 1), 5)
        self.env.cr.execute(
            """
            SELECT id FROM kai_whatsapp_ai_suggestion
            WHERE generation_state = 'pending'
            ORDER BY id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            [limit],
        )
        suggestions = self.browse(row[0] for row in self.env.cr.fetchall())
        for suggestion in suggestions:
            try:
                with self.env.cr.savepoint():
                    suggestion._generate_bounded(from_queue=True)
            except Exception:
                _logger.exception("WhatsApp AI: suggestion %s stayed queued", suggestion.id)

    def _apply_decision(self, decision):
        self.ensure_one()
        allowed = set(self.config_id.catalog_ids.product_id.ids)
        commands = [(5, 0, 0)]
        for sequence, line in enumerate(decision['lines'], start=1):
            product_id = line.get('product_id') if line.get('product_id') in allowed else False
            if line.get('product_id') and not product_id:
                line = dict(line, status='unknown', product_id=None, price=None)
            product = self.env['product.product'].browse(product_id) if product_id else self.env['product.product']
            if product and product.company_id and product.company_id != self.company_id:
                product_id = False
                line = dict(line, status='unknown', price=None)
            commands.append((0, 0, {
                'sequence': sequence,
                'raw_request': line.get('raw') or '',
                'product_id': product_id or False,
                'quantity': line.get('quantity') or 0.0,
                'uom_id': product.uom_id.id if product_id and line.get('status') != 'bad_uom' else False,
                'price_unit': line.get('price') if product_id else 0.0,
                'currency_id': self._currency_for(line, product).id if product_id else False,
                'free_qty': line.get('free_qty') if line.get('free_qty') is not None else 0.0,
                'stock_checked': line.get('free_qty') is not None,
                'status': line.get('status') or 'unknown',
            }))
        self.sudo().write({
            'intent': decision['intent'],
            'needs_human': decision['needs_human'] or any(line.get('status') != 'matched' for line in decision['lines'] if decision['intent'] == 'order'),
            'clarification': decision.get('clarification') or False,
            'suggested_reply': decision.get('reply') or '',
            'provider_error': engine.redact(decision.get('error') or '', self.config_id.sudo().api_key),
            'line_ids': commands,
        })

    def _currency_for(self, line, product):
        self.ensure_one()
        pricelist = self.partner_id.with_company(self.company_id).property_product_pricelist if self.partner_id else False
        return (pricelist.currency_id if pricelist else False) or self.company_id.currency_id or product.currency_id

    def action_refresh_prices(self):
        """Re-read pricelist and stock for the matched lines. Does not send."""
        for suggestion in self:
            suggestion._check_open()
            rows = {row['id']: row for row in suggestion._catalog_rows()}
            for line in suggestion.line_ids:
                row = rows.get(line.product_id.id)
                product = line.product_id
                if not row or not product or line.uom_id != product.uom_id:
                    status = 'bad_uom' if product and line.uom_id and line.uom_id != product.uom_id else 'unknown'
                    price = None
                    free_qty = None
                else:
                    price = row['price']
                    free_qty = row['free_qty']
                    if engine._quantity(line.quantity) is None:
                        status = 'bad_qty'
                    elif price is None:
                        status = 'no_price'
                    else:
                        status = 'matched'
                line.sudo().write({
                    'price_unit': 0.0 if price is None else price,
                    'free_qty': 0.0 if free_qty is None else free_qty,
                    'stock_checked': free_qty is not None,
                    'currency_id': suggestion._currency_for({'currency': row['currency'] if row else ''}, product).id if product else False,
                    'uom_id': product.uom_id.id if product and status != 'bad_uom' else line.uom_id.id,
                    'status': status,
                })
            suggestion._rebuild_reply_from_lines()

    def _rebuild_reply_from_lines(self):
        self.ensure_one()
        if self.intent == 'faq':
            return
        lines = [{
            'name': line.product_id.display_name or line.raw_request,
            'quantity': line.quantity or None,
            'uom_name': line.uom_id.name or '',
            'price': line.price_unit if line.status == 'matched' else None,
            'currency': line.currency_id.name or '',
            'free_qty': line.free_qty if line.stock_checked else None,
            'status': line.status,
        } for line in self.line_ids]
        if self.intent == 'order':
            needs_human = any(line['status'] != 'matched' for line in lines) or not lines
        else:
            needs_human = self.intent != 'catalog' or any(line['status'] != 'matched' for line in lines) or not lines
        clarification = '' if not needs_human else (self.clarification or '')
        self.sudo().write({
            'needs_human': needs_human,
            'clarification': clarification or False,
            'suggested_reply': engine._render(self.intent or 'unknown', lines, None, clarification),
        })

    def _check_open(self):
        self.ensure_one()
        if self.state == 'discarded':
            raise UserError(_("This suggestion was discarded."))
        self.account_id._om_whatsapp_check_user()

    def action_discard(self):
        self._check_open()
        if self.reply_sent or self.sale_order_id:
            raise UserError(_("A sent reply or a draft quotation stays. Discard is only for an open suggestion."))
        self.sudo().write({'state': 'discarded'})

    def _lock(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM kai_whatsapp_ai_suggestion WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset()

    def action_send(self):
        """The only WhatsApp send in this module. A person presses the button."""
        self.ensure_one()
        self._lock()
        self._check_open()
        if not engine.send_allowed(
            reply_sent=self.reply_sent,
            discarded=self.state == 'discarded',
            reply_text=self.suggested_reply,
            allowed_user=self.env.user in self.account_id.user_ids,
        ):
            raise UserError(_("This reply cannot be sent."))
        if not self.channel_id:
            raise UserError(_("This suggestion has no WhatsApp conversation to send from."))
        self.channel_id.message_post(body=plaintext2html(self.suggested_reply.strip()), message_type='comment')
        self.sudo().write({'reply_sent': True, 'reply_sent_at': fields.Datetime.now()})

    def action_create_draft_quotation(self):
        """Create a draft sale order from reviewed lines. Never confirms it."""
        self.ensure_one()
        self._lock()
        self._check_open()
        self.action_refresh_prices()
        if not self._quotation_is_valid():
            raise UserError(_("Choose the customer on this conversation and resolve every line against the tariff before the draft."))
        self.env['sale.order'].check_access('create')
        company = self.company_id
        lines = []
        for line in self.line_ids:
            product = line.product_id
            lines.append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'product_uom_id': product.uom_id.id,
            }))
        order = self.env['sale.order'].with_company(company).create({
            'partner_id': self.partner_id.id,
            'company_id': company.id,
            'origin': _("WhatsApp %s") % (self.whatsapp_message_id or self.id),
            'order_line': lines,
        })
        if order.state != 'draft':
            raise UserError(_("The quotation was not left as a draft."))
        self.sudo().write({'sale_order_id': order.id, 'quotation_at': fields.Datetime.now()})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'views': [(False, 'form')],
        }


class KaiWhatsappAiSuggestionLine(models.Model):
    _name = 'kai.whatsapp.ai.suggestion.line'
    _description = 'WhatsApp AI Suggestion Line'
    _order = 'sequence, id'

    suggestion_id = fields.Many2one('kai.whatsapp.ai.suggestion', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='suggestion_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    raw_request = fields.Char(readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    quantity = fields.Float(digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', string='Unit', readonly=True)
    price_unit = fields.Float(digits='Product Price', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    free_qty = fields.Float(readonly=True)
    stock_checked = fields.Boolean(readonly=True)
    status = fields.Selection([
        ('matched', 'Matched'),
        ('ambiguous', 'Ambiguous'),
        ('unknown', 'Not in catalog'),
        ('bad_qty', 'Missing quantity'),
        ('bad_uom', 'Wrong unit'),
        ('no_price', 'No tariff'),
    ], required=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Suggestion lines are created by the assistant, not by hand."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if set(vals) - {'quantity'}:
                raise UserError(_("Only the quantity can be corrected."))
            if 'quantity' in vals and engine._quantity(vals['quantity']) is None:
                raise UserError(_("The quantity has to be greater than zero and at most %s.", engine.MAX_QTY))
        return super().write(vals)
