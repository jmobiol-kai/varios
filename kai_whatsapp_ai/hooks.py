from odoo import Command

COST_VIEWER_LOGIN = "admin@kaizendo.com.ar"
APP_NAME = "IA Agent"


def post_init_hook(env):
    """Name the app and grant provider-cost access to one login, if that user exists."""
    brand_app(env)
    grant_cost_viewer(env)


def brand_app(env):
    menu = env.ref("om_whatsapp_base.om_whatsapp_menu_root", raise_if_not_found=False)
    if not menu:
        return
    languages = env["res.lang"].sudo().search([]).mapped("code") or ["en_US"]
    for code in languages:
        menu.with_context(lang=code).sudo().write({"name": APP_NAME})


def grant_cost_viewer(env):
    group = env.ref("kai_whatsapp_ai.group_cost_viewer", raise_if_not_found=False)
    if not group:
        return
    user = env["res.users"].sudo().search([("login", "=", COST_VIEWER_LOGIN)], limit=1)
    if user and group not in user.group_ids:
        user.sudo().write({"group_ids": [Command.link(group.id)]})
