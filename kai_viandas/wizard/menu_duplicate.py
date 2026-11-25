from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from ..models.identity import check_operator
from ..models.reservation import operation_context


class MenuDuplicate(models.TransientModel):
    _name = "lafija.menu.duplicate"
    _description = "Duplicar menús del día con una fecha nueva"

    line_ids = fields.One2many("lafija.menu.duplicate.line", "wizard_id", string="Menús a duplicar")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "line_ids" in fields_list:
            ids = self.env.context.get("default_menu_ids") or (
                self.env.context.get("active_ids")
                if self.env.context.get("active_model") == "lafija.menu.day" else [])
            menus = self.env["lafija.menu.day"].browse(ids).exists().sorted("date")
            values["line_ids"] = [(0, 0, {
                "menu_id": menu.id, "new_date": menu.date + timedelta(days=7),
            }) for menu in menus]
        return values

    def action_apply(self):
        check_operator(self.env)
        self.ensure_one()
        if not self.line_ids:
            raise ValidationError(_("Elegí al menos un menú para duplicar."))
        Menu = self.env["lafija.menu.day"]
        seen = set()
        for line in self.line_ids:
            if not line.new_date:
                raise ValidationError(_("Indicá la fecha nueva del menú %s.", line.menu_id.display_name))
            key = (line.new_date, line.menu_id.website_id.id)
            if key in seen:
                raise ValidationError(_(
                    "Elegiste dos veces el %s para el mismo sitio. Cada menú nuevo necesita su propio día.",
                    line.new_date))
            seen.add(key)
            clash = Menu.search([("date", "=", line.new_date), ("website_id", "=", line.menu_id.website_id.id)], limit=1)
            if clash:
                raise ValidationError(_(
                    "Ya existe un menú para el %(date)s en %(site)s. Elegí otra fecha o editá ese menú.",
                    date=line.new_date, site=line.menu_id.website_id.name))
        created = Menu
        for line in self.line_ids:
            created |= line._duplicate_menu()
        if len(created) == 1:
            return {"type": "ir.actions.act_window", "res_model": "lafija.menu.day",
                    "res_id": created.id, "view_mode": "form", "target": "current"}
        return {"type": "ir.actions.act_window", "name": _("Menús duplicados"),
                "res_model": "lafija.menu.day", "view_mode": "list,form,calendar",
                "domain": [("id", "in", created.ids)], "target": "current"}


class MenuDuplicateLine(models.TransientModel):
    _name = "lafija.menu.duplicate.line"
    _description = "Menú a duplicar y su fecha nueva"
    _order = "source_date, id"

    wizard_id = fields.Many2one("lafija.menu.duplicate", required=True, ondelete="cascade")
    menu_id = fields.Many2one("lafija.menu.day", string="Menú original", required=True, readonly=True)
    source_date = fields.Date(related="menu_id.date", string="Fecha original")
    website_id = fields.Many2one(related="menu_id.website_id", string="Sitio")
    reservation_count = fields.Integer(compute="_compute_reservation_count", string="Pedidos del original")
    option_count = fields.Integer(compute="_compute_option_count", string="Opciones que se copian")
    new_date = fields.Date("Fecha del menú nuevo", required=True)

    @api.depends("menu_id")
    def _compute_reservation_count(self):
        for line in self:
            line.reservation_count = len(line.menu_id.reservation_ids)

    @api.depends("menu_id")
    def _compute_option_count(self):
        for line in self:
            line.option_count = len(self._copyable(line.menu_id)["all"])

    @api.model
    def _copyable(self, menu):
        return self.env["lafija.menu.day"]._lf_copyable_options(menu)

    def _duplicate_menu(self):
        """Crea solo el menú (sitio, platos, postres, bebidas). Nunca reservas, pedidos ni órdenes de fabricación."""
        self.ensure_one()
        source = self.menu_id
        options = self._copyable(source)
        new = self.env["lafija.menu.day"].with_context(**operation_context()).create({
            "date": self.new_date,
            "website_id": source.website_id.id,
            "product_ids": [(6, 0, options["plates"].ids)],
            "dessert_ids": [(6, 0, options["desserts"].ids)],
            "drink_ids": [(6, 0, options["drinks"].ids)],
            "published": False,
        })
        skipped = (source.product_ids | source.dessert_ids | source.drink_ids) - options["all"]
        body = _("Menú duplicado desde el del %(date)s. Se copiaron %(count)s opciones; no se copiaron pedidos ni viandas. Queda sin publicar.",
                 date=source.date, count=len(options["all"]))
        if skipped:
            body += " " + _("No se copiaron por estar archivados o no vendibles: %s.", ", ".join(skipped.mapped("display_name")))
        new.message_post(body=body, subtype_xmlid="mail.mt_note")
        return new
