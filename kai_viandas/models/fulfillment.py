from collections import Counter, defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .identity import check_operator
from . import order_windows
from .reservation import check_operation, choice_label, operation_context
from .time_utils import business_datetime, business_today, day_label


FULFILLMENT_STATES = [
    ("to_prepare", "Por elaborar"),
    ("in_progress", "En elaboración"),
    ("prepared", "Elaborado"),
    ("delivered", "Entregado"),
]


def _move_qty(move):
    return move.quantity if "quantity" in move._fields else move.quantity_done


def _set_move_qty(move, value):
    if "quantity" in move._fields:
        move.quantity = value
    else:
        move.quantity_done = value


class Reservation(models.Model):
    _inherit = "lafija.reservation"

    fulfillment_state = fields.Selection(
        FULFILLMENT_STATES, "Estado de elaboración", default="to_prepare",
        required=True, copy=False, groups="kai_viandas.group_operator", index=True)
    fulfillment_started_at = fields.Datetime("Elaboración iniciada", readonly=True, copy=False,
                                             groups="kai_viandas.group_operator")
    fulfillment_started_by = fields.Many2one("res.users", "Elaboración iniciada por", readonly=True, copy=False,
                                             groups="kai_viandas.group_operator")
    prepared_at = fields.Datetime("Elaborada el", readonly=True, copy=False, groups="kai_viandas.group_operator")
    prepared_by = fields.Many2one("res.users", "Elaborada por", readonly=True, copy=False,
                                  groups="kai_viandas.group_operator")
    delivered_at = fields.Datetime("Entregada el", readonly=True, copy=False, groups="kai_viandas.group_operator")
    delivered_by = fields.Many2one("res.users", "Entregada por", readonly=True, copy=False,
                                   groups="kai_viandas.group_operator")
    fulfillment_product_id = fields.Many2one("product.product", "Plato en elaboración", readonly=True, copy=False,
                                             groups="kai_viandas.group_operator")
    fulfillment_dessert_id = fields.Many2one("product.product", "Postre en elaboración", readonly=True, copy=False,
                                             groups="kai_viandas.group_operator")
    fulfillment_drink_id = fields.Many2one("product.product", "Bebida en elaboración", readonly=True, copy=False,
                                           groups="kai_viandas.group_operator")
    fulfillment_production_ids = fields.Many2many(
        "mrp.production", "lafija_reservation_mrp_rel", "reservation_id", "production_id",
        string="Órdenes de fabricación", copy=False, groups="kai_viandas.group_operator")
    lf_quotation_id = fields.Many2one(
        "sale.order", "Presupuesto", copy=False, index=True,
        groups="kai_viandas.group_operator")
    lf_quotation_added = fields.Boolean(
        "En presupuesto", compute="_compute_lf_quotation_added", store=True,
        groups="kai_viandas.group_operator")
    lf_daily_order_id = fields.Many2one(
        related="lf_quotation_id", string="Presupuesto",
        groups="kai_viandas.group_operator")
    fulfillment_label = fields.Char("Elaboración y entrega", compute="_compute_fulfillment_label",
                                    groups="kai_viandas.group_operator")
    on_taken_list = fields.Boolean("En lista tomada vigente", compute="_compute_on_taken_list",
                                   search="_search_on_taken_list", groups="kai_viandas.group_operator")
    to_deliver = fields.Boolean("Por entregar", compute="_compute_to_deliver", search="_search_to_deliver",
                                groups="kai_viandas.group_operator")
    currency_id = fields.Many2one(
        "res.currency", "Moneda", compute="_compute_lf_amount", store=True,
        groups="kai_viandas.group_operator")
    lf_amount = fields.Monetary(
        "Monto", compute="_compute_lf_amount", store=True, currency_field="currency_id",
        groups="kai_viandas.group_operator")

    _LF_COMMERCIAL_SYNC_FIELDS = {
        "state", "current_product_id", "current_dessert_id", "current_drink_id",
        "customer_company_id", "date", "website_id",
    }

    @api.depends("lf_quotation_id")
    def _compute_lf_quotation_added(self):
        for record in self:
            record.lf_quotation_added = bool(record.lf_quotation_id)

    @api.depends(
        "state", "lf_quotation_id",
        "current_product_id", "current_dessert_id", "current_drink_id",
        "customer_company_id", "date", "website_id", "website_id.company_id",
    )
    def _compute_lf_amount(self):
        for record in self:
            seller = record._lf_seller_company()
            record.currency_id = seller.currency_id
            # El monto se muestra solo cuando la vianda ya está en el presupuesto.
            if not record.lf_quotation_id or record.state != "active":
                record.lf_amount = 0.0
                continue
            partner = record.customer_company_id
            amount = 0.0
            for product in (record.current_product_id, record.current_dessert_id, record.current_drink_id):
                amount += record._lf_product_unit_price(product, partner, seller, record.date)
            record.lf_amount = amount

    def _lf_seller_company(self):
        self.ensure_one()
        return self.website_id.company_id or self.env.company

    def _lf_commercial_key(self):
        self.ensure_one()
        return (self.customer_company_id.id, self.date, self._lf_seller_company().id)

    @api.model
    def _lf_product_unit_price(self, product, partner, company, day=None):
        if not product:
            return 0.0
        product = product.sudo().with_company(company) if company else product.sudo()
        partner = partner.sudo().with_company(company) if partner and company else (partner.sudo() if partner else partner)
        pricelist = partner.property_product_pricelist if partner else False
        if not pricelist:
            return product.lst_price or 0.0
        try:
            price = pricelist._get_product_price(
                product, quantity=1.0, uom=product.uom_id, date=day,
                currency=company.currency_id if company else False,
            )
        except TypeError:
            price = pricelist._get_product_price(product, 1.0)
        return price or 0.0

    def _lf_wanted_products(self):
        wanted = Counter()
        for record in self:
            if record.state != "active" and record.fulfillment_state != "delivered":
                continue
            if record.current_product_id:
                wanted[record.current_product_id] += 1
            if record.current_dessert_id:
                wanted[record.current_dessert_id] += 1
            if record.current_drink_id:
                wanted[record.current_drink_id] += 1
        return wanted

    def _lf_sync_progressive_daily_orders(self):
        """Reajusta solo los presupuestos de viandas ya agregadas."""
        self._lf_sync_quoted_keys({record._lf_commercial_key() for record in self if record.lf_quotation_id})

    @api.model
    def _lf_sync_quoted_keys(self, keys, confirm=False):
        Reservation = self.env["lafija.reservation"]
        skip = dict(self.env.context, lf_skip_daily_order_sync=True, **operation_context())
        for partner_id, day, company_id in keys:
            if not (partner_id and day and company_id):
                continue
            partner = self.env["res.partner"].browse(partner_id)
            seller = self.env["res.company"].browse(company_id)
            records = Reservation.search([
                ("customer_company_id", "=", partner_id),
                ("date", "=", day),
                ("lf_quotation_id", "!=", False),
            ])
            records = records.filtered(lambda rec: rec._lf_seller_company().id == company_id)
            wanted = records._lf_wanted_products()
            order = Reservation._lf_upsert_company_daily_order(
                partner, day, seller, records, wanted, confirm=False,
                origin=_("Viandas %s · %s") % (day, partner.name),
            )
            if order and order.state != "cancel":
                records.with_context(**skip).write({"lf_quotation_id": order.id})
            elif records:
                records.with_context(**skip).write({"lf_quotation_id": False})

    @api.model
    def _lf_upsert_company_daily_order(self, partner, day, seller, reservations, wanted, confirm=False, origin=None):
        wanted = Counter(wanted)
        Order = self.env["sale.order"].sudo().with_company(seller)
        order = Order.search([
            ("lf_preparation_date", "=", day),
            ("partner_id", "=", partner.id),
            ("company_id", "=", seller.id),
            ("state", "!=", "cancel"),
        ], limit=1, order="id desc")
        if order:
            delivered_qty = Counter()
            for record in order.lf_reservation_ids.filtered(lambda rec: rec.fulfillment_state == "delivered"):
                if record.current_product_id:
                    delivered_qty[record.current_product_id] += 1
                if record.current_dessert_id:
                    delivered_qty[record.current_dessert_id] += 1
                if record.current_drink_id:
                    delivered_qty[record.current_drink_id] += 1
            for product, qty in delivered_qty.items():
                wanted[product] = max(wanted[product], qty)
        if not order and not wanted:
            return order
        if order and not wanted and order.state in ("draft", "sent"):
            order.with_context(disable_cancel_warning=True).action_cancel()
            return order
        line_name = lambda product: _("%s\nViandas %s · %s") % (product.display_name, day, partner.name)
        if not order:
            line_vals = []
            for product, qty in wanted.items():
                if not qty:
                    continue
                line_vals.append({
                    "product_id": product.id,
                    "product_uom_qty": qty,
                    "name": line_name(product),
                })
            if not line_vals:
                return order
            order = Order.create({
                "partner_id": partner.id,
                "company_id": seller.id,
                "lf_preparation_date": day,
                "lf_reservation_ids": [(6, 0, reservations.ids)],
                "origin": origin or _("Viandas %s · %s") % (day, partner.name),
                "order_line": [(0, 0, values) for values in line_vals],
            })
            if confirm and order.state in ("draft", "sent"):
                order.action_confirm()
            return order
        order.write({
            "lf_reservation_ids": [(6, 0, list(set(order.lf_reservation_ids.ids) | set(reservations.ids)))],
        })
        existing = {line.product_id: line for line in order.order_line.filtered(lambda line: not line.display_type)}
        for product, qty in list(wanted.items()):
            if not qty:
                continue
            price = self._lf_product_unit_price(product, partner, seller, day)
            line = existing.pop(product, False)
            if line:
                new_qty = max(qty, line.qty_delivered or 0)
                values = {"product_uom_qty": new_qty}
                if not line.qty_invoiced and abs((line.price_unit or 0.0) - price) > 0.0001:
                    values["price_unit"] = price
                if any(line[field] != values[field] for field in values):
                    line.write(values)
            else:
                order.order_line.create({
                    "order_id": order.id,
                    "product_id": product.id,
                    "product_uom_qty": qty,
                    "name": line_name(product),
                    "price_unit": price,
                })
        for leftover in existing.values():
            if leftover.qty_delivered:
                if leftover.product_uom_qty != leftover.qty_delivered:
                    leftover.write({"product_uom_qty": leftover.qty_delivered})
            else:
                leftover.write({"product_uom_qty": 0})
        if confirm and order.state in ("draft", "sent"):
            order.action_confirm()
        if order.state not in ("draft", "sent", "cancel"):
            order._lf_sync_outgoing_to_delivered()
        return order

    @api.depends("fulfillment_state")
    def _compute_fulfillment_label(self):
        labels = dict(FULFILLMENT_STATES)
        for record in self:
            record.fulfillment_label = labels.get(record.fulfillment_state) or ""

    lf_can_change = fields.Boolean(
        "Se puede cambiar", compute="_compute_lf_can_change", groups="kai_viandas.group_operator")

    # Campos editables en la lista Pedidos (multi_edit): muestran la vianda vigente y, al guardar,
    # aplican «Cambiar elección antes del corte» (mismas validaciones y mismo movimiento entre OF).
    lf_new_product_id = fields.Many2one(
        "product.product", "Elección vigente", compute="_compute_lf_edit_choice",
        inverse="_inverse_lf_edit_choice", groups="kai_viandas.group_operator")
    lf_new_dessert_id = fields.Many2one(
        "product.product", "Postre", compute="_compute_lf_edit_choice",
        inverse="_inverse_lf_edit_choice", groups="kai_viandas.group_operator")
    lf_new_drink_id = fields.Many2one(
        "product.product", "Bebida", compute="_compute_lf_edit_choice",
        inverse="_inverse_lf_edit_choice", groups="kai_viandas.group_operator")
    lf_offer_product_ids = fields.Many2many(
        "product.product", "lafija_reservation_offer_plate", compute="_compute_lf_offer",
        groups="kai_viandas.group_operator")
    lf_offer_dessert_ids = fields.Many2many(
        "product.product", "lafija_reservation_offer_dessert", compute="_compute_lf_offer",
        groups="kai_viandas.group_operator")
    lf_offer_drink_ids = fields.Many2many(
        "product.product", "lafija_reservation_offer_drink", compute="_compute_lf_offer",
        groups="kai_viandas.group_operator")

    @api.depends("current_product_id", "current_dessert_id", "current_drink_id")
    def _compute_lf_edit_choice(self):
        for record in self:
            record.lf_new_product_id = record.current_product_id
            record.lf_new_dessert_id = record.current_dessert_id
            record.lf_new_drink_id = record.current_drink_id

    @api.depends("menu_id.product_ids", "menu_id.dessert_ids", "menu_id.drink_ids",
                 "current_product_id", "current_dessert_id", "current_drink_id")
    def _compute_lf_offer(self):
        for record in self:
            menu = record.sudo().menu_id
            record.lf_offer_product_ids = menu.product_ids | record.current_product_id
            record.lf_offer_dessert_ids = menu.dessert_ids | record.current_dessert_id
            record.lf_offer_drink_ids = menu.drink_ids | record.current_drink_id

    _LF_INLINE_FIELDS = ("lf_new_product_id", "lf_new_dessert_id", "lf_new_drink_id")

    def _inverse_lf_edit_choice(self):
        """Sin efecto: `write` aplica el cambio antes (ver _lf_inline_change)."""

    def _lf_inline_change(self, edited):
        """Guardar desde la lista = «Cambiar elección antes del corte», vianda por vianda.

        `edited` trae solo lo que se tocó en la lista; lo demás se toma de cada vianda.
        """
        check_operator(self.env)
        Correction = self.env["lafija.reservation.correction"]
        Product = self.env["product.product"]
        for record in self:
            current = record.sudo()
            product = Product.browse(edited["lf_new_product_id"]) if "lf_new_product_id" in edited else current.current_product_id
            dessert = Product.browse(edited["lf_new_dessert_id"]) if "lf_new_dessert_id" in edited else current.current_dessert_id
            drink = Product.browse(edited["lf_new_drink_id"]) if "lf_new_drink_id" in edited else current.current_drink_id
            if (product, dessert, drink) == (
                    current.current_product_id, current.current_dessert_id, current.current_drink_id):
                continue
            if current.pending_product_id or current.pending_dessert_id or current.pending_drink_id:
                raise ValidationError(_(
                    "%s tiene un cambio pendiente: resolvelo con «Editar» antes de cambiar la elección.",
                    current.name))
            try:
                Correction.create({
                    "reservation_id": record.id, "operation": "change",
                    "product_id": product.id, "dessert_id": dessert.id, "drink_id": drink.id,
                    "reason": _("Cambio desde la lista de Pedidos"),
                }).action_apply()
            except ValidationError as error:
                raise ValidationError(_("%(name)s: %(error)s", name=current.name, error=error.args[0])) from error

    def _lf_change_block_reason(self):
        """Por qué ya no se puede cambiar la elección de esta vianda (o False si se puede).

        Se puede hasta el corte del día de elaboración (10:30, hora de La Fija) y mientras la
        vianda siga «Por elaborar» y sus órdenes de fabricación estén en borrador.
        """
        self.ensure_one()
        record = self.sudo()
        if record.state != "active":
            return _("La vianda está cancelada.")
        cutoff = order_windows.daily_cutoff_datetime(self.env, record.date)
        if fields.Datetime.now() >= cutoff:
            return _(
                "Pasó el corte de las %(hour)s del %(day)s (hora de La Fija): la elección ya no se puede cambiar.",
                hour=order_windows.daily_cutoff_label(self.env), day=day_label(record.date))
        labels = dict(FULFILLMENT_STATES)
        if record.fulfillment_state != "to_prepare":
            return _(
                "La vianda ya está «%s»: no se puede cambiar la elección.",
                labels.get(record.fulfillment_state, record.fulfillment_state))
        started = record.fulfillment_production_ids.filtered(lambda mo: mo.state not in ("draft", "cancel"))
        if started:
            return _(
                "La orden de fabricación %(names)s ya está confirmada o empezó: no se puede cambiar la elección.",
                names=", ".join(started.mapped("name")))
        return False

    @api.depends("state", "date", "fulfillment_state", "fulfillment_production_ids.state")
    def _compute_lf_can_change(self):
        for record in self:
            record.lf_can_change = not record._lf_change_block_reason()

    def action_change_choice(self):
        """Abre «Editar» ya en «Corregir opción», con la elección vigente cargada."""
        check_operator(self.env)
        self.ensure_one()
        reason = self._lf_change_block_reason()
        if reason:
            raise ValidationError(reason)
        record = self.sudo()
        return {"type": "ir.actions.act_window", "name": _("Cambiar vianda"),
                "res_model": "lafija.reservation.correction", "view_mode": "form", "target": "new",
                "context": {"default_reservation_id": self.id, "default_operation": "change",
                            "default_product_id": record.current_product_id.id,
                            "default_dessert_id": record.current_dessert_id.id,
                            "default_drink_id": record.current_drink_id.id}}

    def _current_preparation_line(self):
        self.ensure_one()
        cut = self.sudo().menu_id.cut_ids[:1]
        if not cut or not cut.current_revision_id:
            return self.env["lafija.preparation.line"]
        return cut.current_revision_id.line_ids.filtered(lambda line: line.reservation_id == self)[:1]

    def _compute_on_taken_list(self):
        for record in self:
            record.on_taken_list = bool(record._current_preparation_line())

    def _search_on_taken_list(self, operator, value):
        lines = self.env["lafija.preparation.line"].sudo().search([])
        current = lines.filtered(lambda line: line.revision_id == line.revision_id.cut_id.current_revision_id)
        ids = current.reservation_id.ids
        positive = (operator in ("=",) and value) or (operator in ("!=",) and not value)
        return [("id", "in" if positive else "not in", ids)]

    @api.depends("fulfillment_state", "menu_id.cut_ids.current_revision_id")
    def _compute_to_deliver(self):
        for record in self:
            record.to_deliver = record.fulfillment_state == "prepared" and record.on_taken_list

    def _search_to_deliver(self, operator, value):
        records = self.search([("fulfillment_state", "=", "prepared"), ("on_taken_list", "=", True)])
        positive = (operator in ("=",) and value) or (operator in ("!=",) and not value)
        return [("id", "in" if positive else "not in", records.ids)]

    def write(self, values):
        inline = {name: values[name] for name in self._LF_INLINE_FIELDS if name in values}
        if inline:
            values = {key: value for key, value in values.items() if key not in inline}
            self._lf_inline_change(inline)
            if not values:
                return True
        tracked = {
            "fulfillment_state", "fulfillment_started_at", "fulfillment_started_by",
            "prepared_at", "prepared_by", "delivered_at", "delivered_by",
            "fulfillment_product_id", "fulfillment_dessert_id", "fulfillment_drink_id",
            "fulfillment_production_ids",
        }
        if set(values) & tracked:
            check_operation(self.env)
        skip = self.env.context.get("lf_skip_daily_order_sync")
        keys = set()
        quoted = self.env["lafija.reservation"]
        if not skip and set(values) & self._LF_COMMERCIAL_SYNC_FIELDS:
            quoted = self.filtered("lf_quotation_id")
            keys = {record._lf_commercial_key() for record in quoted}
        result = super().write(values)
        if set(values) & {"current_product_id", "current_dessert_id", "current_drink_id", "state"}:
            self._lf_reset_fulfillment_if_choice_changed()
            if not self.env.context.get("_lf_syncing_mos"):
                self._lf_accumulate_productions()
        if not skip and set(values) & self._LF_COMMERCIAL_SYNC_FIELDS:
            quoted |= self.filtered("lf_quotation_id")
            if quoted:
                keys |= {record._lf_commercial_key() for record in quoted}
                self._lf_sync_quoted_keys(keys)
        return result

    def _lf_reset_fulfillment_if_choice_changed(self):
        records = self.sudo()
        records.invalidate_recordset([
            "fulfillment_state", "fulfillment_product_id", "fulfillment_dessert_id",
            "fulfillment_drink_id", "current_product_id", "current_dessert_id",
            "current_drink_id", "state",
        ])
        for record in records:
            if record.fulfillment_state in ("to_prepare", "delivered"):
                continue
            if record.state != "active":
                continue
            marked = (record.fulfillment_product_id, record.fulfillment_dessert_id, record.fulfillment_drink_id)
            current = (record.current_product_id, record.current_dessert_id, record.current_drink_id)
            if record.fulfillment_product_id and marked != current:
                record._lf_set_state(
                    "to_prepare",
                    _("La vianda vigente cambió; hay que elaborarla de nuevo. "
                      "Si quedó una orden de fabricación confirmada, su cantidad no se revierte sola."),
                )

    def _lf_require_taken_list(self):
        missing = self.filtered(lambda record: not record.sudo()._current_preparation_line())
        if missing:
            raise ValidationError(_("Solo se puede elaborar o entregar una vianda que esté en una lista tomada vigente."))

    def _lf_feedback(self, message, warning=False):
        return {"type": "ir.actions.client", "tag": "lf_operation_feedback", "params": {
            "message": message, "type": "warning" if warning else "success",
        }}

    def action_add_to_quotation(self):
        """Agrega viandas elaboradas o entregadas al presupuesto diario de su empresa."""
        check_operator(self.env)
        records = self.sudo()
        already = records.filtered("lf_quotation_id")
        not_ready = records.filtered(
            lambda rec: not rec.lf_quotation_id and rec.fulfillment_state not in ("prepared", "delivered"))
        todo = records.filtered(
            lambda rec: not rec.lf_quotation_id and rec.fulfillment_state in ("prepared", "delivered")
            and rec.current_product_id)
        if not todo:
            if already and not not_ready:
                return self._lf_feedback(
                    _("Esas viandas ya están en un presupuesto: %s.") % ", ".join(already.mapped("name")),
                    warning=True)
            raise ValidationError(_(
                "Elegí viandas elaboradas o entregadas que todavía no estén en un presupuesto."))
        groups = defaultdict(lambda: self.env["lafija.reservation"])
        for record in todo:
            groups[record._lf_commercial_key()] |= record
        skip = dict(self.env.context, lf_skip_daily_order_sync=True, **operation_context())
        added = self.env["lafija.reservation"]
        for (partner_id, day, company_id), batch in groups.items():
            if not (partner_id and day and company_id):
                continue
            partner = self.env["res.partner"].browse(partner_id)
            seller = self.env["res.company"].browse(company_id)
            existing = self.env["lafija.reservation"].search([
                ("customer_company_id", "=", partner_id),
                ("date", "=", day),
                ("lf_quotation_id", "!=", False),
            ]).filtered(lambda rec: rec._lf_seller_company().id == company_id)
            members = existing | batch
            wanted = members._lf_wanted_products()
            order = self._lf_upsert_company_daily_order(
                partner, day, seller, members, wanted, confirm=False,
                origin=_("Viandas %s · %s") % (day, partner.name),
            )
            if not order or order.state == "cancel":
                continue
            batch.with_context(**skip).write({"lf_quotation_id": order.id})
            added |= batch
        message = _("Se agregaron %s vianda(s) al presupuesto.") % len(added)
        if already:
            message = _("%s Ya estaban en un presupuesto: %s.") % (
                message, ", ".join(already.mapped("name")))
        if not_ready:
            message = _("%s No se agregaron (todavía no están elaboradas): %s.") % (
                message, ", ".join(not_ready.mapped("name")))
        return self._lf_feedback(message, warning=bool(already or not_ready or not added))

    def _lf_migrate_explicit_quotations(self):
        """Pasa el pedido diario a un paso explícito: quita borradores no elaborados y marca los ya facturables."""
        skip = dict(self.env.context, lf_skip_daily_order_sync=True, **operation_context())
        Reservation = self.env["lafija.reservation"].sudo().with_context(**skip)
        Order = self.env["sale.order"].sudo()
        orders = Order.search([("lf_preparation_date", "!=", False), ("state", "!=", "cancel")])
        kept_confirmed = Reservation
        kept_draft = Reservation
        unlinked = Reservation
        cancelled_drafts = Order
        for order in orders:
            linked = order.lf_reservation_ids
            if order.state not in ("draft", "sent"):
                if linked:
                    linked.write({"lf_quotation_id": order.id})
                    kept_confirmed |= linked
                continue
            keep = linked.filtered(lambda rec: rec.fulfillment_state in ("prepared", "delivered"))
            drop = linked - keep
            if drop:
                order.write({"lf_reservation_ids": [(3, rec.id) for rec in drop]})
                drop.write({"lf_quotation_id": False})
                unlinked |= drop
            members = keep
            wanted = members._lf_wanted_products()
            if not wanted:
                if order.state in ("draft", "sent"):
                    order.with_context(disable_cancel_warning=True).action_cancel()
                    cancelled_drafts |= order
                    if keep:
                        keep.write({"lf_quotation_id": False})
                continue
            refreshed = Reservation._lf_upsert_company_daily_order(
                order.partner_id, order.lf_preparation_date, order.company_id,
                members, wanted, confirm=False, origin=order.origin)
            if refreshed and refreshed.state != "cancel" and keep:
                keep.write({"lf_quotation_id": refreshed.id})
                kept_draft |= keep
        summary = {
            "kept_confirmed": kept_confirmed.mapped("name"),
            "kept_confirmed_ids": kept_confirmed.ids,
            "kept_draft": kept_draft.mapped("name"),
            "kept_draft_ids": kept_draft.ids,
            "unlinked": unlinked.mapped("name"),
            "unlinked_ids": unlinked.ids,
            "cancelled_drafts": cancelled_drafts.mapped("name"),
            "cancelled_draft_ids": cancelled_drafts.ids,
        }
        self.env["ir.config_parameter"].sudo().set_param(
            "kai_viandas.migration_1176", repr(summary))
        return summary

    def _lf_ensure_lists_for_elaboration(self):
        """Tomar la lista del día (o incorporar las viandas a la vigente) para poder elaborar y crear OF."""
        for menu in self.menu_id:
            cut = menu.sudo().cut_ids[:1]
            if not cut:
                menu.action_take_list()
                continue
            missing = self.filtered(
                lambda record, menu=menu: record.menu_id == menu and record.state == "active"
                and not record.sudo()._current_preparation_line())
            if missing:
                cut.with_context(**operation_context())._new_revision(
                    _("Incorporar viandas para elaborar"), self.env.user)

    def _lf_accept_pending_for_elaboration(self):
        """Al elaborar, aplicar antes la elección pendiente (igual que Editar → Aplicar)."""
        pending = self.filtered(
            lambda record: record.state != "cancelled"
            and (record.pending_product_id or record.pending_dessert_id or record.pending_drink_id)
        )
        if not pending:
            return pending
        Correction = self.env["lafija.reservation.correction"]
        reason = _("Elaborar: se aplica la elección pendiente")
        for record in pending:
            Correction.create({
                "reservation_id": record.id,
                "operation": "accept",
                "reason": reason,
            }).action_apply()
        return pending

    def action_elaborate(self):
        """Aplica una elección pendiente, si hay, y deja la vianda en su OF en borrador.

        Ya no confirma la orden: eso lo hace el chef en Manufactura o en
        Producción del día.
        """
        check_operator(self.env)
        self._lf_accept_pending_for_elaboration()
        self.invalidate_recordset()
        self._lf_accumulate_productions()
        linked = self.sudo().filtered("fulfillment_production_ids")
        if len(self) == 1 and linked.fulfillment_production_ids:
            return self.action_open_production()
        if linked:
            return self._lf_feedback(
                _("Las viandas quedaron en la orden de fabricación del plato y el día (en borrador). "
                  "El chef la confirma en Manufactura o en Pedidos → Producción del día."))
        return self._lf_feedback(
            _("No hay una orden de fabricación para esas viandas (falta lista de materiales o no están vigentes)."),
            warning=True)

    def action_mark_delivered(self):

        check_operator(self.env)
        self._lf_require_taken_list()
        todo = self.sudo().filtered(lambda record: record.fulfillment_state == "prepared")
        if not todo:
            raise ValidationError(_("Solo se puede marcar «Entregado» una vianda ya elaborada."))
        notices = todo._lf_validate_delivery_pickings()
        moment = fields.Datetime.now()
        for record in todo:
            record.with_context(**operation_context()).write({
                "fulfillment_state": "delivered",
                "delivered_at": moment,
                "delivered_by": self.env.uid,
            })
            label = choice_label(record.current_description, record.current_dessert_description,
                                 record.current_drink_description)
            record._record_event(self.env.user, moment, "fulfillment", label, "", label, "Entregada")
            record.message_post(body=_("Vianda marcada como entregada."),
                                author_id=self.env.user.partner_id.id, subtype_xmlid="mail.mt_note")
        message = _("Se entregaron %s vianda(s).") % len(todo)
        if notices:
            message = "%s %s" % (message, " ".join(notices))
        return self._lf_feedback(message, warning=bool(notices))

    def action_unmark_delivered(self):
        check_operator(self.env)
        todo = self.sudo().filtered(lambda record: record.fulfillment_state == "delivered")
        if not todo:
            raise ValidationError(_("Elegí viandas entregadas para deshacer la marca."))
        moment = fields.Datetime.now()
        for record in todo:
            record.with_context(**operation_context()).write({
                "fulfillment_state": "prepared",
                "delivered_at": False,
                "delivered_by": False,
            })
            label = choice_label(record.current_description, record.current_dessert_description,
                                 record.current_drink_description)
            record._record_event(self.env.user, moment, "fulfillment", label, "", label,
                                 "Se deshizo la marca de entregada")
            record.message_post(
                body=_("Se deshizo la marca de entregada. El remito de salida no se revierte solo; "
                       "si hace falta, hacé una devolución en Inventario."),
                author_id=self.env.user.partner_id.id, subtype_xmlid="mail.mt_note")
        return self._lf_feedback(
            _("Se deshizo la entrega de %s vianda(s). El remito no se revierte automáticamente.") % len(todo),
            warning=True)

    def _lf_set_state(self, state, result):
        values = {"fulfillment_state": state}
        if state == "to_prepare":
            values.update({
                "fulfillment_started_at": False, "fulfillment_started_by": False,
                "prepared_at": False, "prepared_by": False,
                "fulfillment_product_id": False, "fulfillment_dessert_id": False, "fulfillment_drink_id": False,
            })
        elif state == "prepared":
            values.update({"prepared_at": fields.Datetime.now(), "prepared_by": self.env.uid})
        for record in self:
            if record.fulfillment_state == "delivered":
                continue
            record.with_context(**operation_context()).write(values)
            label = choice_label(record.current_description, record.current_dessert_description,
                                 record.current_drink_description)
            record._record_event(self.env.user, fields.Datetime.now(), "fulfillment", label, "", label, result)
            record.message_post(body=result, author_id=self.env.user.partner_id.id, subtype_xmlid="mail.mt_note")

    def _lf_enter_progress(self):
        moment = fields.Datetime.now()
        for record in self:
            record.with_context(**operation_context()).write({
                "fulfillment_state": "in_progress",
                "fulfillment_started_at": moment,
                "fulfillment_started_by": self.env.uid,
                "fulfillment_product_id": record.current_product_id.id,
                "fulfillment_dessert_id": record.current_dessert_id.id,
                "fulfillment_drink_id": record.current_drink_id.id,
                "prepared_at": False, "prepared_by": False,
            })
            names = ", ".join(record.fulfillment_production_ids.mapped("name"))
            label = choice_label(record.current_description, record.current_dessert_description,
                                 record.current_drink_description)
            result = _("En elaboración · orden %s") % names
            record._record_event(self.env.user, moment, "fulfillment", label, "", label, result)
            record.message_post(body=result, author_id=self.env.user.partner_id.id, subtype_xmlid="mail.mt_note")

    def _lf_bom_for(self, product, company):
        if not product or "mrp.bom" not in self.env:
            return self.env["mrp.bom"]
        domain = [
            ("type", "=", "normal"), ("active", "=", True),
            ("company_id", "in", [False, company.id]),
            "|", ("product_id", "=", product.id),
            "&", ("product_id", "=", False), ("product_tmpl_id", "=", product.product_tmpl_id.id),
        ]
        return self.env["mrp.bom"].sudo().search(domain, order="product_id, sequence, id", limit=1)

    def _lf_daily_order(self):
        return self._lf_daily_orders()[:1]

    @api.model
    def _lf_format_production_origin(self, records, product=None):
        """Origen legible de la OF compartida: «fecha · plato» (los pedidos viven en la pestaña Viandas)."""
        product = product or (records[:1].current_product_id if records else self.env["product.product"])
        day = records[:1].date if records else False
        day_txt = str(day) if day else ""
        name = product.display_name if product else ""
        if day_txt and name:
            return _("%s · %s") % (day_txt, name)
        return day_txt or name or ""

    @api.model
    def _lf_apply_production_refs(self, mo, records):
        # Las OF hechas (p.ej. WH/MO/00005) conservan su origen histórico.
        if not mo or mo.state == "done":
            return
        values = {"origin": self._lf_format_production_origin(records, product=mo.product_id)}
        orders = records._lf_daily_orders() if records else self.env["sale.order"]
        if orders:
            values["lf_sale_order_id"] = orders[:1].id
        if mo.origin != values["origin"] or ("lf_sale_order_id" in values and mo.lf_sale_order_id.id != values["lf_sale_order_id"]):
            mo.sudo().write(values)

    def _lf_wanted_production_groups(self, reservations):
        """Agrupar por plato y día (todas las empresas juntas); acompañamientos solo si tienen receta.

        La empresa de fabricación (website o compañía del entorno) sigue en la clave
        para no mezclar OF de distintas compañías de Odoo.
        """
        groups = []
        skipped = []
        by_plate = defaultdict(lambda: self.env["lafija.reservation"])
        for record in reservations:
            if not record.current_product_id:
                continue
            company = record.website_id.company_id or record.env.company
            by_plate[(record.date, company.id, record.current_product_id.id)] |= record
        for (_day, company_id, product_id), records in by_plate.items():
            product = self.env["product.product"].browse(product_id)
            company = self.env["res.company"].browse(company_id)
            partner = records[:1].customer_company_id
            bom = records[:1]._lf_bom_for(product, company)
            if not bom:
                skipped.append(product.display_name)
            else:
                groups.append({
                    "records": records, "product": product, "company": company,
                    "partner": partner, "qty": len(records), "bom": bom,
                })
            for side_field in ("current_dessert_id", "current_drink_id"):
                sides = defaultdict(lambda: self.env["lafija.reservation"])
                for record in records:
                    side = record[side_field]
                    if side:
                        sides[side.id] |= record
                for side_id, side_records in sides.items():
                    side = self.env["product.product"].browse(side_id)
                    side_bom = side_records[:1]._lf_bom_for(side, company)
                    if not side_bom:
                        continue
                    groups.append({
                        "records": side_records, "product": side, "company": company,
                        "partner": partner, "qty": len(side_records), "bom": side_bom,
                    })
        return groups, skipped

    def _lf_make_production(self, group, confirm=False):
        Production = self.env["mrp.production"].sudo()
        records = group["records"]
        orders = records._lf_daily_orders()
        day = records[:1].date
        mo = Production.with_company(group["company"]).create({
            "product_id": group["product"].id,
            "product_qty": group["qty"],
            "product_uom_id": group["product"].uom_id.id,
            "bom_id": group["bom"].id,
            "origin": self._lf_format_production_origin(records, product=group["product"]),
            "lf_sale_order_id": orders[:1].id if orders else False,
            "lf_meal_date": day,
            "company_id": group["company"].id,
        })
        records.with_context(_lf_syncing_mos=True, **operation_context()).write({
            "fulfillment_production_ids": [(4, mo.id)],
        })
        if confirm:
            mo.action_confirm()
        return mo

    def _lf_meal_company(self):
        self.ensure_one()
        return self.website_id.company_id or self.env.company

    def _lf_wanted_mo_products(self):
        self.ensure_one()
        if self.state != "active" or not self.current_product_id:
            return self.env["product.product"]
        company = self._lf_meal_company()
        products = self.env["product.product"]
        for product in self.current_product_id | self.current_dessert_id | self.current_drink_id:
            if product and self._lf_bom_for(product, company):
                products |= product
        return products

    def _lf_mo_meal_date(self, mo):
        return mo.lf_meal_date or mo.lf_reservation_ids[:1].date

    def _lf_find_draft_mo(self, product, day, company):
        drafts = self.env["mrp.production"].sudo().search([
            ("product_id", "=", product.id),
            ("company_id", "=", company.id),
            ("state", "=", "draft"),
            ("lf_reservation_ids", "!=", False),
        ])
        for mo in drafts:
            if self._lf_mo_meal_date(mo) == day:
                return mo
        # Borradores recién creados en esta misma transacción, aún sin viandas.
        empty = self.env["mrp.production"].sudo().search([
            ("product_id", "=", product.id),
            ("company_id", "=", company.id),
            ("state", "=", "draft"),
            ("lf_meal_date", "=", day),
            ("lf_reservation_ids", "=", False),
        ], limit=1)
        return empty

    def _lf_link_to_draft_mo(self, mo):
        self.ensure_one()
        if mo in self.fulfillment_production_ids:
            return mo
        self.with_context(_lf_syncing_mos=True, **operation_context()).write({
            "fulfillment_production_ids": [(4, mo.id)],
        })
        values = {}
        if not mo.lf_meal_date:
            values["lf_meal_date"] = self.date
        if values:
            mo.sudo().write(values)
        self._lf_set_production_qty(mo, len(mo.lf_reservation_ids))
        self._lf_apply_production_refs(mo, mo.lf_reservation_ids)
        return mo

    def _lf_unlink_from_mo(self, mo):
        self.ensure_one()
        if mo not in self.fulfillment_production_ids:
            return
        self.with_context(_lf_syncing_mos=True, **operation_context()).write({
            "fulfillment_production_ids": [(3, mo.id)],
        })
        if mo.state == "draft":
            remaining = mo.lf_reservation_ids
            if remaining:
                self._lf_set_production_qty(mo, len(remaining))
                self._lf_apply_production_refs(mo, remaining)
            else:
                mo.with_context(_lf_syncing_drafts=True, _lf_syncing_mos=True).action_cancel()
        elif mo.state != "cancel":
            mo.message_post(
                body=_("Se desvinculó la vianda %s. La cantidad de esta orden (ya no está en borrador) no se modifica.")
                % self.name,
                subtype_xmlid="mail.mt_note",
            )

    def _lf_accumulate_productions(self):
        """Crear o ajustar la OF en borrador por plato y día al quedar la vianda vigente.

        Si la OF de ese plato y día ya está confirmada, una vianda nueva va a otra
        OF en borrador; una que sale se desvincula y queda asentado en la orden.
        """
        if self.env.context.get("_lf_syncing_mos"):
            return
        records = self.sudo()
        for record in records:
            company = record._lf_meal_company()
            wanted = record._lf_wanted_mo_products()
            linked = record.fulfillment_production_ids.filtered(lambda mo: mo.state != "cancel")
            for mo in linked:
                if mo.product_id not in wanted:
                    record._lf_unlink_from_mo(mo)
            record.invalidate_recordset(["fulfillment_production_ids"])
            linked = record.fulfillment_production_ids.filtered(lambda mo: mo.state != "cancel")
            for product in wanted:
                if linked.filtered(lambda mo, product=product: mo.product_id == product):
                    continue
                draft = record._lf_find_draft_mo(product, record.date, company)
                if draft:
                    record._lf_link_to_draft_mo(draft)
                    continue
                bom = record._lf_bom_for(product, company)
                if not bom:
                    continue
                record._lf_make_production({
                    "records": record, "product": product, "company": company,
                    "partner": record.customer_company_id, "qty": 1, "bom": bom,
                }, confirm=False)

    @api.model
    def _lf_migrate_accumulate_mos_1177(self, exclude_names=None):
        """Vincular viandas vigentes sueltas a la OF en borrador de su plato y día."""
        exclude_names = set(exclude_names or [])
        records = self.sudo().search([
            ("state", "=", "active"),
            ("current_product_id", "!=", False),
        ])
        records = records.filtered(lambda rec: rec.name not in exclude_names)
        # Completar la fecha en OF ya existentes.
        mos = records.fulfillment_production_ids
        for mo in mos.filtered(lambda production: not production.lf_meal_date):
            day = mo.lf_reservation_ids[:1].date
            if day:
                mo.sudo().write({"lf_meal_date": day})
        records._lf_accumulate_productions()
        return records

    def _lf_mo_migration_snapshot(self):
        mos = self.env["mrp.production"].sudo().search([
            "|", ("lf_meal_date", "!=", False), ("lf_reservation_ids", "!=", False),
        ], order="lf_meal_date, product_id, id")
        snapshot = {}
        for mo in mos:
            snapshot[mo.id] = {
                "id": mo.id,
                "name": mo.name,
                "product": mo.product_id.display_name,
                "date": str(mo.lf_meal_date or mo.lf_reservation_ids[:1].date or ""),
                "qty": mo.product_qty,
                "state": mo.state,
                "viandas": mo.lf_reservation_ids.mapped("name"),
            }
        return snapshot

    @api.model
    def _lf_migrate_1178(self, exclude_names=None):
        """Aplica pendientes (salvo exclusiones) y acumula OF en borrador por plato y día."""
        exclude_names = list(exclude_names or [])
        Reservation = self.env["lafija.reservation"].sudo()
        pending = Reservation._lf_migrate_pending_choices_1177(exclude_names=exclude_names)
        before = self._lf_mo_migration_snapshot()
        records = Reservation._lf_migrate_accumulate_mos_1177(exclude_names=exclude_names)
        after = self._lf_mo_migration_snapshot()
        created, updated = [], []
        for mo_id, data in after.items():
            if mo_id not in before:
                created.append(data)
            elif (before[mo_id]["qty"] != data["qty"]
                  or set(before[mo_id]["viandas"]) != set(data["viandas"])
                  or before[mo_id]["state"] != data["state"]):
                updated.append({**data, "qty_before": before[mo_id]["qty"]})
        excluded = Reservation.search([("name", "in", exclude_names)])
        summary = {
            "pending_applied": pending.mapped("name"),
            "pending_applied_ids": pending.ids,
            "excluded": exclude_names,
            "excluded_state": [
                {
                    "name": rec.name,
                    "state": rec.state,
                    "fulfillment_state": rec.fulfillment_state,
                    "current": rec.current_description or "",
                    "pending": rec.pending_description or "",
                    "mo_ids": rec.fulfillment_production_ids.ids,
                }
                for rec in excluded
            ],
            "vigente_processed": records.mapped("name"),
            "created": created,
            "updated": updated,
            "mos": list(after.values()),
        }
        self.env["ir.config_parameter"].sudo().set_param(
            "kai_viandas.migration_1178", repr(summary))
        return summary

    def _lf_set_production_qty(self, mo, qty):
        if mo.state != "draft" or mo.product_qty == qty:
            return
        mo.write({"product_qty": qty})

    def _lf_confirm_productions(self):
        """Confirmar una OF por plato y día, solo con las viandas de esta selección.

        Si ya hay un borrador de ese plato y día y se eligen todas sus viandas, se
        confirma. Si solo se elige una parte, se parte: las elegidas van a una OF
        confirmada y el resto queda en el borrador.
        """
        productions = self.env["mrp.production"].sudo()
        groups, skipped = self._lf_wanted_production_groups(self)
        for group in groups:
            records = group["records"]
            product = group["product"]
            company = group["company"]
            pool = records
            cut = records[:1].menu_id.cut_ids[:1]
            if cut.current_revision_id:
                pool = cut.current_revision_id.line_ids.reservation_id | records
            confirmed = records.fulfillment_production_ids.filtered(
                lambda mo, product=product: mo.state not in ("draft", "done", "cancel")
                and mo.product_id == product)
            if confirmed:
                productions |= confirmed[:1]
                continue
            drafts = pool.fulfillment_production_ids.filtered(
                lambda mo, product=product, company=company: mo.state == "draft"
                and mo.product_id == product and mo.company_id == company)
            mo = drafts[:1]
            extras = drafts - mo
            remaining = (mo.lf_reservation_ids - records) if mo else self.env["lafija.reservation"]
            remaining = remaining.filtered(
                lambda record: record.state == "active" and record.fulfillment_state == "to_prepare")
            if mo and remaining:
                self._lf_set_production_qty(mo, len(remaining))
                records.with_context(**operation_context()).write({
                    "fulfillment_production_ids": [(3, mo.id)],
                })
                self._lf_apply_production_refs(mo, remaining)
                selected = self._lf_make_production(dict(group, records=records, qty=len(records)), confirm=False)
                self._lf_apply_production_refs(selected, records)
                selected.action_confirm()
                productions |= selected
            elif mo:
                self._lf_set_production_qty(mo, len(records))
                missing = records.filtered(lambda record, mo=mo: mo not in record.fulfillment_production_ids)
                if missing:
                    missing.with_context(**operation_context()).write({
                        "fulfillment_production_ids": [(4, mo.id)],
                    })
                stale = mo.lf_reservation_ids - records
                if stale:
                    stale.with_context(**operation_context()).write({
                        "fulfillment_production_ids": [(3, mo.id)],
                    })
                self._lf_apply_production_refs(mo, records)
                mo.action_confirm()
                productions |= mo
            else:
                mo = self._lf_make_production(dict(group, records=records, qty=len(records)), confirm=False)
                self._lf_apply_production_refs(mo, records)
                mo.action_confirm()
                productions |= mo
            for extra in extras:
                extra.with_context(_lf_syncing_drafts=True).action_cancel()
                extra.lf_reservation_ids.with_context(**operation_context()).write({
                    "fulfillment_production_ids": [(3, extra.id)],
                })
        return productions, skipped

    def _lf_sync_from_productions(self):
        # Una OF en borrador no pasa la vianda a «En elaboración»; eso ocurre al confirmar (Elaborar o Manufactura).
        cuts = self.env["lafija.preparation.cut"]
        for record in self:
            if record.fulfillment_state == "delivered":
                continue
            mos = record.fulfillment_production_ids
            if not mos:
                continue
            confirmed_open = mos.filtered(lambda mo: mo.state not in ("draft", "done", "cancel"))
            done = mos.filtered(lambda mo: mo.state == "done")
            if confirmed_open:
                if record.fulfillment_state == "to_prepare":
                    record._lf_enter_progress()
                continue
            if done:
                if record.fulfillment_state != "prepared":
                    record._lf_set_state("prepared", _("Elaborada: la orden de fabricación quedó hecha."))
                continue
            if record.fulfillment_state != "to_prepare":
                record._lf_set_state(
                    "to_prepare",
                    _("La orden de fabricación se canceló. La vianda vuelve a «Por elaborar»."))
                if record.sudo()._current_preparation_line():
                    cuts |= record.menu_id.cut_ids[:1]
        if cuts and not self.env.context.get("_lf_syncing_drafts"):
            for cut in cuts:
                cut.with_context(_lf_syncing_drafts=True)._lf_sync_draft_productions()

    @api.model
    def _lf_merge_draft_productions_by_dish_day(self):
        """Unir OF en borrador del mismo plato, día y compañía de fabricación. No toca OF hechas."""
        drafts = self.env["mrp.production"].sudo().search([
            ("lf_reservation_ids", "!=", False),
            ("state", "=", "draft"),
        ])
        buckets = defaultdict(lambda: self.env["mrp.production"])
        leftovers = self.env["mrp.production"]
        for mo in drafts:
            dates = set(mo.lf_reservation_ids.mapped("date"))
            if len(dates) != 1:
                leftovers |= mo
                continue
            buckets[(dates.pop(), mo.product_id.id, mo.company_id.id)] |= mo
        keepers = self.env["mrp.production"]
        for _key, mos in buckets.items():
            keeper = mos.sorted("id")[:1]
            others = mos - keeper
            if others:
                for record in mos.lf_reservation_ids:
                    drop = record.fulfillment_production_ids & others
                    record.with_context(**operation_context()).write({
                        "fulfillment_production_ids": [(4, keeper.id)] + [(3, extra.id) for extra in drop],
                    })
                self._lf_set_production_qty(keeper, len(keeper.lf_reservation_ids))
                for extra in others:
                    extra.with_context(_lf_syncing_drafts=True).action_cancel()
                    leftover = extra.lf_reservation_ids
                    if leftover:
                        leftover.with_context(**operation_context()).write({
                            "fulfillment_production_ids": [(3, extra.id)],
                        })
            if keeper:
                self._lf_apply_production_refs(keeper, keeper.lf_reservation_ids)
                keepers |= keeper
        for mo in leftovers:
            self._lf_apply_production_refs(mo, mo.lf_reservation_ids)
        return keepers

    def _lf_daily_orders(self):
        return self.env["sale.order"].sudo().search([
            ("lf_preparation_date", "!=", False),
            ("state", "!=", "cancel"),
            ("lf_reservation_ids", "in", self.ids),
        ])

    def _lf_validate_delivery_pickings(self):
        notices = []
        for order in self._lf_daily_orders():
            notices.extend(order._lf_sync_outgoing_to_delivered())
        if any(not record._lf_daily_orders() for record in self):
            notices.append(_("Alguna vianda todavía no tiene un pedido diario; la entrega quedó registrada y se validará en el remito cuando exista el pedido."))
        return notices

    def action_open_production(self):
        check_operator(self.env)
        self.ensure_one()
        productions = self.sudo().fulfillment_production_ids
        if not productions:
            raise ValidationError(_("Esta vianda no tiene una orden de fabricación vinculada."))
        action = {"type": "ir.actions.act_window", "res_model": "mrp.production", "target": "current",
                  "name": _("Orden de fabricación")}
        if len(productions) == 1:
            action.update(res_id=productions.id, view_mode="form")
        else:
            action.update(domain=[("id", "in", productions.ids)], view_mode="list,form")
        return action

    def action_open_daily_order(self):
        check_operator(self.env)
        self.ensure_one()
        order = self.sudo().lf_daily_order_id
        if not order:
            raise ValidationError(_("Esta vianda no tiene un pedido de venta diario vinculado."))
        return {"type": "ir.actions.act_window", "res_model": "sale.order", "res_id": order.id,
                "view_mode": "form", "target": "current", "name": _("Pedido de venta")}


