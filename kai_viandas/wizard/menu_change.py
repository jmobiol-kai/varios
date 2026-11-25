from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from ..models.identity import check_operator
from ..models.reservation import (
    DESSERT_CATEGORY_NAME, DRINK_CATEGORY_NAME, PLATE_CATEGORY_NAME, operation_context,
)
from ..models.time_utils import business_today


class MenuChange(models.TransientModel):
    _name = "lafija.menu.change"
    _description = "Cambiar un plato agotado del menú"

    menu_id = fields.Many2one("lafija.menu.day", "Menú", required=True, readonly=True)
    menu_date = fields.Date(related="menu_id.date", string="Día")
    current_plate_ids = fields.Many2many("product.product", "lafija_menu_change_cur_plate", compute="_compute_current")
    current_dessert_ids = fields.Many2many("product.product", "lafija_menu_change_cur_dessert", compute="_compute_current")
    current_drink_ids = fields.Many2many("product.product", "lafija_menu_change_cur_drink", compute="_compute_current")
    sold_out_ids = fields.Many2many(
        "product.product", "lafija_menu_change_sold_out", "wizard_id", "product_id",
        string="Se agotó", help="Platos, postres o bebidas que dejan de ofrecerse desde ahora.")
    add_plate_ids = fields.Many2many(
        "product.product", "lafija_menu_change_add_plate", "wizard_id", "product_id",
        string="Plato nuevo", domain=lambda self: self.env["lafija.menu.day"]._option_domain(PLATE_CATEGORY_NAME))
    add_dessert_ids = fields.Many2many(
        "product.product", "lafija_menu_change_add_dessert", "wizard_id", "product_id",
        string="Postre nuevo", domain=lambda self: self.env["lafija.menu.day"]._option_domain(DESSERT_CATEGORY_NAME))
    add_drink_ids = fields.Many2many(
        "product.product", "lafija_menu_change_add_drink", "wizard_id", "product_id",
        string="Bebida nueva", domain=lambda self: self.env["lafija.menu.day"]._option_domain(DRINK_CATEGORY_NAME))
    reason = fields.Char("Motivo (opcional)")
    already_ordered = fields.Text(compute="_compute_already_ordered", string="Ya pedidos")

    @api.depends("menu_id")
    def _compute_current(self):
        for wizard in self:
            wizard.current_plate_ids = wizard.menu_id.product_ids
            wizard.current_dessert_ids = wizard.menu_id.dessert_ids
            wizard.current_drink_ids = wizard.menu_id.drink_ids

    @api.depends("sold_out_ids", "menu_id")
    def _compute_already_ordered(self):
        for wizard in self:
            reservations = wizard.menu_id.sudo().reservation_ids.filtered(lambda r: r.state == "active")
            lines = []
            for product in wizard.sold_out_ids:
                product_id = product._origin.id or product.id  # en el formulario llegan como NewId
                count = len(reservations.filtered(lambda r: product_id in (
                    r.current_product_id | r.current_dessert_id | r.current_drink_id).ids))
                lines.append(_("%(name)s: ya lo pidieron %(count)s. Esas viandas no cambian.", name=product.display_name, count=count))
            wizard.already_ordered = "\n".join(lines) if lines else False

    def action_apply(self):
        check_operator(self.env)
        self.ensure_one()
        menu = self.menu_id
        menu.check_access("write")
        if menu.date < business_today(self.env):
            raise ValidationError(_("Ese día ya pasó. Las viandas de un día pasado no se cambian desde acá."))
        added = self.add_plate_ids | self.add_dessert_ids | self.add_drink_ids
        if not (self.sold_out_ids or added):
            raise ValidationError(_("Elegí qué se agotó y, si hace falta, qué se ofrece en su lugar."))
        foreign = self.sold_out_ids - (menu.product_ids | menu.dessert_ids | menu.drink_ids)
        if foreign:
            raise ValidationError(_("Estas opciones no están en el menú: %s.", ", ".join(foreign.mapped("display_name"))))
        values = {}
        for field, new in (("product_ids", self.add_plate_ids), ("dessert_ids", self.add_dessert_ids),
                           ("drink_ids", self.add_drink_ids)):
            commands = [(3, product.id) for product in self.sold_out_ids & menu[field]]
            commands += [(4, product.id) for product in new - menu[field]]
            if commands:
                values[field] = commands
        if "product_ids" in values:
            remaining = (menu.product_ids - self.sold_out_ids) | self.add_plate_ids
            if menu.published and not remaining:
                raise ValidationError(_("El menú publicado necesita al menos un plato. Elegí un plato nuevo para reemplazar."))
        menu.with_context(lf_offer_change_reason=self.reason or "").write(values)
        return {"type": "ir.actions.client", "tag": "lf_operation_feedback", "params": {
            "close": True,
            "message": _("Listo. Desde ahora se ofrece lo nuevo en el sitio; las viandas ya pedidas se mantienen."),
        }}
