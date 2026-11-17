from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from .identity import check_operator
from .time_utils import business_today
from . import order_windows


DAYS_PER_WEEK = 7
_OPERATION = object()
PLATE_CATEGORY_NAME = "Viandas"
DESSERT_CATEGORY_NAME = "Postre Vianda"
DRINK_CATEGORY_NAME = "Bebida Vianda"


def operation_context():
    return {"_lf_reservation_operation": _OPERATION, "mail_create_nosubscribe": True}


def choice_label(plate, dessert=None, drink=None):
    """Texto visible de una elección: plato, y postre/bebida si hay."""
    return " · ".join(part for part in (plate, dessert, drink) if part)


def normalize_selection(item):
    """Acepta (menú, plato) o (menú, plato, postre, bebida). 0 = sin acompañamiento."""
    if not item or len(item) not in (2, 4):
        raise ValidationError("Elegí al menos una opción, sin repetir días y hasta una semana por envío.")
    menu_id, product_id = item[0], item[1]
    dessert_id = item[2] if len(item) == 4 else 0
    drink_id = item[3] if len(item) == 4 else 0
    return menu_id, product_id, dessert_id or 0, drink_id or 0


def check_operation(env):
    if env.context.get("_lf_reservation_operation") is _OPERATION:
        return
    if env.su and not env.user._lf_is_corporate_subject():
        return
    raise AccessError(env._("Usá las acciones de reserva o corrección para conservar el historial."))


class SelectionConflict(ValidationError):
    """Conflicto identificado, distinto de una selección inválida o no autorizada."""
    def __init__(self, menu_id):
        self.menu_id = menu_id
        super().__init__("La vianda vigente cambió mientras elegías. Revisá el día y volvé a guardar.")


class PastDayConflict(SelectionConflict):
    """El límite calendario se comprueba bajo la misma exclusión que el corte."""
    def __init__(self, menu_id):
        self.menu_id = menu_id
        ValidationError.__init__(self, "Día pasado · para corregir, escribile a La Fija.")


class OrderWindowClosed(ValidationError):
    """La ventana de pedido del empleado está cerrada para ese día."""


