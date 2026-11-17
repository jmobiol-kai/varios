from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from ..models.identity import check_operator
from ..models.reservation import choice_label, SelectionConflict
from ..models.time_utils import business_today, day_label


def _week_start(day):
    return day - timedelta(days=day.weekday())


class MenuDay(models.Model):
    _inherit = "lafija.menu.day"

    @api.depends("name", "date", "website_id.name")
    def _compute_display_name(self):
        if not self.env.context.get("lf_day_label"):
            return super()._compute_display_name()
        for menu in self:
            menu.display_name = day_label(menu.date) if menu.date else (menu.name or "")


class EmployeeOrder(models.TransientModel):
    _name = "lafija.employee.order"
    _description = "Crear pedidos de empleados"

    allowed_company_ids = fields.Many2many(
        "res.partner", compute="_compute_allowed_company_ids",
        string="Empresas con empleados activos")
    customer_company_id = fields.Many2one(
        "res.partner", "Empresa cliente", required=True,
        domain="[('id', 'in', allowed_company_ids)]", ondelete="cascade")
    employee_id = fields.Many2one(
        "res.partner", "Empleado", ondelete="cascade",
        domain="[('active', '=', True), ('lf_corporate_account', '=', True), "
               "('lf_enabled', '=', True), ('is_company', '=', False), "
               "('lf_customer_company_id', '=', customer_company_id)]")
    website_id = fields.Many2one("website", "Sitio corporativo", related="employee_id.website_id")
    week_start = fields.Date("Semana")
    week_label = fields.Char("Semana visible", compute="_compute_week_label")
    line_ids = fields.One2many("lafija.employee.order.line", "wizard_id", "Días de la semana")
    notice = fields.Text("Aviso", readonly=True)
    can_add_line = fields.Boolean("Se puede agregar un día", compute="_compute_add_line_state")
    focus_date = fields.Date("Día a enfocar")


    @api.model
    def _active_employee_domain(self):
        return [
            ("active", "=", True),
            ("is_company", "=", False),
            ("lf_corporate_account", "=", True),
            ("lf_enabled", "=", True),
            ("lf_customer_company_id", "!=", False),
        ]

    @api.model
    def _companies_with_active_employees(self):
        employees = self.env["res.partner"].search(self._active_employee_domain())
        return employees.mapped("lf_customer_company_id")

    @api.depends()
    def _compute_allowed_company_ids(self):
        companies = self._companies_with_active_employees()
        for wizard in self:
            wizard.allowed_company_ids = companies

    @api.constrains("customer_company_id")
    def _check_company_has_active_employees(self):
        allowed = self._companies_with_active_employees()
        for wizard in self:
            if wizard.customer_company_id and wizard.customer_company_id not in allowed:
                raise ValidationError(
                    _("Esa empresa no tiene empleados dados de alta en Viandas.")
                )

    @api.depends("week_start")
    def _compute_week_label(self):
        for wizard in self:
            start = wizard.week_start
            wizard.week_label = (f"{start:%d/%m} al {start + timedelta(days=6):%d/%m/%Y}" if start else "")

    @api.depends("employee_id", "website_id", "week_start", "line_ids.menu_id")
    def _compute_add_line_state(self):
        Menu = self.env["lafija.menu.day"].sudo()
        for wizard in self:
            if not wizard.employee_id or not wizard.week_start or not wizard.website_id:
                wizard.can_add_line = False
                continue
            menus = Menu.search([
                ("website_id", "=", wizard.website_id.id),
                ("published", "=", True),
                ("date", ">=", wizard.week_start),
                ("date", "<", wizard.week_start + timedelta(days=7)),
            ])
            unused = menus - wizard.line_ids.mapped("menu_id")
            wizard.can_add_line = bool(unused)

    def _check_employee_company(self):
        for wizard in self:
            if (wizard.employee_id and wizard.customer_company_id
                    and wizard.employee_id.lf_customer_company_id != wizard.customer_company_id):
                raise ValidationError(_("El empleado debe pertenecer a la empresa cliente elegida."))

    def _employee_user(self):
        self.ensure_one()
        self._check_employee_company()
        users = self.employee_id.sudo().user_ids
        if not self.employee_id or len(users) != 1:
            raise ValidationError(_("Elegí un empleado con cuenta corporativa habilitada."))
        return users

    def _default_week_start(self, website):
        today = business_today(self.env)
        menu = self.env["lafija.menu.day"].sudo().search([
            ("website_id", "=", website.id), ("published", "=", True), ("date", ">=", today),
        ], order="date", limit=1)
        return _week_start(menu.date or today)

    def _week_from_context(self):
        ctx = self.env.context
        if ctx.get("default_week_start"):
            return fields.Date.to_date(ctx["default_week_start"])
        if ctx.get("default_focus_date"):
            return _week_start(fields.Date.to_date(ctx["default_focus_date"]))
        if ctx.get("default_date"):
            return _week_start(fields.Date.to_date(ctx["default_date"]))
        return False

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        week = self._week_from_context()
        focus = self.env.context.get("default_focus_date") or self.env.context.get("default_date")
        if week and "week_start" in fields_list and not values.get("week_start"):
            values["week_start"] = week
        if focus and "focus_date" in fields_list and not values.get("focus_date"):
            values["focus_date"] = fields.Date.to_date(focus)
        return values

    def _line_values_for_week(self, employee, week_start):
        website = employee.website_id
        menus = self.env["lafija.menu.day"].sudo().search([
            ("website_id", "=", website.id), ("published", "=", True),
            ("date", ">=", week_start), ("date", "<", week_start + timedelta(days=7)),
        ], order="date, id")
        reservations = self.env["lafija.reservation"].sudo().search([
            ("employee_partner_id", "=", employee.id),
            ("date", "in", menus.mapped("date")),
        ])
        by_date = {record.date: record for record in reservations}
        today = business_today(self.env)
        values = []
        for menu in menus:
            record = by_date.get(menu.date)
            current = record.current_product_id if record and record.state == "active" else self.env["product.product"]
            has_pending = bool(record and (record.pending_product_id or record.pending_dessert_id or record.pending_drink_id))
            selected = (record.pending_product_id or current) if record else self.env["product.product"]
            selected_dessert = (record.pending_dessert_id if has_pending else record.current_dessert_id) if record and record.state == "active" else self.env["product.product"]
            selected_drink = (record.pending_drink_id if has_pending else record.current_drink_id) if record and record.state == "active" else self.env["product.product"]
            values.append({
                "menu_id": menu.id,
                "product_id": selected.id,
                "dessert_id": selected_dessert.id,
                "drink_id": selected_drink.id,
            })
        return values

    def _sync_lines(self):
        for wizard in self:
            if not wizard.employee_id or not wizard.week_start:
                wizard.line_ids.unlink()
                wizard.notice = False
                continue
            values = wizard._line_values_for_week(wizard.employee_id, wizard.week_start)
            wizard.line_ids.unlink()
            if values:
                wizard.with_context(_lf_skip_line_sync=True).write({
                    "line_ids": [(0, 0, line) for line in values], "notice": False,
                })
            else:
                wizard.with_context(_lf_skip_line_sync=True).write({
                    "notice": _("No hay menús publicados en esta semana para el sitio de este empleado."),
                })

    def _apply_reservations(self, require_selection=True):
        self.ensure_one()
        if not self.employee_id:
            if require_selection:
                raise ValidationError(_("Elegí la empresa cliente y el empleado."))
            return self.env["lafija.reservation"]
        if self.employee_id.lf_customer_company_id != self.customer_company_id:
            raise ValidationError(_("El empleado debe pertenecer a la empresa cliente elegida."))
        subject = self._employee_user()
        website = self.employee_id.website_id
        if not website.lf_corporate_site:
            raise ValidationError(_("El empleado debe pertenecer a un sitio corporativo."))
        selections = []
        withdraw_current = {}
        today = business_today(self.env)
        for line in self.line_ids:
            line._check_choice()
            if not line.menu_id or line.past or not line.date or line.date < today or not line.product_id:
                continue
            current = line.current_product_id
            selections.append((line.menu_id.id, line.product_id.id, line.dessert_id.id or 0, line.drink_id.id or 0))
            if line.has_pending and line.reservation_id and line.product_id.id == (current.id or 0):
                submitted = (line.product_id.id, line.dessert_id.id or 0, line.drink_id.id or 0)
                current_triple = (current.id, line.current_dessert_id.id or 0, line.current_drink_id.id or 0)
                if submitted == current_triple:
                    withdraw_current[line.menu_id.id] = submitted
        if not selections:
            if require_selection:
                raise ValidationError(_("Elegí al menos un plato de un día vigente. "
                                        "Si no hay plato, una reserva ya cargada de ese día no se modifica."))
            return self.env["lafija.reservation"]
        service = self.env["lafija.reservation"]
        try:
            before = service._last_events_for_submission(website, selections, employee=subject)
            records = service._submit_selections(
                website, selections, withdraw_current=withdraw_current, employee=subject)
        except SelectionConflict:
            raise ValidationError(_("La reserva cambió mientras la cargabas. Revisá la semana y volvé a confirmar.")) from None
        changed = records.filtered(lambda r: r.sudo().event_ids[-1:].id != before.get(r.id))
        for record in changed:
            record.message_post(body=_("Cargado por operador."), author_id=self.env.user.partner_id.id,
                                subtype_xmlid="mail.mt_note")
        return changed

    def _feedback_message(self, changed):
        if not changed:
            return _("No hiciste cambios. Las reservas del empleado se mantienen.")
        details = []
        for record in changed:
            last = record.sudo().event_ids[-1:]
            label = choice_label(record.current_description, record.current_dessert_description,
                                 record.current_drink_description)
            if last.kind == "withdrawal":
                details.append(_("%s: anulaste el cambio pedido. Sigue vigente %s.") % (day_label(record.date), label))
            elif record.pending:
                details.append(_("%s: cambio recibido para revisión; todavía no se aplicó.") % day_label(record.date))
            else:
                details.append(_("%s: elección guardada · %s.") % (day_label(record.date), label))
        return _("Cargado por operador.\n%s") % "\n".join(details)

    def web_save(self, vals, specification, next_id=None):
        # El Guardar del encabezado solo hacía web_save y no confirmaba, por eso
        # no se creaba la reserva y Día/Ya reservado quedaban vacíos (readonly).
        if self:
            self.write(vals)
            records = self
        else:
            records = self.create(vals)
        if next_id:
            records = records.browse(next_id)
        else:
            records = records.exists()
        for wizard in records:
            if wizard.employee_id:
                wizard._apply_reservations(require_selection=False)
                wizard._sync_lines()
        return records.with_context(bin_size=True).web_read(specification)

    @api.model_create_multi
    def create(self, values_list):
        check_operator(self.env)
        records = super().create(values_list)
        records._check_employee_company()
        for wizard, values in zip(records, values_list):
            if wizard.employee_id and not wizard.week_start:
                wizard.with_context(_lf_skip_line_sync=True).write({
                    "week_start": wizard._default_week_start(wizard.employee_id.website_id),
                })
            # El formulario envía las líneas ya elegidas. Regenerarlas aquí
            # (todavía no hay reserva) perdería el plato, el postre y la bebida.
            if not values.get("line_ids"):
                wizard._sync_lines()
        return records

    def write(self, values):
        result = super().write(values)
        if set(values) & {"employee_id", "customer_company_id", "week_start"} and not self.env.context.get("_lf_skip_line_sync"):
            self._sync_lines()
        return result

    @api.onchange("customer_company_id")
    def _onchange_company(self):
        if self.employee_id and self.employee_id.lf_customer_company_id != self.customer_company_id:
            self.employee_id = False
            if not self.focus_date:
                self.week_start = False
                self.line_ids = False
                self.notice = False

    @api.onchange("employee_id")
    def _onchange_employee(self):
        if not self.employee_id:
            if not self.focus_date:
                self.week_start = False
            self.line_ids = False
            self.notice = False
            return
        if self.employee_id.lf_customer_company_id != self.customer_company_id:
            raise ValidationError(_("El empleado debe pertenecer a la empresa cliente elegida."))
        self.week_start = (
            self.week_start
            or (self.focus_date and _week_start(self.focus_date))
            or self._week_from_context()
            or self._default_week_start(self.employee_id.website_id)
        )
        self.line_ids = [(5, 0, 0)] + [(0, 0, values) for values in self._line_values_for_week(self.employee_id, self.week_start)]
        self.notice = (False if self.line_ids
                       else _("No hay menús publicados en esta semana para el sitio de este empleado."))

    def _reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Crear pedidos de empleados"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "views": [(self.env.ref("kai_viandas.employee_order_form").id, "form")],
        }

    def action_previous_week(self):
        check_operator(self.env)
        self.ensure_one()
        if not self.week_start:
            raise ValidationError(_("Elegí un empleado para ver la semana."))
        self.week_start = self.week_start - timedelta(days=7)
        return self._reopen()

    def action_next_week(self):
        check_operator(self.env)
        self.ensure_one()
        if not self.week_start:
            raise ValidationError(_("Elegí un empleado para ver la semana."))
        self.week_start = self.week_start + timedelta(days=7)
        return self._reopen()

    def action_confirm(self):
        check_operator(self.env)
        self.ensure_one()
        changed = self._apply_reservations(require_selection=True)
        message = self._feedback_message(changed)
        self._sync_lines()
        return {"type": "ir.actions.client", "tag": "lf_operation_feedback", "params": {
            "message": message,
            "next": self._reopen(),
        }}


