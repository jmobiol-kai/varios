import logging
import time
from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import plaintext2html

from odoo.addons.kai_whatsapp_ai.services import engine

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    kai_trainer_ids = fields.One2many('kai.whatsapp.ai.trainer', 'company_id')


class KaiWhatsappAiTrainer(models.Model):
    """People allowed to teach the agent. A customer sentence never grants this."""
    _name = 'kai.whatsapp.ai.trainer'
    _description = 'WhatsApp AI Trainer'
    _order = 'company_id, name, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True)
    user_id = fields.Many2one(
        'res.users', string='Odoo user', ondelete='cascade',
        domain="[('share', '=', False)]")
    phone = fields.Char(string='WhatsApp number', help="Authorized personal number, with country code.")
    phone_e164 = fields.Char(compute='_compute_phone_e164', store=True, index=True)

    _trainer_user_unique = models.UniqueIndex("(company_id, user_id) WHERE user_id IS NOT NULL")
    _trainer_phone_unique = models.UniqueIndex(
        "(company_id, phone_e164) WHERE phone_e164 IS NOT NULL AND phone_e164 != ''")

    @api.depends('phone')
    def _compute_phone_e164(self):
        for trainer in self:
            trainer.phone_e164 = engine.normalize_e164(trainer.phone)

    @api.constrains('user_id', 'phone', 'company_id')
    def _check_identity(self):
        for trainer in self:
            if not trainer.user_id and not trainer.phone_e164:
                raise ValidationError(_("A trainer needs an Odoo user or a WhatsApp number."))
            if trainer.user_id and trainer.user_id.share:
                raise ValidationError(_("%s is not an internal user.", trainer.user_id.display_name))
            if trainer.user_id and trainer.company_id not in trainer.user_id.company_ids:
                raise ValidationError(_("%s is not in this company.", trainer.user_id.display_name))

    @api.model
    def _for_user(self, user, company):
        if not user or not company:
            return self.browse()
        domain = [('user_id', '=', user.id), ('active', '=', True)]
        if company:
            current = self.sudo().search(domain + [('company_id', '=', company.id)], limit=1)
            if current:
                return current
        return self.sudo().search(domain + [('company_id', 'in', user.company_ids.ids)], limit=1)