class MenuDay(models.Model):
    _name = "lafija.menu.day"
    _description = "Menú del día"
    _inherit = ["mail.thread"]
    _order = "date, id"

    name = fields.Char("Menú del día", compute="_compute_name", store=True)
    date = fields.Date("Fecha", required=True, index=True, tracking=True)
    website_id = fields.Many2one("website", "Sitio corporativo", required=True, ondelete="restrict", tracking=True)
    product_ids = fields.Many2many(
        "product.product", string="Platos", domain=lambda self: self._option_domain(PLATE_CATEGORY_NAME))
    dessert_ids = fields.Many2many(
        "product.product", "lafija_menu_day_dessert_rel", "menu_id", "product_id",
        string="Postres", domain=lambda self: self._option_domain(DESSERT_CATEGORY_NAME))
    drink_ids = fields.Many2many(
        "product.product", "lafija_menu_day_drink_rel", "menu_id", "product_id",
        string="Bebidas", domain=lambda self: self._option_domain(DRINK_CATEGORY_NAME))
    published = fields.Boolean("Publicado", tracking=True)
    revision = fields.Integer("Revisión", default=0, readonly=True)
    option_snapshot = fields.Json("Opciones publicadas", readonly=True)
    dessert_snapshot = fields.Json("Postres publicados", readonly=True)
    drink_snapshot = fields.Json("Bebidas publicadas", readonly=True)
    revision_ids = fields.One2many("lafija.menu.revision", "menu_id", "Historia de la oferta", readonly=True)
    reservation_ids = fields.One2many("lafija.reservation", "menu_id", "Reservas", readonly=True)
    operation_version = fields.Integer(default=0, readonly=True)

    _date_site_unique = models.Constraint("unique(date, website_id)", "Ya existe un menú para ese sitio y fecha.")

    @api.depends("date", "website_id.name")
    def _compute_name(self):
        for menu in self:
            menu.name = (f"{menu.date} · {menu.website_id.name}"
                         if menu.date and menu.website_id else "Nuevo menú del día")

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if set(values) & {"revision", "option_snapshot", "dessert_snapshot", "drink_snapshot", "operation_version"}:
                check_operation(self.env)
        records = super().create(values_list)
        records._record_revision()
        return records

    def write(self, values):
        if set(values) & {"revision", "option_snapshot", "dessert_snapshot", "drink_snapshot", "operation_version"}:
            check_operation(self.env)
        changed = bool(set(values) & {"date", "website_id", "product_ids", "dessert_ids", "drink_ids", "published"})
        if changed:
            self._lock_for_operation()
        result = super().write(values)
        if changed:
            self._record_revision()
        return result

    @api.model
    def _option_category(self, name):
        return self.env["product.category"].sudo().search([("complete_name", "=", name)], limit=1)

    @api.model
    def _option_domain(self, name):
        domain = [("sale_ok", "=", True)]
        category = self._option_category(name)
        if category:
            domain.append(("categ_id", "child_of", category.id))
        return domain

    def _products_in_category(self, products, category):
        if not category:
            return products.browse()
        prefix = category.parent_path or f"{category.id}/"
        return products.filtered(lambda p: (p.categ_id.parent_path or "").startswith(prefix))

    @api.constrains("website_id", "published", "product_ids", "dessert_ids", "drink_ids")
    def _check_menu(self):
        plate_categ = self._option_category(PLATE_CATEGORY_NAME)
        dessert_categ = self._option_category(DESSERT_CATEGORY_NAME)
        drink_categ = self._option_category(DRINK_CATEGORY_NAME)
        for menu in self:
            if not menu.website_id.lf_corporate_site:
                raise ValidationError(_("El menú debe pertenecer a un sitio corporativo."))
            if menu.published and (not menu.product_ids or any(not p.active or not p.sale_ok for p in menu.product_ids)):
                raise ValidationError(_("Para publicar, elegí al menos un plato activo y vendible."))
            sides = menu.dessert_ids | menu.drink_ids
            if menu.published and any(not p.active or not p.sale_ok for p in sides):
                raise ValidationError(_("Los postres y las bebidas del menú deben estar activos y vendibles."))
            if self.env.context.get("_lf_skip_category_check"):
                continue
            if plate_categ and (menu.product_ids - menu._products_in_category(menu.product_ids, plate_categ)):
                raise ValidationError(_("Los platos deben pertenecer a la categoría Viandas."))
            if dessert_categ and (menu.dessert_ids - menu._products_in_category(menu.dessert_ids, dessert_categ)):
                raise ValidationError(_("Los postres deben pertenecer a la categoría Postre Vianda."))
            if drink_categ and (menu.drink_ids - menu._products_in_category(menu.drink_ids, drink_categ)):
                raise ValidationError(_("Las bebidas deben pertenecer a la categoría Bebida Vianda."))

    def _option_values(self, products):
        return {
            str(product.id): {
                "name": product.display_name,
                "description": product.description_sale or product.display_name,
            } for product in products
        }

    def _record_revision(self):
        for menu in self:
            snapshot = menu._option_values(menu.product_ids)
            desserts = menu._option_values(menu.dessert_ids)
            drinks = menu._option_values(menu.drink_ids)
            revision = menu.revision + 1
            super(MenuDay, menu).write({
                "revision": revision, "option_snapshot": snapshot,
                "dessert_snapshot": desserts, "drink_snapshot": drinks,
            })
            self.env["lafija.menu.revision"].sudo().with_context(**operation_context()).create({
                "menu_id": menu.id, "number": revision, "date": menu.date,
                "website_id": menu.website_id.id, "published": menu.published,
                "options": snapshot, "desserts": desserts, "drinks": drinks,
                "actor_id": self.env.uid,
            })

    def _lock_for_operation(self):
        # Odoo usa REPEATABLE READ: tocar la fila provoca reintento de una petición
        # con snapshot obsoleto; un SELECT FOR UPDATE solo no refresca ese snapshot.
        self.flush_recordset()
        for menu in self.sorted("id"):
            self.env.cr.execute(
                "UPDATE lafija_menu_day SET operation_version = operation_version + 1 WHERE id = %s",
                [menu.id],
            )
        self.invalidate_recordset()

    def _reference_datetime(self):
        self.ensure_one()
        # Corte diario (por defecto 10:30) en la zona del usuario administrador de Odoo.
        return order_windows.daily_cutoff_datetime(self.env, self.date)

    def _weekly_close_datetime(self):
        self.ensure_one()
        week_start = self.date - timedelta(days=self.date.weekday())
        return order_windows.weekly_close_datetime(self.env, week_start)

    def _employee_window_state(self, moment=None):
        self.ensure_one()
        return order_windows.window_state(self.env, self.date, moment)

    def _employee_window_open(self, moment=None):
        self.ensure_one()
        return order_windows.window_open(self.env, self.date, moment)

    def _employee_window_message(self, moment=None):
        self.ensure_one()
        return order_windows.window_message(self.env, self.date, moment)

    def _split_mixed_options(self):
        """Pasa postres y bebidas que estaban en product_ids a sus listas propias.

        En Odoo 19 el domain del Many2many se aplica al leer y al escribir, así
        que los acompañamientos mezclados no aparecen en product_ids: hay que
        leer la tabla de relación en crudo (como quedó en datos históricos).
        """
        dessert_categ = self._option_category(DESSERT_CATEGORY_NAME)
        drink_categ = self._option_category(DRINK_CATEGORY_NAME)
        if not self or not (dessert_categ or drink_categ):
            return self.browse()
        Product = self.env["product.product"].with_context(active_test=False)
        self.env.cr.execute(
            """
            SELECT lafija_menu_day_id, product_product_id
              FROM lafija_menu_day_product_product_rel
             WHERE lafija_menu_day_id = ANY(%s)
            """,
            [list(self.ids)],
        )
        by_menu = {}
        for menu_id, product_id in self.env.cr.fetchall():
            by_menu.setdefault(menu_id, []).append(product_id)
        changed = self.browse()
        for menu in self:
            products = Product.browse(by_menu.get(menu.id, [])).exists()
            desserts = menu._products_in_category(products, dessert_categ) | menu.dessert_ids
            drinks = menu._products_in_category(products, drink_categ) | menu.drink_ids
            plates = products - desserts - drinks
            if (set(by_menu.get(menu.id, [])) == set(plates.ids)
                    and set(menu.dessert_ids.ids) == set(desserts.ids)
                    and set(menu.drink_ids.ids) == set(drinks.ids)):
                continue
            menu.with_context(**operation_context(), _lf_skip_category_check=True).write({
                "product_ids": [(6, 0, plates.ids)],
                "dessert_ids": [(6, 0, desserts.ids)],
                "drink_ids": [(6, 0, drinks.ids)],
            })
            # El domain también impide desvincular los que no son platos: limpiar la tabla.
            menu.env.cr.execute(
                """
                DELETE FROM lafija_menu_day_product_product_rel
                 WHERE lafija_menu_day_id = %s
                   AND product_product_id <> ALL(%s)
                """,
                [menu.id, plates.ids or [0]],
            )
            menu.invalidate_recordset(["product_ids"])
            changed |= menu
        return changed

    def action_publish(self):
        check_operator(self.env)
        self.check_access("write")
        self._lock_for_operation()
        unpublished = self.filtered(lambda menu: not menu.published)
        unpublished.write({"published": True})
        # El cierre nativo activa onClose y recarga la ficha abierta. La
        # notificación sola dejaba visible una revisión anterior a la publicación.
        return {"type": "ir.actions.client", "tag": "lf_operation_feedback", "params": {
            "close": True,
            "message": (_("Menú publicado. Las opciones ya están disponibles para ese día.")
                        if unpublished else _("El menú ya estaba publicado. No se hicieron cambios.")),
        }}

    def action_refresh_options(self):
        check_operator(self.env)
        self._lock_for_operation()
        self._record_revision()
        return {"type": "ir.actions.client", "tag": "lf_operation_feedback", "params": {
            "close": True, "message": _("Descripciones copiadas. Las elecciones anteriores se conservan."),
        }}


