from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _compute_im_status(self):
        super()._compute_im_status()
        bot = self.env.ref('kai_whatsapp_ai.partner_ai_agent', raise_if_not_found=False)
        if bot and bot in self:
            bot.im_status = 'bot'

    def _search_for_channel_invite(self, store, search_term, channel_id=None, limit=30):
        """Keep Agente IA selectable even though its user is not a login, like OdooBot."""
        result = super()._search_for_channel_invite(store, search_term, channel_id, limit)
        bot = self.env.ref('kai_whatsapp_ai.partner_ai_agent', raise_if_not_found=False)
        if not bot or bot.id == self.env.user.partner_id.id or bot.id in result.get('partner_ids', []):
            return result
        term = (search_term or '').strip().casefold()
        if term and term not in (bot.name or '').casefold():
            return result
        if channel_id:
            channel = self.env['discuss.channel'].browse(int(channel_id)).exists()
            if channel and bot in channel.with_context(active_test=False).channel_member_ids.partner_id:
                return result
        store.add(bot)
        result['partner_ids'] = [bot.id] + list(result.get('partner_ids') or [])
        result['count'] = int(result.get('count') or 0) + 1
        return result