class KaiWhatsappAiRule(models.Model):
    """A preference. It becomes active only after a trainer confirms it."""
    _name = 'kai.whatsapp.ai.rule'
    _description = 'WhatsApp AI Preference Rule'
    _inherit = ['mail.thread']
    _order = 'priority desc, id desc'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True)
    title = fields.Char(required=True, tracking=True)
    body = fields.Text(string='Rule', required=True, tracking=True)
    scope = fields.Selection([
        ('global', 'Global'),
        ('category', 'Category'),
        ('product', 'Product'),
        ('activity', 'Activity'),
    ], required=True, default='global', tracking=True)
    category_id = fields.Many2one('product.category', string='Category')
    product_id = fields.Many2one(
        'product.product', string='Product', check_company=True,
        domain="[('sale_ok', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    activity = fields.Char(help="For example miel or cosmética.")
    priority = fields.Integer(default=10, tracking=True)
    state = fields.Selection([
        ('propuesta', 'Propuesta'),
        ('activa', 'Activa'),
        ('inactiva', 'Inactiva'),
    ], required=True, default='propuesta', tracking=True, index=True)
    flagged = fields.Boolean(readonly=True)
    flag_reason = fields.Char(readonly=True)
    origin = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('discuss', 'Discuss'),
        ('odoo', 'Odoo'),
    ], required=True, default='odoo')
    origin_number = fields.Char(readonly=True)
    trainer_id = fields.Many2one('kai.whatsapp.ai.trainer', string='Proposed by', readonly=True)
    author_user_id = fields.Many2one('res.users', string='Proposed by user', readonly=True)
    approved_by_user_id = fields.Many2one('res.users', readonly=True)
    approved_by_trainer_id = fields.Many2one('kai.whatsapp.ai.trainer', readonly=True)
    training_id = fields.Many2one('kai.whatsapp.ai.training', readonly=True, index=True)

    def _as_engine_row(self):
        self.ensure_one()
        return {
            'id': self.id,
            'state': self.state,
            'flagged': self.flagged,
            'scope': self.scope,
            'priority': self.priority,
            'title': self.title,
            'body': self.body or '',
            'activity': self.activity or '',
            'product_id': self.product_id.id or False,
            'category_id': self.category_id.id or False,
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            verdict = engine.screen_rule(vals.get('body') or '')
            if not verdict['ok']:
                vals['flagged'] = True
                vals['flag_reason'] = verdict['reason']
                vals['state'] = 'propuesta'
            elif vals.get('state') == 'activa':
                raise UserError(_("A rule starts as a proposal. Confirm it on purpose."))
        rules = super().create(vals_list)
        for rule in rules:
            who = rule.trainer_id.name or rule.author_user_id.name or rule.create_uid.name
            rule.message_post(
                body=_("Propuesta creada por %s desde %s.", who, rule.origin),
                subtype_xmlid='mail.mt_note',
            )
        return rules

    def write(self, vals):
        vals = dict(vals)
        if 'body' in vals:
            verdict = engine.screen_rule(vals.get('body') or '')
            vals['flagged'] = not verdict['ok']
            vals['flag_reason'] = verdict['reason'] if not verdict['ok'] else False
            if not verdict['ok']:
                vals['state'] = 'propuesta'
        if vals.get('state') == 'activa':
            for rule in self:
                if rule.state != 'propuesta':
                    raise UserError(_("Only a proposal can be confirmed."))
                preview = rule._as_engine_row()
                if 'body' in vals:
                    preview['body'] = vals.get('body') or ''
                    preview['flagged'] = bool(vals.get('flagged'))
                preview['state'] = 'propuesta'
                if not engine.can_activate(preview):
                    raise UserError(vals.get('flag_reason') or rule.flag_reason or _("This proposal cannot be activated."))
        return super().write(vals)

    def action_confirm(self):
        for rule in self:
            if not engine.can_activate(rule._as_engine_row()):
                raise UserError(rule.flag_reason or _("This proposal cannot be activated."))
            trainer = self.env['kai.whatsapp.ai.trainer']._for_user(self.env.user, rule.company_id) or rule.trainer_id
            actor = trainer.user_id if self.env.su and trainer.user_id else self.env.user
            rule.sudo().write({
                'state': 'activa',
                'approved_by_user_id': actor.id,
                'approved_by_trainer_id': trainer.id,
            })
            rule.message_post(body=_("Confirmada por %s.", actor.name), subtype_xmlid='mail.mt_note')

    def action_deactivate(self):
        self.write({'state': 'inactiva'})
        for rule in self:
            rule.message_post(body=_("Desactivada por %s.", self.env.user.name), subtype_xmlid='mail.mt_note')


class KaiWhatsappAiTraining(models.Model):
    """One trainer message. Customer chats never land here."""
    _name = 'kai.whatsapp.ai.training'
    _description = 'WhatsApp AI Training Turn'
    _order = 'id desc'

    company_id = fields.Many2one('res.company', required=True, index=True)
    config_id = fields.Many2one('kai.whatsapp.ai.config', ondelete='set null')
    account_id = fields.Many2one('om.whatsapp.account', ondelete='set null', index=True)
    trainer_id = fields.Many2one('kai.whatsapp.ai.trainer', ondelete='set null')
    user_id = fields.Many2one('res.users', string='Trainer user')
    partner_id = fields.Many2one('res.partner')
    phone_e164 = fields.Char()
    origin = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('discuss', 'Discuss'),
    ], required=True, index=True)
    channel_id = fields.Many2one('discuss.channel', ondelete='set null')
    message_id = fields.Many2one('mail.message', ondelete='set null', index=True)
    whatsapp_message_id = fields.Char(index=True)
    inbound_body = fields.Text()
    suggested_reply = fields.Text(string='Reply to review')
    generation_state = fields.Selection([
        ('pending', 'Queued'),
        ('done', 'Ready'),
        ('error', 'Error'),
    ], default='pending', required=True, index=True)
    provider_error = fields.Char(readonly=True, groups='kai_whatsapp_ai.group_manager')
    consultation_id = fields.Many2one('kai.whatsapp.ai.consultation', readonly=True)
    reply_sent = fields.Boolean(readonly=True, copy=False)
    reply_sent_at = fields.Datetime(readonly=True, copy=False)
    discuss_replied = fields.Boolean(readonly=True, copy=False)

    _training_whatsapp_unique = models.UniqueIndex(
        "(account_id, whatsapp_message_id) WHERE whatsapp_message_id IS NOT NULL")
    _training_message_unique = models.UniqueIndex("(message_id) WHERE message_id IS NOT NULL")

    @api.model
    def _bot_partner(self):
        return self.env.ref('kai_whatsapp_ai.partner_ai_agent', raise_if_not_found=False)

    @api.model
    def _route_whatsapp(self, account, number):
        phones = self.env['kai.whatsapp.ai.trainer'].sudo().search([
            ('company_id', '=', account.company_id.id),
            ('active', '=', True),
        ]).mapped('phone_e164')
        return engine.route_mode(number=number, authorized_numbers=phones)

    @api.model
    def _register_whatsapp(self, account, config, channel, message, body, whatsapp_id):
        """A trainer's own number. Never a customer suggestion and never an automatic customer send."""
        inbound = engine.strip_markup(body or message.body)
        if not inbound:
            return self.browse()
        if whatsapp_id and self.sudo().search_count([
            ('account_id', '=', account.id), ('whatsapp_message_id', '=', whatsapp_id),
        ]):
            return self.browse()
        phone = engine.normalize_e164(channel.om_whatsapp_number if channel else '')
        trainer = self.env['kai.whatsapp.ai.trainer'].sudo().search([
            ('company_id', '=', account.company_id.id),
            ('active', '=', True),
            ('phone_e164', '=', phone),
        ], limit=1)
        turn = self.sudo().create({
            'company_id': account.company_id.id,
            'config_id': config.id,
            'account_id': account.id,
            'trainer_id': trainer.id,
            'user_id': trainer.user_id.id,
            'partner_id': channel.om_whatsapp_partner_id.id if channel and channel.om_whatsapp_partner_id else False,
            'phone_e164': phone,
            'origin': 'whatsapp',
            'channel_id': channel.id if channel else False,
            'message_id': message.id,
            'whatsapp_message_id': whatsapp_id,
            'inbound_body': inbound,
            'generation_state': 'pending',
        })
        turn._meter(config, account)
        command = engine.training_command(inbound)
        if command:
            turn._finish_command(command)
            turn._maybe_whatsapp_reply()
        return turn

    @api.model
    def _on_discuss_message(self, channel, message, msg_vals):
        bot = self._bot_partner()
        if not bot or not channel:
            return
        message_type = (msg_vals or {}).get('message_type') or message.message_type
        if message_type != 'comment':
            return
        author = message.author_id
        members = channel.with_context(active_test=False).channel_member_ids.partner_id
        author_user = author.user_ids.filtered(lambda user: not user.share)[:1]
        trainer, company = self._discuss_trainer(author_user)
        route = engine.route_discuss(
            channel_type=channel.channel_type,
            author_is_bot=author == bot,
            bot_in_channel=bot in members,
            author_is_trainer=bool(company),
            member_count=len(members),
        )
        if route == 'ignore':
            return
        if self.sudo().search_count([('message_id', '=', message.id)]):
            return
        if route == 'unauthorized':
            self._post_as_bot(channel, engine.UNAUTHORIZED_TRAINER)
            return
        body = engine.strip_markup((msg_vals or {}).get('body') or message.body)
        if not body:
            return
        config = self.env['kai.whatsapp.ai.config'].sudo()._enabled_for_company(company)
        command = engine.training_command(body)
        if not engine.discuss_should_meter(route, bool(config)):
            reply = self._command_reply(company, trainer, command) if command else engine.PUBLIC_FAILURE
            self._post_as_bot(channel, engine.customer_visible_text(reply))
            return
        account = self._account_for_company(company, config)
        turn = self.sudo().create({
            'company_id': company.id,
            'config_id': config.id,
            'account_id': account.id,
            'trainer_id': trainer.id,
            'user_id': author_user.id,
            'partner_id': author.id,
            'origin': 'discuss',
            'channel_id': channel.id,
            'message_id': message.id,
            'inbound_body': body,
            'generation_state': 'pending',
        })
        turn._meter(config, account)
        if command:
            turn._finish_command(command)
            turn._post_discuss_reply()
            return
        self._post_as_bot(channel, engine.THINKING)

    def _finish_command(self, command):
        self.ensure_one()
        reply = self._command_reply(self.company_id, self.trainer_id, command)
        self.sudo().write({
            'suggested_reply': reply,
            'generation_state': 'done',
            'provider_error': False,
        })

    def _command_reply(self, company, trainer, command):
        rules = self.env['kai.whatsapp.ai.rule'].sudo().search([
            ('company_id', '=', company.id),
        ])
        action = (command or {}).get('action')
        number = (command or {}).get('number')
        if action == 'list':
            return engine.format_rule_list([rule._as_engine_row() | {'title': rule.title} for rule in rules])
        rule = rules.filtered(lambda item: item.id == number)[:1] if number else self.env['kai.whatsapp.ai.rule']
        if action == 'deactivate':
            if not rule:
                return _("No encuentro esa regla.")
            rule.with_user(self.env.user).action_deactivate()
            return _("La regla %s quedó inactiva.", rule.id)
        if action == 'confirm':
            if not rule:
                proposals = rules.filtered(lambda item: engine.can_activate(item._as_engine_row()))
                rule = proposals.sorted('id')[-1:] if proposals else rule
            if not rule or not engine.can_activate(rule._as_engine_row()):
                return _("No hay una propuesta para confirmar.")
            rule.action_confirm()
            return _("La regla %s quedó activa.", rule.id)
        if action == 'edit':
            if not rule:
                return _("No encuentro esa regla.")
            verdict = engine.screen_rule(command.get('body') or '')
            if not verdict['ok']:
                rule.sudo().write({'body': command.get('body') or '', 'state': 'propuesta'})
                return verdict['reason']
            rule.sudo().write({'body': command.get('body') or ''})
            return _("Actualicé la regla %s. Si estaba propuesta, confirmala.", rule.id)
        return _("No entendí el pedido.")

    @api.model
    def _cron_generate_training(self, limit=5):
        """Prepare queued trainer turns. Discuss replies here. WhatsApp only if the admin flag is on."""
        limit = min(max(int(limit or 5), 1), 5)
        self.env.cr.execute(
            """
            SELECT id FROM kai_whatsapp_ai_training
            WHERE generation_state = 'pending'
            ORDER BY id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            [limit],
        )
        turns = self.browse(row[0] for row in self.env.cr.fetchall())
        for turn in turns:
            try:
                with self.env.cr.savepoint():
                    turn._generate_bounded()
            except Exception:
                _logger.exception("WhatsApp AI: training turn %s stayed queued", turn.id)

    def _generate_bounded(self):
        for turn in self:
            config = turn.config_id.sudo()
            if not turn._provider_may_run():
                turn.sudo().write({
                    'generation_state': 'error',
                    'provider_error': engine.PROVIDER_MISSING,
                    'suggested_reply': engine.PUBLIC_FAILURE,
                })
                turn._post_discuss_reply()
                continue
            history = turn._history()
            names = turn._catalog_names()
            rules = self.env['kai.whatsapp.ai.rule'].sudo().search([('company_id', '=', turn.company_id.id)])
            messages = engine.build_training_messages(
                history, names, [rule._as_engine_row() for rule in rules])
            timeout = min(max(int(config.api_timeout or 15), 1), 15)
            started = time.perf_counter()
            usage = engine.parse_usage('')
            try:
                raw = engine.post_chat(
                    config.api_base_url, config.api_key, config.api_model, messages, timeout=timeout)
                usage = engine.parse_usage(raw)
                parsed = engine.parse_training_reply(raw)
                outcome = 'success'
                error_text = ''
            except engine.ProviderError as error:
                outcome = 'failed'
                error_text = str(error)
                parsed = {'reply': engine.PUBLIC_FAILURE, 'proposals': []}
            except Exception:
                _logger.exception("WhatsApp AI: training provider failed for %s", turn.id)
                outcome = 'failed'
                error_text = engine.PROVIDER_BAD
                parsed = {'reply': engine.PUBLIC_FAILURE, 'proposals': []}
            turn._log_call(config, outcome, usage, int((time.perf_counter() - started) * 1000), error_text)
            notes = []
            for proposal in parsed['proposals']:
                rule = turn._store_proposal(proposal)
                if rule and not rule.flagged:
                    notes.append(_("Propuesta %s: %s. Respondé confirmar %s para activarla.", rule.id, rule.title, rule.id))
                elif rule:
                    notes.append(_("No guardé «%s»: %s", rule.title, rule.flag_reason))
            reply = engine.customer_visible_text(parsed['reply'])
            if outcome == 'success' and notes:
                reply = (reply + "\n\n" + "\n".join(notes)).strip()
            if outcome != 'success':
                reply = engine.PUBLIC_FAILURE
            turn.sudo().write({
                'suggested_reply': reply[:engine.MAX_REPLY_CHARS],
                'generation_state': 'done' if outcome == 'success' else 'error',
                'provider_error': error_text or False,
            })
            turn._post_discuss_reply()
            turn._maybe_whatsapp_reply()

    def _provider_may_run(self):
        self.ensure_one()
        config = self.config_id.sudo()
        enabled = bool(
            config and config.enabled and config.active and config.company_id == self.company_id
        )
        return engine.should_call_provider(
            enabled=enabled,
            configured=engine.provider_is_configured(
                config.api_base_url, config.api_model, config.api_key) if config else False,
            generation_state=self.generation_state,
            from_queue=True,
        )

    def _history(self):
        self.ensure_one()
        previous = self.sudo().search([
            ('company_id', '=', self.company_id.id),
            ('id', '<', self.id),
            ('origin', '=', self.origin),
            ('partner_id', '=', self.partner_id.id),
        ], order='id desc', limit=engine.MAX_MESSAGES)
        history = []
        for item in reversed(previous):
            if item.inbound_body:
                history.append({'role': 'trainer', 'body': item.inbound_body})
            if item.suggested_reply:
                history.append({'role': 'agent', 'body': item.suggested_reply})
        history.append({'role': 'trainer', 'body': self.inbound_body or ''})
        return history

    def _catalog_names(self):
        self.ensure_one()
        rows = []
        configs = self.env['kai.whatsapp.ai.config'].sudo().search([
            ('company_id', '=', self.company_id.id), ('active', '=', True),
        ])
        for line in configs.catalog_ids:
            product = line.product_id
            if product and product.sale_ok:
                rows.append({'name': product.display_name, 'code': product.default_code or ''})
        return rows[:engine.MAX_PRODUCTS]

    def _store_proposal(self, proposal):
        self.ensure_one()
        vals = {
            'company_id': self.company_id.id,
            'title': proposal['title'],
            'body': proposal['body'],
            'scope': proposal['scope'],
            'priority': proposal['priority'],
            'state': 'propuesta',
            'flagged': not proposal['ok'],
            'flag_reason': proposal['reason'] or False,
            'origin': self.origin,
            'origin_number': self.phone_e164 or False,
            'trainer_id': self.trainer_id.id,
            'author_user_id': self.user_id.id,
            'training_id': self.id,
            'activity': proposal.get('activity') or False,
        }
        if proposal['scope'] == 'product' and proposal.get('product_code'):
            product = self._find_catalog_product(proposal['product_code'])
            if product:
                vals['product_id'] = product.id
            else:
                vals['flagged'] = True
                vals['flag_reason'] = _("El producto no está en el catálogo habilitado.")
        if proposal['scope'] == 'category' and proposal.get('category_name'):
            category = self.env['product.category'].sudo().search([
                ('name', '=ilike', proposal['category_name']),
            ], limit=1)
            if category:
                vals['category_id'] = category.id
            else:
                vals['flagged'] = True
                vals['flag_reason'] = _("La categoría no está cargada.")
        if not proposal['body']:
            return self.env['kai.whatsapp.ai.rule']
        return self.env['kai.whatsapp.ai.rule'].sudo().create(vals)

    def _find_catalog_product(self, code):
        self.ensure_one()
        lines = self.env['kai.whatsapp.ai.catalog'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('product_id.default_code', '=', code),
        ], limit=1)
        return lines.product_id

    def _meter(self, config, account):
        """Same consultation row a customer message gets. No separate report category."""
        self.ensure_one()
        if self.consultation_id:
            return
        moment = fields.Datetime.now()
        rates = self.env['kai.whatsapp.ai.billable.rate'].sudo().search([
            ('company_id', '=', self.company_id.id),
        ])
        chosen = engine.select_dated(
            [rate._as_engine_row() for rate in rates], moment, self.company_id.id, account.id if account else False)
        consultation = self.env['kai.whatsapp.ai.consultation'].sudo().create({
            'company_id': self.company_id.id,
            'account_id': account.id if account else False,
            'channel_id': self.channel_id.id,
            'message_id': self.message_id.id,
            'whatsapp_message_id': self.whatsapp_message_id,
            'partner_id': self.partner_id.id,
            'occurred_at': moment,
            'client_label': (chosen or {}).get('client_label') or (config.client_label if config else '') or '',
            'billable_known': bool(chosen),
            'billable_amount': chosen['amount'] if chosen else 0.0,
            'billable_currency_id': chosen['currency_id'] if chosen else False,
            'billable_rate_id': chosen['id'] if chosen else False,
            'has_image': False,
        })
        self.sudo().write({'consultation_id': consultation.id})

    def _log_call(self, config, outcome, usage, latency_ms, error_text):
        self.ensure_one()
        if not self.consultation_id:
            return
        config = config.sudo()
        secret = config.api_key
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
        stored_preset = config.provider_preset if config.provider_preset in ('manual', 'gemini_flash_lite', 'grok') else 'manual'
        self.env['kai.whatsapp.ai.call'].sudo().create({
            'consultation_id': self.consultation_id.id,
            'company_id': self.company_id.id,
            'account_id': self.account_id.id,
            'occurred_at': moment,
            'attempt': attempt,
            'outcome': outcome,
            'latency_ms': max(latency_ms, 0),
            'provider_preset': stored_preset,
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
            'is_training': True,
        })

    def _post_discuss_reply(self):
        for turn in self:
            if turn.origin != 'discuss' or turn.discuss_replied or not turn.channel_id:
                continue
            if not (turn.suggested_reply or '').strip():
                continue
            self._post_as_bot(turn.channel_id, turn.suggested_reply)
            turn.sudo().write({'discuss_replied': True})

    @api.model
    def _post_as_bot(self, channel, text):
        bot = self._bot_partner()
        if not bot or not channel or not str(text or '').strip():
            return
        channel.sudo().message_post(
            author_id=bot.id,
            body=plaintext2html(str(text).strip()),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def _maybe_whatsapp_reply(self):
        """WhatsApp stays manual unless an administrator turned this on. Customers are never sent here."""
        for turn in self:
            config = turn.config_id
            if not config or not config.auto_reply_trainer or turn.origin != 'whatsapp' or turn.reply_sent:
                continue
            turn._send_whatsapp()

    def _lock(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM kai_whatsapp_ai_training WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset()

    def _send_whatsapp(self):
        self.ensure_one()
        self._lock()
        if self.origin != 'whatsapp' or self.reply_sent or not self.channel_id:
            return
        if not (self.suggested_reply or '').strip():
            return
        self.channel_id.sudo().message_post(
            body=plaintext2html(self.suggested_reply.strip()),
            message_type='comment',
        )
        self.sudo().write({'reply_sent': True, 'reply_sent_at': fields.Datetime.now()})

    def action_send(self):
        """A person sends the trainer's WhatsApp reply. This button does not send customer replies."""
        self.ensure_one()
        self._lock()
        if self.origin != 'whatsapp':
            raise UserError(_("This reply already lives in the Discuss chat."))
        if not engine.send_allowed(
            reply_sent=self.reply_sent,
            discarded=False,
            reply_text=self.suggested_reply,
            allowed_user=self.env.user in self.account_id.user_ids,
        ):
            raise UserError(_("This reply cannot be sent."))
        self._send_whatsapp()

    @api.model
    def _discuss_trainer(self, user):
        """Listed trainer, or an Odoo user in the trainer group. A customer is neither."""
        Trainer = self.env['kai.whatsapp.ai.trainer']
        empty_company = self.env['res.company']
        if not user:
            return Trainer.browse(), empty_company
        row = Trainer._for_user(user, user.company_id)
        if row:
            return row, row.company_id
        if user.has_group('kai_whatsapp_ai.group_trainer'):
            return Trainer.browse(), user.company_id
        return Trainer.browse(), empty_company

    @api.model
    def _account_for_company(self, company, config):
        if config and config.account_id and config.account_id.company_id == company:
            return config.account_id
        accounts = self.env['om.whatsapp.account'].sudo().search([('company_id', '=', company.id)])
        return accounts[:1] if len(accounts) == 1 else self.env['om.whatsapp.account']

