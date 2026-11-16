# -*- coding: utf-8 -*-
"""Seed admin restrictions for company 00IA when that company exists. Do not overwrite."""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    from odoo.addons.kai_whatsapp_ai.hooks import seed_restrictions

    env = api.Environment(cr, SUPERUSER_ID, {})
    seed_restrictions(env)
