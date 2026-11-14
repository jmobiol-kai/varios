# -*- coding: utf-8 -*-
"""Point the IA Agent app icon at this module."""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    from odoo.addons.kai_whatsapp_ai.hooks import post_init_hook

    post_init_hook(api.Environment(cr, SUPERUSER_ID, {}))
