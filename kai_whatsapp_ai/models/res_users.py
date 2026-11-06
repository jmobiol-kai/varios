from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _on_webclient_bootstrap(self):
        """Pin a direct chat with Agente IA, the same way OdooBot appears under direct messages."""
        super()._on_webclient_bootstrap()
        if not self._is_internal():
            return
        bot = self.env.ref('kai_whatsapp_ai.partner_ai_agent', raise_if_not_found=False)
        if not bot:
            return
        channel = self.env['discuss.channel'].with_context(active_test=False)._get_or_create_chat(
            [bot.id, self.partner_id.id])
        if channel.message_ids:
            return
        self.env['kai.whatsapp.ai.training']._post_as_bot(
            channel,
            "Soy el agente de entrenamiento. Si estás en Entrenadores, escribime cómo querés que hable con los clientes.",
        )