class PreparationLine(models.Model):
    _inherit = "lafija.preparation.line"

    fulfillment_state = fields.Selection(related="reservation_id.fulfillment_state", string="Estado de elaboración")
    fulfillment_label = fields.Char(related="reservation_id.fulfillment_label")
    fulfillment_production_ids = fields.Many2many(related="reservation_id.fulfillment_production_ids")
    reservation_name = fields.Char(related="reservation_id.name", string="Vianda")
    lf_daily_order_id = fields.Many2one(related="reservation_id.lf_daily_order_id", string="Pedido de venta")
    prepared_at = fields.Datetime(related="reservation_id.prepared_at")
    delivered_at = fields.Datetime(related="reservation_id.delivered_at")

    def action_elaborate(self):
        return self.reservation_id.action_elaborate()

    def action_mark_delivered(self):
        return self.reservation_id.action_mark_delivered()

    def action_unmark_delivered(self):
        return self.reservation_id.action_unmark_delivered()

    def action_open_production(self):
        self.ensure_one()
        return self.reservation_id.action_open_production()

    def action_open_daily_order(self):
        self.ensure_one()
        return self.reservation_id.action_open_daily_order()


class PreparationCut(models.Model):
    _inherit = "lafija.preparation.cut"

    current_line_ids = fields.One2many(related="current_revision_id.line_ids", string="Viandas de la lista vigente")
    to_prepare_count = fields.Integer("Por elaborar", compute="_compute_fulfillment_counts")
    in_progress_count = fields.Integer("En elaboración", compute="_compute_fulfillment_counts")
    prepared_count = fields.Integer("Elaboradas", compute="_compute_fulfillment_counts")
    delivered_count = fields.Integer("Entregadas", compute="_compute_fulfillment_counts")

    @api.depends("current_revision_id.line_ids.reservation_id.fulfillment_state")
    def _compute_fulfillment_counts(self):
        for cut in self:
            states = cut.current_revision_id.line_ids.reservation_id.mapped("fulfillment_state")
            cut.to_prepare_count = states.count("to_prepare")
            cut.in_progress_count = states.count("in_progress")
            cut.prepared_count = states.count("prepared")
            cut.delivered_count = states.count("delivered")

    def _new_revision(self, reason, actor):
        revision = super()._new_revision(reason, actor)
        self.invalidate_recordset(["current_revision_id", "current_line_ids"])
        self._lf_reset_changed_fulfillments()
        self._lf_sync_draft_productions(revision)
        return revision

    def _lf_reset_changed_fulfillments(self):
        for line in self.current_revision_id.line_ids:
            line.reservation_id._lf_reset_fulfillment_if_choice_changed()

    def _lf_sync_draft_productions(self, revision=None):
        """Crear o ajustar OF en borrador de las viandas por elaborar.

        Si la OF compartida del plato y el día sigue en borrador, se ajusta la
        cantidad y los vínculos. Si ya está confirmada, no se cambia su cantidad:
        las viandas nuevas de ese plato quedan en otra OF en borrador (el delta).
        Las viandas que salen o cambian se desvinculan; una confirmada con cantidad
        de más la ajusta el operador en Manufactura.
        """
        self.ensure_one()
        if self.env.context.get("_lf_syncing_drafts_inner"):
            return
        cut = self.with_context(_lf_syncing_drafts=True, _lf_syncing_drafts_inner=True)
        revision = revision or cut.current_revision_id
        if not revision:
            return
        lines = revision.line_ids
        current = lines.reservation_id.filtered(
            lambda record: record.state == "active" and record.fulfillment_state == "to_prepare"
            and record.current_product_id)
        groups, _skipped = current._lf_wanted_production_groups(current) if current else ([], [])
        used = cut.env["mrp.production"]
        previous = cut.revision_ids.line_ids.reservation_id
        pool = current | previous
        for group in groups:
            product = group["product"]
            company = group["company"]
            records = group["records"]
            confirmed = pool.fulfillment_production_ids.filtered(
                lambda mo, product=product, company=company: mo.state not in ("draft", "done", "cancel")
                and mo.product_id == product and mo.company_id == company)
            pending = records.filtered(
                lambda record, product=product: not record.fulfillment_production_ids.filtered(
                    lambda mo, product=product: mo.product_id == product and mo.state not in ("draft", "cancel")))
            if not pending:
                continue
            drafts = pool.fulfillment_production_ids.filtered(
                lambda mo, product=product, company=company: mo.state == "draft"
                and mo.product_id == product and mo.company_id == company)
            mo = drafts[:1]
            extras = drafts - mo
            if mo:
                cut.env["lafija.reservation"]._lf_set_production_qty(mo, len(pending))
                missing = pending.filtered(lambda record, mo=mo: mo not in record.fulfillment_production_ids)
                if missing:
                    missing.with_context(**operation_context()).write({
                        "fulfillment_production_ids": [(4, mo.id)],
                    })
                stale = mo.lf_reservation_ids - pending
                if stale:
                    stale.with_context(**operation_context()).write({
                        "fulfillment_production_ids": [(3, mo.id)],
                    })
            else:
                mo = pending._lf_make_production(dict(group, records=pending, qty=len(pending)), confirm=False)
            pending._lf_apply_production_refs(mo, mo.lf_reservation_ids)
            used |= mo
            for extra in extras:
                extra.with_context(_lf_syncing_drafts=True).action_cancel()
                extra.lf_reservation_ids.with_context(**operation_context()).write({
                    "fulfillment_production_ids": [(3, extra.id)],
                })
        leftover = pool.fulfillment_production_ids.filtered(
            lambda mo: mo.state == "draft" and mo not in used)
        for mo in leftover:
            linked = mo.lf_reservation_ids
            mo.with_context(_lf_syncing_drafts=True).action_cancel()
            linked.with_context(**operation_context()).write({
                "fulfillment_production_ids": [(3, mo.id)],
            })

    def _lf_sync_daily_orders(self, revision=None):
        self.ensure_one()
        lines = (revision or self.current_revision_id).line_ids
        for company in lines.customer_company_id:
            company_lines = lines.filtered(lambda line: line.customer_company_id == company)
            self._lf_upsert_daily_order(company, company_lines)

    def _lf_upsert_daily_order(self, partner, lines):
        seller = self.website_id.company_id or self.env.company
        reservations = lines.reservation_id
        wanted = Counter()
        for line in lines:
            if line.product_id:
                wanted[line.product_id] += 1
            if line.dessert_id:
                wanted[line.dessert_id] += 1
            if line.drink_id:
                wanted[line.drink_id] += 1
        return self.env["lafija.reservation"]._lf_upsert_company_daily_order(
            partner, self.date, seller, reservations, wanted, confirm=False,
            origin=_("Viandas %s · %s") % (self.date, partner.name),
        )


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Sin groups: action_confirm y otros flujos comerciales lo leen con cualquier usuario de ventas.
    lf_preparation_date = fields.Date("Día de la lista de preparación", copy=False, index=True)
    lf_production_ids = fields.Many2many(
        "mrp.production", compute="_compute_lf_production_buttons",
        string="Órdenes de fabricación", groups="kai_viandas.group_operator")
    lf_production_count = fields.Integer(compute="_compute_lf_production_buttons",
                                         groups="kai_viandas.group_operator")
    lf_reservation_count = fields.Integer(compute="_compute_lf_production_buttons",
                                          groups="kai_viandas.group_operator")

    @api.depends("lf_reservation_ids", "lf_reservation_ids.fulfillment_production_ids")
    def _compute_lf_production_buttons(self):
        for order in self:
            productions = order.sudo().lf_reservation_ids.fulfillment_production_ids
            order.lf_production_ids = productions
            order.lf_production_count = len(productions)
            order.lf_reservation_count = len(order.sudo().lf_reservation_ids)

    def action_lf_open_productions(self):
        check_operator(self.env)
        self.ensure_one()
        productions = self.sudo().lf_reservation_ids.fulfillment_production_ids
        if not productions:
            raise ValidationError(_("Este pedido no tiene órdenes de fabricación vinculadas."))
        action = {"type": "ir.actions.act_window", "res_model": "mrp.production", "target": "current",
                  "name": _("Órdenes de fabricación")}
        if len(productions) == 1:
            action.update(res_id=productions.id, view_mode="form")
        else:
            action.update(domain=[("id", "in", productions.ids)], view_mode="list,form")
        return action

    def action_lf_open_reservations(self):
        check_operator(self.env)
        self.ensure_one()
        reservations = self.sudo().lf_reservation_ids
        if not reservations:
            raise ValidationError(_("Este pedido no tiene viandas vinculadas."))
        action = {"type": "ir.actions.act_window", "res_model": "lafija.reservation", "target": "current",
                  "name": _("Viandas")}
        if len(reservations) == 1:
            action.update(res_id=reservations.id, view_mode="form")
        else:
            action.update(domain=[("id", "in", reservations.ids)], view_mode="list,form")
        return action

    def action_confirm(self):
        result = super().action_confirm()
        self.filtered(lambda order: order.sudo().lf_preparation_date)._lf_sync_outgoing_to_delivered()
        return result

    def _lf_sync_outgoing_to_delivered(self):
        notices = []
        for order in self:
            delivered = order.lf_reservation_ids.filtered(lambda record: record.fulfillment_state == "delivered")
            needed = Counter()
            for record in delivered:
                if record.current_product_id:
                    needed[record.current_product_id.id] += 1
                if record.current_dessert_id:
                    needed[record.current_dessert_id.id] += 1
                if record.current_drink_id:
                    needed[record.current_drink_id.id] += 1
            pickings = order.picking_ids.filtered(
                lambda picking: picking.picking_type_code == "outgoing" and picking.state != "cancel")
            if not pickings:
                if needed:
                    notices.append(_("El pedido %s no tiene remito de salida (productos no almacenables o sin ruta). La entrega quedó registrada en la vianda.") % (order.name or ""))
                continue
            already = Counter()
            for move in pickings.filtered(lambda picking: picking.state == "done").mapped("move_ids"):
                already[move.product_id.id] += move.product_uom_qty
            pending = pickings.filtered(lambda picking: picking.state not in ("done", "cancel"))
            to_validate = self.env["stock.picking"]
            for product_id, qty in needed.items():
                remaining = max(0, qty - already[product_id])
                for move in pending.mapped("move_ids").filtered(
                        lambda move: move.product_id.id == product_id and move.state not in ("done", "cancel")):
                    if remaining <= 0:
                        break
                    current = _move_qty(move) or 0
                    demand_left = max(0, move.product_uom_qty - current)
                    take = min(demand_left, remaining)
                    if take:
                        _set_move_qty(move, current + take)
                        remaining -= take
                        to_validate |= move.picking_id
                if remaining > 0:
                    notices.append(_("No alcanzó la cantidad del remito de %s para entregar todo lo marcado en %s.") % (order.name, self.env["product.product"].browse(product_id).display_name))
            for picking in to_validate:
                notices.extend(order._lf_validate_picking(picking))
        return notices

    def _lf_validate_picking(self, picking):
        if picking.state in ("done", "cancel"):
            return []
        try:
            action = picking.with_context(skip_sms=True, skip_backorder=False).button_validate()
        except Exception as exc:
            return [_("No se pudo validar el remito %s: %s") % (picking.name, exc)]
        if not isinstance(action, dict):
            return []
        model = action.get("res_model")
        context = action.get("context") or {}
        if model in ("stock.immediate.transfer", "stock.backorder.confirmation", "stock.immediate.transfer,stock.backorder.confirmation"):
            wizard = self.env[model].with_context(**context).sudo().create({})
            if hasattr(wizard, "process"):
                wizard.process()
            elif hasattr(wizard, "button_validate"):
                wizard.button_validate()
        return []


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    lf_reservation_ref = fields.Char(
        "Viandas", compute="_compute_lf_reservation_ref", groups="kai_viandas.group_operator")

    @api.depends(
        "order_id.lf_reservation_ids", "order_id.lf_reservation_ids.name",
        "order_id.lf_reservation_ids.current_product_id",
        "order_id.lf_reservation_ids.current_dessert_id",
        "order_id.lf_reservation_ids.current_drink_id",
        "product_id", "order_id.lf_preparation_date")
    def _compute_lf_reservation_ref(self):
        for line in self:
            reservations = line.order_id.sudo().lf_reservation_ids.filtered(
                lambda record: line.product_id
                and line.product_id in (record.current_product_id | record.current_dessert_id | record.current_drink_id))
            line.lf_reservation_ref = ", ".join(reservations.sorted("name").mapped("name")) or False


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    lf_meal_date = fields.Date(
        "Día del menú", copy=False, index=True, groups="kai_viandas.group_operator")
    lf_reservation_ids = fields.Many2many(
        "lafija.reservation", "lafija_reservation_mrp_rel", "production_id", "reservation_id",
        string="Viandas", copy=False, groups="kai_viandas.group_operator")
    lf_sale_order_id = fields.Many2one(
        "sale.order", "Pedido de venta", copy=False, index=True,
        groups="kai_viandas.group_operator")
    lf_sale_order_ids = fields.Many2many(
        "sale.order", compute="_compute_lf_sale_orders",
        string="Pedidos de venta", groups="kai_viandas.group_operator")
    lf_sale_order_count = fields.Integer(
        compute="_compute_lf_sale_orders", groups="kai_viandas.group_operator")

    @api.depends(
        "lf_reservation_ids", "lf_reservation_ids.lf_daily_order_id",
        "lf_reservation_ids.lf_sale_order_ids", "lf_sale_order_id")
    def _compute_lf_sale_orders(self):
        for mo in self:
            reservations = mo.sudo().lf_reservation_ids
            orders = reservations.lf_daily_order_id | reservations.lf_sale_order_ids.filtered("lf_preparation_date")
            if mo.lf_sale_order_id:
                orders |= mo.lf_sale_order_id
            mo.lf_sale_order_ids = orders
            mo.lf_sale_order_count = len(orders)

    def action_lf_open_sale_orders(self):
        check_operator(self.env)
        self.ensure_one()
        orders = self.sudo().lf_sale_order_ids
        if not orders:
            raise ValidationError(_("Esta orden de fabricación no tiene un pedido de venta vinculado."))
        action = {"type": "ir.actions.act_window", "res_model": "sale.order", "target": "current",
                  "name": _("Pedidos de venta")}
        if len(orders) == 1:
            action.update(res_id=orders.id, view_mode="form")
        else:
            action.update(domain=[("id", "in", orders.ids)], view_mode="list,form")
        return action

    def action_lf_open_sale_order(self):
        return self.action_lf_open_sale_orders()

    def action_lf_open_reservations(self):
        check_operator(self.env)
        self.ensure_one()
        reservations = self.sudo().lf_reservation_ids
        if not reservations:
            raise ValidationError(_("Esta orden de fabricación no tiene viandas vinculadas."))
        action = {"type": "ir.actions.act_window", "res_model": "lafija.reservation", "target": "current",
                  "name": _("Viandas")}
        if len(reservations) == 1:
            action.update(res_id=reservations.id, view_mode="form")
        else:
            action.update(domain=[("id", "in", reservations.ids)], view_mode="list,form")
        return action

    def write(self, values):
        result = super().write(values)
        if "state" in values:
            self.sudo().lf_reservation_ids._lf_sync_from_productions()
        return result

    def action_cancel(self):
        result = super().action_cancel()
        self.sudo().lf_reservation_ids._lf_sync_from_productions()
        return result

    def button_mark_done(self):
        result = super().button_mark_done()
        self.sudo().lf_reservation_ids._lf_sync_from_productions()
        return result