class MenuRevision(models.Model):
    _name = "lafija.menu.revision"
    _description = "Revisión conservada del menú"
    _order = "number desc"

    menu_id = fields.Many2one("lafija.menu.day", "Menú del día", required=True, ondelete="restrict")
    number = fields.Integer("Revisión", required=True)
    date = fields.Date("Día del menú", required=True)
    website_id = fields.Many2one("website", "Sitio corporativo", required=True)
    published = fields.Boolean("Publicado")
    options = fields.Json("Opciones conservadas")
    desserts = fields.Json("Postres conservados")
    drinks = fields.Json("Bebidas conservadas")
    actor_id = fields.Many2one("res.users", "Quién", required=True)

    @api.model_create_multi
    def create(self, values_list):
        check_operation(self.env)
        return super().create(values_list)

    def write(self, values):
        raise AccessError(_("La historia de la oferta se conserva. Creá una nueva revisión."))

    def unlink(self):
        raise AccessError(_("La historia de la oferta no se elimina."))


class Reservation(models.Model):
    _name = "lafija.reservation"
    _description = "Reserva de vianda"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Referencia", required=True, readonly=True, default="Nueva")
    employee_partner_id = fields.Many2one("res.partner", "Empleado", required=True, ondelete="restrict", groups="base.group_user")
    customer_company_id = fields.Many2one("res.partner", "Empresa cliente", required=True, ondelete="restrict", groups="base.group_user")
    menu_id = fields.Many2one("lafija.menu.day", "Menú del día", required=True, ondelete="restrict", groups="base.group_user")
    date = fields.Date("Fecha de la vianda", required=True, readonly=True, index=True)
    website_id = fields.Many2one("website", "Sitio corporativo", required=True, groups="base.group_user")
    menu_revision = fields.Integer("Revisión de oferta", readonly=True, groups="base.group_user")
    current_product_id = fields.Many2one("product.product", "Plato vigente", ondelete="restrict", groups="base.group_user")
    current_description = fields.Text("Elección vigente", readonly=True)
    current_dessert_id = fields.Many2one("product.product", "Postre vigente", ondelete="restrict", groups="base.group_user")
    current_dessert_description = fields.Text("Postre vigente", readonly=True)
    current_drink_id = fields.Many2one("product.product", "Bebida vigente", ondelete="restrict", groups="base.group_user")
    current_drink_description = fields.Text("Bebida vigente", readonly=True)
    pending_product_id = fields.Many2one("product.product", "Cambio recibido", ondelete="restrict", groups="base.group_user")
    pending_description = fields.Text("Elección pendiente", readonly=True)
    pending_dessert_id = fields.Many2one("product.product", "Postre recibido", ondelete="restrict", groups="base.group_user")
    pending_dessert_description = fields.Text("Postre pendiente", readonly=True)
    pending_drink_id = fields.Many2one("product.product", "Bebida recibida", ondelete="restrict", groups="base.group_user")
    pending_drink_description = fields.Text("Bebida pendiente", readonly=True)
    state = fields.Selection([("active", "Vigente"), ("cancelled", "Cancelada")], string="Estado de la vianda", default="active", required=True, readonly=True)
    attention_pending = fields.Boolean("Solicitud por atender", readonly=True, copy=False)
    pending = fields.Boolean("Requiere atención", compute="_compute_pending", store=True, index=True)
    last_employee_change_at = fields.Datetime("Último cambio del empleado", readonly=True)
    after_reference_time = fields.Boolean("Después del corte diario", readonly=True, index=True)
    after_preparation_cut = fields.Boolean("Después de tomar la lista", readonly=True, index=True)
    event_ids = fields.One2many("lafija.reservation.event", "reservation_id", "Historia", readonly=True, groups="base.group_user")

    _employee_date_unique = models.Constraint("unique(employee_partner_id, date)", "El empleado ya tiene una reserva para ese día.")

    @api.depends("attention_pending", "pending_product_id", "pending_dessert_id", "pending_drink_id")
    def _compute_pending(self):
        for record in self:
            record.pending = bool(record.attention_pending or record.pending_product_id
                                  or record.pending_dessert_id or record.pending_drink_id)

    @api.model_create_multi
    def create(self, values_list):
        check_operation(self.env)
        records = super().create(values_list)
        for record in records:
            if record.name == "Nueva":
                super(Reservation, record).write({"name": f"V-{record.id:06d}"})
        return records

    def write(self, values):
        if set(values) & {
            "name", "employee_partner_id", "customer_company_id", "menu_id", "date", "website_id",
            "menu_revision", "current_product_id", "current_description",
            "current_dessert_id", "current_dessert_description", "current_drink_id", "current_drink_description",
            "pending_product_id", "pending_description",
            "pending_dessert_id", "pending_dessert_description", "pending_drink_id", "pending_drink_description",
            "state", "pending", "attention_pending", "last_employee_change_at",
            "after_reference_time", "after_preparation_cut",
        }:
            check_operation(self.env)
        return super().write(values)

    def unlink(self):
        raise AccessError(_("La reserva y su historia se conservan. Solicitá una cancelación al admin La Fija operativo."))

    @api.model
    def _submission_subject(self, employee=None):
        """Usuario dueño de la reserva y actor del envío.

        El empleado pide por el portal. El operador puede cargar la semana de
        un empleado habilitado; el actor sigue siendo el operador.
        """
        if not employee:
            return self.env.user, self.env.user
        check_operator(self.env)
        employee.ensure_one()
        if employee._name == "res.partner":
            users = employee.sudo().user_ids
            if len(users) != 1:
                raise ValidationError(_("El empleado debe tener una cuenta corporativa habilitada."))
            subject = users
        else:
            subject = employee
        return subject, self.env.user

    def _submission_menus(self, website, selections, subject=None):
        """Valida el alcance del envío antes de consultar sus reservas propias."""
        user = subject or self.env.user
        if not user._lf_can_use_site(website):
            raise AccessError(_("Tu cuenta no está habilitada para este sitio.")
                              if user == self.env.user else
                              _("El empleado no está habilitado para pedir en este sitio."))
        # El envío semanal acota un POST manipulado; la regla de negocio es una reserva por día.
        normalized = [normalize_selection(item) for item in selections]
        if not normalized or len(normalized) > DAYS_PER_WEEK or len({m for m, *_ in normalized}) != len(normalized):
            raise ValidationError(_("Elegí al menos una opción, sin repetir días y hasta una semana por envío."))
        menus = self.env["lafija.menu.day"].sudo().browse([m for m, *_ in normalized]).exists()
        if len(menus) != len(selections):
            raise ValidationError(_("Uno de los menús ya no está disponible. Consultá a La Fija."))
        return menus

    @api.model
    def _last_events_for_submission(self, website, selections, employee=None):
        if not selections:
            return {}
        subject, _actor = self._submission_subject(employee)
        menus = self._submission_menus(website, selections, subject=subject)
        own = self.search([("date", "in", menus.mapped("date")),
                           ("employee_partner_id", "=", subject.partner_id.id)])
        return {record.id: record.sudo().event_ids[-1:].id for record in own}

    @api.model
    def _submit_selections(self, website, selections, withdraw_current=None, employee=None):
        subject, actor = self._submission_subject(employee)
        menus = self._submission_menus(website, selections, subject=subject)
        menus._lock_for_operation()
        today = business_today(self.env)
        withdraw_current = withdraw_current or {}
        result = self.browse()
        empty = self.env["product.product"]
        for menu_id, product_id, dessert_id, drink_id in (normalize_selection(item) for item in selections):
            menu = menus.filtered(lambda m: m.id == menu_id)
            if not menu.published or menu.website_id != website:
                raise ValidationError(_("La opción debe pertenecer al menú publicado de ese día."))
            record = self.sudo().search([("employee_partner_id", "=", subject.partner_id.id), ("date", "=", menu.date)], limit=1)
            # La acción del operador usa la misma exclusión por menú. No decidir
            # con valores cacheados antes de adquirirla (también en un reintento).
            record.invalidate_recordset()
            if record and record.menu_id != menu:
                raise ValidationError(_("Tu reserva corresponde a una oferta anterior. Pedí una corrección a La Fija."))
            current = record.current_product_id if record.state == "active" else empty
            current_triple = (
                current.id,
                record.current_dessert_id.id if record and record.state == "active" else 0,
                record.current_drink_id.id if record and record.state == "active" else 0,
            )
            submitted = (product_id, dessert_id, drink_id)
            expected = withdraw_current.get(menu_id)
            withdrawing = expected == submitted or (expected == product_id and submitted[1:] == current_triple[1:])
            if withdrawing and (not record or current_triple != submitted):
                raise SelectionConflict(menu.id)
            has_pending = bool(record and (record.pending_product_id or record.pending_dessert_id or record.pending_drink_id))
            if current_triple == submitted and has_pending:
                record._withdraw_pending_choice(fields.Datetime.now(), actor)
                result |= self.browse(record.id)
                continue
            if record and record.state == "active":
                retained = (
                    (record.pending_product_id or record.current_product_id).id,
                    (record.pending_dessert_id.id if record.pending_product_id or record.pending_dessert_id or record.pending_drink_id else record.current_dessert_id.id),
                    (record.pending_drink_id.id if record.pending_product_id or record.pending_dessert_id or record.pending_drink_id else record.current_drink_id.id),
                )
                # Si hay pendiente, la elección retenida es el triple pedido; si no, el vigente.
                if has_pending:
                    retained = (
                        record.pending_product_id.id,
                        record.pending_dessert_id.id,
                        record.pending_drink_id.id,
                    )
                if retained == submitted:
                    # Conservar la preselección también después de una corrección manual
                    # fuera del menú. No autoriza a elegir otro producto ajeno.
                    result |= self.browse(record.id)
                    continue
            product = menu.product_ids.filtered(lambda p: p.id == product_id)
            dessert = menu.dessert_ids.filtered(lambda p: p.id == dessert_id) if dessert_id else empty
            drink = menu.drink_ids.filtered(lambda p: p.id == drink_id) if drink_id else empty
            if (not menu.published or menu.website_id != website or not product.active or not product.sale_ok
                    or str(product_id) not in (menu.option_snapshot or {})):
                raise ValidationError(_("El plato debe pertenecer al menú publicado de ese día."))
            if dessert_id and (not dessert or not dessert.active or not dessert.sale_ok
                               or str(dessert_id) not in (menu.dessert_snapshot or {})):
                raise ValidationError(_("El postre debe pertenecer al menú publicado de ese día."))
            if drink_id and (not drink or not drink.active or not drink.sale_ok
                             or str(drink_id) not in (menu.drink_snapshot or {})):
                raise ValidationError(_("La bebida debe pertenecer al menú publicado de ese día."))
            if menu.date < today:
                # La anulación propia y los reenvíos inocuos se resolvieron arriba.
                # La corrección del operador no usa este servicio del empleado.
                raise PastDayConflict(menu.id)
            moment = fields.Datetime.now()
            if not actor.has_group("kai_viandas.group_operator") and not menu._employee_window_open(moment):
                raise OrderWindowClosed(menu._employee_window_message(moment))
            if not record:
                record = self.sudo().with_context(**operation_context()).create({
                    "employee_partner_id": subject.partner_id.id,
                    "customer_company_id": subject.sudo().partner_id.lf_customer_company_id.id,
                    "menu_id": menu.id, "date": menu.date, "website_id": website.id,
                })
            record._apply_employee_choice(
                product, menu.option_snapshot[str(product_id)]["description"],
                dessert, (menu.dessert_snapshot or {}).get(str(dessert_id), {}).get("description") if dessert_id else False,
                drink, (menu.drink_snapshot or {}).get(str(drink_id), {}).get("description") if drink_id else False,
                moment, actor)
            result |= self.browse(record.id)
        return result

    def _withdraw_pending_choice(self, moment, actor):
        """Solo se llama después de validar la reserva propia bajo el bloqueo del menú.

        Anular un cambio pedido no corrige la vianda tomada para preparación ni
        cierra una consulta escrita. Se conserva también el cambio anulado.
        """
        self.ensure_one()
        received = choice_label(self.pending_description, self.pending_dessert_description, self.pending_drink_description)
        applied = choice_label(self.current_description, self.current_dessert_description, self.current_drink_description)
        self.with_context(**operation_context()).write({
            "pending_product_id": False, "pending_description": False,
            "pending_dessert_id": False, "pending_dessert_description": False,
            "pending_drink_id": False, "pending_drink_description": False,
            "last_employee_change_at": moment,
            "after_reference_time": moment > self.menu_id._reference_datetime(),
            "after_preparation_cut": self._has_preparation_cut(),
        })
        self._record_event(actor, moment, "withdrawal", applied, received,
                           applied, self._submission_result(actor, "Cambio anulado por el empleado"))

    def _has_preparation_cut(self):
        self.ensure_one()
        return bool(self.env["lafija.preparation.cut"].sudo().search_count([("menu_id", "=", self.menu_id.id)]))

    def _same_pending_choice(self, product, description, dessert, dessert_description, drink, drink_description):
        return (self.pending_product_id == product and self.pending_description == description
                and self.pending_dessert_id == dessert and (self.pending_dessert_description or False) == (dessert_description or False)
                and self.pending_drink_id == drink and (self.pending_drink_description or False) == (drink_description or False))

    def _same_current_choice(self, product, description, dessert, dessert_description, drink, drink_description):
        return (not self.pending_product_id and not self.pending_dessert_id and not self.pending_drink_id
                and self.state == "active" and self.current_product_id == product
                and self.current_description == description
                and self.current_dessert_id == dessert and (self.current_dessert_description or False) == (dessert_description or False)
                and self.current_drink_id == drink and (self.current_drink_description or False) == (drink_description or False))

    def _apply_employee_choice(self, product, description, dessert, dessert_description, drink, drink_description, moment, actor):
        self.ensure_one()
        dessert = dessert or self.env["product.product"]
        drink = drink or self.env["product.product"]
        dessert_description = dessert_description or False
        drink_description = drink_description or False
        if (self._same_pending_choice(product, description, dessert, dessert_description, drink, drink_description)
                or self._same_current_choice(product, description, dessert, dessert_description, drink, drink_description)):
            return  # Guardar otros días no convierte una elección sin cambios en tardía.
        before = choice_label(self.current_description, self.current_dessert_description, self.current_drink_description)
        received = choice_label(description, dessert_description, drink_description)
        after_cut = self._has_preparation_cut()
        values = {
            "menu_revision": self.menu_id.revision,
            "last_employee_change_at": moment,
            "after_reference_time": moment > self.menu_id._reference_datetime(),
            "after_preparation_cut": after_cut,
        }
        side = {
            "pending_dessert_id": dessert.id, "pending_dessert_description": dessert_description,
            "pending_drink_id": drink.id, "pending_drink_description": drink_description,
        }
        current_side = {
            "current_dessert_id": dessert.id, "current_dessert_description": dessert_description,
            "current_drink_id": drink.id, "current_drink_description": drink_description,
            "pending_dessert_id": False, "pending_dessert_description": False,
            "pending_drink_id": False, "pending_drink_description": False,
        }
        values.update({"current_product_id": product.id, "current_description": description,
                       "pending_product_id": False, "pending_description": False, "state": "active",
                       **current_side})
        self.with_context(**operation_context()).write(values)
        applied = choice_label(self.current_description, self.current_dessert_description, self.current_drink_description)
        self._record_event(actor, moment, "choice", before, received,
                           applied or "", self._submission_result(actor, "Elección aplicada"))
        if after_cut:
            cut = self.menu_id.sudo().cut_ids[:1]
            if cut:
                cut.with_context(**operation_context())._new_revision(
                    _("Cambio del empleado aplicado en la lista"), actor)

    def _submission_result(self, actor, result):
        if actor.partner_id != self.employee_partner_id:
            return f"Cargado por operador · {result}"
        return result

    def _record_event(self, actor, moment, kind, before, received, applied, result):
        self.ensure_one()
        return self.env["lafija.reservation.event"].sudo().with_context(**operation_context()).create({
            "reservation_id": self.id, "actor_id": actor.id, "occurred_at": moment,
            "kind": kind, "previous_description": before, "received_description": received,
            "applied_description": applied, "result": result,
            "after_reference_time": self.after_reference_time, "after_preparation_cut": self.after_preparation_cut,
            "menu_revision": self.menu_revision,
        })

    def _employee_values(self):
        self.ensure_one()
        if self.sudo().employee_partner_id != self.env.user.partner_id:
            raise AccessError(_("Solo podés consultar tus propias reservas."))
        record = self.sudo()
        return {"id": record.id, "reference": record.name, "date": str(record.date),
                "current": record.current_description or "", "pending": record.pending_description or "",
                "current_dessert": record.current_dessert_description or "",
                "current_drink": record.current_drink_description or "",
                "pending_dessert": record.pending_dessert_description or "",
                "pending_drink": record.pending_drink_description or "",
                "current_label": choice_label(record.current_description, record.current_dessert_description, record.current_drink_description),
                "pending_label": choice_label(record.pending_description, record.pending_dessert_description, record.pending_drink_description),
                "needs_attention": record.pending, "attention_pending": record.attention_pending,
                "state": record.state}

    @api.model
    def _lf_migrate_pending_choices_1177(self, exclude_names=None):
        """Aplicar elecciones pendientes como vigentes (1.17.7), salvo las excluidas."""
        exclude_names = set(exclude_names or [])
        records = self.sudo().search([
            "|", "|",
            ("pending_product_id", "!=", False),
            ("pending_dessert_id", "!=", False),
            ("pending_drink_id", "!=", False),
        ])
        migrated = self.browse()
        for record in records:
            if record.name in exclude_names:
                continue
            if not (record.pending_product_id or record.pending_dessert_id or record.pending_drink_id):
                continue
            before = choice_label(record.current_description, record.current_dessert_description,
                                  record.current_drink_description) or ""
            values = {
                "current_product_id": record.pending_product_id.id,
                "current_description": record.pending_description,
                "current_dessert_id": record.pending_dessert_id.id,
                "current_dessert_description": record.pending_dessert_description or False,
                "current_drink_id": record.pending_drink_id.id,
                "current_drink_description": record.pending_drink_description or False,
                "pending_product_id": False, "pending_description": False,
                "pending_dessert_id": False, "pending_dessert_description": False,
                "pending_drink_id": False, "pending_drink_description": False,
                "state": "active",
            }
            record.with_context(**operation_context()).write(values)
            applied = choice_label(record.current_description, record.current_dessert_description,
                                   record.current_drink_description)
            record._record_event(
                self.env.user, fields.Datetime.now(), "resolution", before, "", applied or "",
                "Migración 1.17.7: se aplica la elección pendiente",
            )
            cut = record.menu_id.cut_ids[:1]
            if cut:
                cut.with_context(**operation_context())._new_revision(
                    "Migración 1.17.7: se aplica la elección pendiente", self.env.user)
            migrated |= record
        return migrated