class EmployeeOrderLine(models.TransientModel):
    _name = "lafija.employee.order.line"
    _description = "Día del pedido cargado por el operador"
    _order = "date, id"

    wizard_id = fields.Many2one("lafija.employee.order", required=True, ondelete="cascade")
    menu_id = fields.Many2one(
        "lafija.menu.day", "Día", ondelete="cascade",
        domain="[('id', 'in', available_menu_ids)]",
        context="{'lf_day_label': 1}")
    date = fields.Date("Fecha", compute="_compute_from_menu", store=True)
    date_label = fields.Char("Día", compute="_compute_from_menu", store=True)
    is_focus = fields.Boolean("Día de origen", compute="_compute_is_focus")

    @api.depends("date", "wizard_id.focus_date")
    def _compute_is_focus(self):
        for line in self:
            line.is_focus = bool(line.wizard_id.focus_date and line.date == line.wizard_id.focus_date)
    past = fields.Boolean("Día pasado", compute="_compute_from_menu", store=True)
    after_cut = fields.Boolean("Después de tomar la lista", compute="_compute_from_menu", store=True)
    available_menu_ids = fields.Many2many("lafija.menu.day", compute="_compute_available_menu_ids")
    reservation_id = fields.Many2one("lafija.reservation", compute="_compute_current_display")
    product_id = fields.Many2one("product.product", "Plato", domain="[('id', 'in', plate_option_ids)]")
    dessert_id = fields.Many2one("product.product", "Postre", domain="[('id', 'in', dessert_option_ids)]")
    drink_id = fields.Many2one("product.product", "Bebida", domain="[('id', 'in', drink_option_ids)]")
    plate_option_ids = fields.Many2many("product.product", compute="_compute_option_ids")
    dessert_option_ids = fields.Many2many("product.product", compute="_compute_option_ids")
    drink_option_ids = fields.Many2many("product.product", compute="_compute_option_ids")
    current_product_id = fields.Many2one("product.product", compute="_compute_current_display")
    current_dessert_id = fields.Many2one("product.product", compute="_compute_current_display")
    current_drink_id = fields.Many2one("product.product", compute="_compute_current_display")
    has_pending = fields.Boolean(compute="_compute_current_display")
    current_label = fields.Char("Ya reservado", compute="_compute_current_display")

    @api.depends("menu_id", "menu_id.date", "menu_id.cut_ids")
    def _compute_from_menu(self):
        today = business_today(self.env)
        for line in self:
            menu = line.menu_id
            line.date = menu.date
            line.date_label = day_label(menu.date) if menu.date else ""
            line.past = bool(menu.date and menu.date < today)
            line.after_cut = bool(menu.cut_ids)

    @api.depends("wizard_id.website_id", "wizard_id.week_start", "wizard_id.line_ids.menu_id", "menu_id")
    def _compute_available_menu_ids(self):
        Menu = self.env["lafija.menu.day"].sudo()
        for line in self:
            wizard = line.wizard_id
            if not wizard.week_start or not wizard.website_id:
                line.available_menu_ids = line.menu_id
                continue
            used = (wizard.line_ids - line).mapped("menu_id").ids
            menus = Menu.search([
                ("website_id", "=", wizard.website_id.id),
                ("published", "=", True),
                ("date", ">=", wizard.week_start),
                ("date", "<", wizard.week_start + timedelta(days=7)),
                ("id", "not in", used),
            ])
            line.available_menu_ids = menus | line.menu_id

    @api.depends("menu_id")
    def _compute_option_ids(self):
        for line in self:
            menu = line.menu_id
            line.plate_option_ids = menu.product_ids
            line.dessert_option_ids = menu.dessert_ids
            line.drink_option_ids = menu.drink_ids

    @api.depends(
        "menu_id", "wizard_id.employee_id",
        "reservation_id.current_description", "reservation_id.current_dessert_description",
        "reservation_id.current_drink_description", "reservation_id.pending_description",
        "reservation_id.pending_dessert_description", "reservation_id.pending_drink_description",
        "reservation_id.current_product_id", "reservation_id.current_dessert_id",
        "reservation_id.current_drink_id", "reservation_id.pending_product_id",
        "reservation_id.pending_dessert_id", "reservation_id.pending_drink_id",
        "reservation_id.state",
    )
    def _compute_current_display(self):
        Reservation = self.env["lafija.reservation"].sudo()
        for line in self:
            record = Reservation.browse()
            if line.menu_id and line.wizard_id.employee_id:
                record = Reservation.search([
                    ("employee_partner_id", "=", line.wizard_id.employee_id.id),
                    ("menu_id", "=", line.menu_id.id),
                ], limit=1)
            line.reservation_id = record
            active = record if record and record.state == "active" else Reservation
            has_pending = bool(active and (active.pending_product_id or active.pending_dessert_id or active.pending_drink_id))
            line.has_pending = has_pending
            line.current_product_id = active.current_product_id
            line.current_dessert_id = active.current_dessert_id
            line.current_drink_id = active.current_drink_id
            if active:
                current_label = choice_label(
                    active.current_description, active.current_dessert_description, active.current_drink_description)
                if has_pending:
                    current_label = (
                        f"{current_label} · pedido pendiente: "
                        f"{choice_label(active.pending_description, active.pending_dessert_description, active.pending_drink_description)}"
                    )
                line.current_label = current_label
            else:
                line.current_label = ""

    @api.onchange("menu_id")
    def _onchange_menu(self):
        if not self.menu_id:
            self.product_id = False
            self.dessert_id = False
            self.drink_id = False
            return
        record = self.env["lafija.reservation"].sudo().search([
            ("employee_partner_id", "=", self.wizard_id.employee_id.id),
            ("menu_id", "=", self.menu_id.id),
            ("state", "=", "active"),
        ], limit=1) if self.wizard_id.employee_id else self.env["lafija.reservation"]
        if record:
            has_pending = bool(record.pending_product_id or record.pending_dessert_id or record.pending_drink_id)
            self.product_id = record.pending_product_id or record.current_product_id
            self.dessert_id = record.pending_dessert_id if has_pending else record.current_dessert_id
            self.drink_id = record.pending_drink_id if has_pending else record.current_drink_id
            return
        if self.product_id and self.product_id not in self.menu_id.product_ids:
            self.product_id = False
        if self.dessert_id and self.dessert_id not in self.menu_id.dessert_ids:
            self.dessert_id = False
        if self.drink_id and self.drink_id not in self.menu_id.drink_ids:
            self.drink_id = False

    @api.onchange("product_id")
    def _onchange_product(self):
        if not self.product_id:
            self.dessert_id = False
            self.drink_id = False

    def _check_choice(self):
        self.ensure_one()
        if not self.menu_id:
            if self.product_id or self.dessert_id or self.drink_id:
                raise ValidationError(_("Elegí el día de la línea nueva."))
            return
        if not self.product_id and (self.dessert_id or self.drink_id):
            raise ValidationError(_("El postre y la bebida solo se pueden pedir si hay un plato el %s.")
                                  % (self.date_label or self.date))
        if self.dessert_id and self.dessert_id not in self.menu_id.dessert_ids:
            raise ValidationError(_("El postre debe pertenecer al menú publicado de ese día."))
        if self.drink_id and self.drink_id not in self.menu_id.drink_ids:
            raise ValidationError(_("La bebida debe pertenecer al menú publicado de ese día."))
        if self.product_id and self.product_id not in self.menu_id.product_ids:
            raise ValidationError(_("El plato debe pertenecer al menú publicado de ese día."))