class ReservationEvent(models.Model):
    _name = "lafija.reservation.event"
    _description = "Actuación sobre una reserva"
    _order = "occurred_at, id"

    reservation_id = fields.Many2one("lafija.reservation", required=True, ondelete="restrict")
    actor_id = fields.Many2one("res.users", "Quién", required=True)
    occurred_at = fields.Datetime("Cuándo", required=True)
    kind = fields.Selection([("choice", "Elección del empleado"), ("request", "Solicitud de corrección"),
                             ("withdrawal", "Cambio anulado por el empleado"),
                             ("response", "Respuesta de La Fija"), ("closure", "Solicitud cerrada"),
                             ("resolution", "Resolución de La Fija"),
                             ("fulfillment", "Elaboración y entrega")],
                            string="Actuación", required=True)
    previous_description = fields.Text("Antes")
    received_description = fields.Text("Recibido")
    applied_description = fields.Text("Vigente después")
    result = fields.Text("Resultado / motivo")
    after_reference_time = fields.Boolean("Después del corte diario")
    after_preparation_cut = fields.Boolean("Después de tomar la lista")
    menu_revision = fields.Integer("Revisión de oferta")

    @api.model_create_multi
    def create(self, values_list):
        check_operation(self.env)
        return super().create(values_list)

    def write(self, values):
        raise AccessError(_("Las actuaciones se conservan. Registrá una nueva corrección."))

    def unlink(self):
        raise AccessError(_("El historial de la reserva no se elimina."))
