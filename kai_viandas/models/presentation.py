from collections import Counter
from datetime import timedelta
import re

from odoo import api, fields, models

from .identity import check_operator
from .time_utils import business_datetime, business_today, business_tz, day_label, business_date_domain
from .operation_labels import OLD_LABELS, pending_label
from .order_windows import daily_cutoff_label


class Partner(models.Model):
    _inherit = 'res.partner'

    lf_login = fields.Char('Usuario', compute='_compute_lf_login', groups='base.group_user')

    def _compute_lf_login(self):
        for partner in self:
            partner.lf_login = partner.sudo().with_context(active_test=False).user_ids[:1].login or ''


class MenuDay(models.Model):
    _inherit = 'lafija.menu.day'

    preparation_status = fields.Char('Preparación', compute='_compute_preparation_status')
    list_taken = fields.Boolean(compute='_compute_preparation_status')
    day_title = fields.Char('Día', compute='_compute_preparation_status')
    is_upcoming = fields.Boolean(store=False, search='_search_is_upcoming')
    take_list_future = fields.Boolean(compute='_compute_preparation_status')

    def _search_is_upcoming(self, operator, value):
        return business_date_domain(self.env, operator, value, '>=', '<')

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        if 'website_id' in names and not values.get('website_id'):
            sites = self.env['website'].search([('lf_corporate_site', '=', True)], limit=2)
            if len(sites) == 1:
                values['website_id'] = sites.id
        return values

    @api.depends('date', 'website_id', 'cut_ids', 'cut_ids.taken_at', 'cut_ids.taken_by')
    def _compute_preparation_status(self):
        today = business_today(self.env)
        for menu in self:
            cut = menu.cut_ids[:1]
            menu.list_taken = bool(cut)
            menu.day_title = day_label(menu.date) if menu.date and menu.website_id else 'Nuevo menú del día'
            menu.take_list_future = bool(menu.date and menu.date > today)
            menu.preparation_status = (
                f'Lista tomada el {business_datetime(self.env, cut.taken_at)} por {cut.taken_by.name}'
                if cut else 'Todavía no se tomó la lista para preparación.'
            )

    def action_workday(self):
        check_operator(self.env)
        action = self.env['ir.actions.act_window']._for_xml_id('kai_viandas.reservation_action')
        title = f'Hoy · {day_label(business_today(self.env))}'
        action.update(name=title, display_name=title,
                      context={'search_default_today': 1},
                      help='<p>No hay reservas para hoy con estos filtros.</p>'
                           '<p>Puede haber solicitudes de otras fechas. Usá el filtro '
                           '«Requieren atención» o consultá «Menús del día».</p>')
        return action


class Reservation(models.Model):
    _inherit = 'lafija.reservation'

    def action_pending_all_dates(self):
        check_operator(self.env)
        return self.env['ir.actions.act_window']._for_xml_id('kai_viandas.pending_action')

    def action_create_client_orders(self):
        check_operator(self.env)
        return self.env['ir.actions.act_window']._for_xml_id('kai_viandas.employee_order_action')

    change_local = fields.Char('Último acto del empleado · hora de La Fija', compute='_compute_local_display')
    attention_label = fields.Char('Atención', compute='_compute_local_display')
    timing_label = fields.Char('Momento del último acto', compute='_compute_local_display',
                              help='Incluye elecciones, consultas y anulaciones; no indica un pendiente.')
    is_today = fields.Boolean(compute='_compute_local_display', search='_search_is_today')
    is_upcoming = fields.Boolean(store=False, search='_search_is_upcoming')
    is_open_order = fields.Boolean(store=False, search='_search_is_open_order')
    week_label = fields.Char('Semana de la vianda', compute='_compute_week_label', store=True)
    business_week = fields.Integer(store=False, search='_search_business_week')
    other_pending_count = fields.Integer('Pendientes de otras fechas', compute='_compute_local_display', groups='base.group_user')

    @api.depends('last_employee_change_at', 'pending', 'attention_pending', 'pending_product_id', 'current_product_id',
                 'after_reference_time', 'after_preparation_cut', 'date')
    def _compute_local_display(self):
        today = business_today(self.env)
        # Un mismo día comparte el contador: no repetir la consulta por persona.
        pending_by_date = {date: self.search_count([('pending', '=', True), ('date', '!=', date)])
                           for date in set(self.mapped('date'))}
        for record in self:
            record.change_local = business_datetime(self.env, record.last_employee_change_at)
            record.attention_label = pending_label(record.current_product_id, record.pending_product_id,
                                                   record.attention_pending)
            markers = []
            if record.after_reference_time:
                markers.append('Después de las %s' % daily_cutoff_label(record.env))
            if record.after_preparation_cut:
                markers.append('Después de tomar lista')
            record.timing_label = ' · '.join(markers) or 'Antes del cierre'
            record.is_today = record.date == today
            record.other_pending_count = pending_by_date[record.date]

    @api.depends('date')
    def _compute_week_label(self):
        for record in self:
            start = record.date - timedelta(days=record.date.weekday()) if record.date else None
            record.week_label = (f'{start:%d/%m/%Y} al {start + timedelta(days=6):%d/%m/%Y}' if start else '')

    def _search_business_week(self, operator, value):
        # Los filtros usan semanas relativas a la misma zona que la regla de las 10:00.
        if operator != '=' or value not in (-1, 0, 1):
            return NotImplemented
        today = business_today(self.env)
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=value)
        return [('date', '>=', start), ('date', '<', start + timedelta(days=7))]

    def _read_group_orderby(self, order, groupby_terms, query):
        if 'week_label' in groupby_terms:
            # Orden SQL antes de paginar, sin reescribir etiquetas históricas.
            order = re.sub(r'(^|,)\s*week_label(?=\s|,|$)', r'\1date:min',
                           order or ','.join(groupby_terms))
        return super()._read_group_orderby(order, groupby_terms, query)

    def _search_is_today(self, operator, value):
        return business_date_domain(self.env, operator, value)

    def _search_is_upcoming(self, operator, value):
        return business_date_domain(self.env, operator, value, '>=', '<')

    def _search_is_open_order(self, operator, value):
        # Vigentes from today onward, plus anything still pending (any date).
        today = business_today(self.env)
        domain = [
            '&', ('state', '!=', 'cancelled'),
            '|', ('date', '>=', today), ('pending', '=', True),
        ]
        if operator in ('in', 'not in'):
            yes = (True in value) == (operator == 'in')
            no = (False in value) == (operator == 'in')
            if yes == no:
                return [(1, '=', 1 if yes else 0)]
            matched = yes
        elif operator in ('=', '!='):
            matched = bool(value) == (operator == '=')
        else:
            return NotImplemented
        return domain if matched else ['!'] + domain


class ReservationEvent(models.Model):
    _inherit = 'lafija.reservation.event'

    occurred_local = fields.Char('Cuándo · hora de La Fija', compute='_compute_occurred_local')
    result_label = fields.Text('Resultado / motivo', compute='_compute_occurred_local')

    @api.depends('occurred_at', 'result')
    def _compute_occurred_local(self):
        for event in self:
            event.occurred_local = business_datetime(self.env, event.occurred_at)
            prefix, separator, reason = (event.result or '').partition(': ')
            event.result_label = (f'{OLD_LABELS[prefix]}: {reason}' if separator and prefix in OLD_LABELS
                                  else OLD_LABELS.get(event.result, event.result))


class MenuRevision(models.Model):
    _inherit = 'lafija.menu.revision'

    options_text = fields.Text('Opciones publicadas', compute='_compute_options_text')
    changed_local = fields.Char('Modificado el · hora de La Fija', compute='_compute_options_text')

    def _option_lines(self, title, values):
        names = [v.get('description') or v.get('name') or '' for v in (values or {}).values()]
        names = [name for name in names if name]
        return [title + ':'] + names if names else []

    @api.depends('options', 'desserts', 'drinks')
    def _compute_options_text(self):
        for revision in self:
            revision.changed_local = business_datetime(self.env, revision.create_date)
            plates = [v.get('description') or v.get('name') or '' for v in (revision.options or {}).values()]
            extras = self._option_lines('Postres', revision.desserts) + self._option_lines('Bebidas', revision.drinks)
            revision.options_text = '\n'.join(plates + extras)


class PreparationCut(models.Model):
    _inherit = 'lafija.preparation.cut'

    taken_local = fields.Char('Lista tomada · hora de La Fija', compute='_compute_summary')
    timezone_label = fields.Char('Zona horaria de La Fija', compute='_compute_summary')
    meal_count = fields.Integer('Viandas en la lista vigente', compute='_compute_summary')
    option_summary = fields.Text('Cantidades por opción', compute='_compute_summary')
    attention_count = fields.Integer('Reservas por atender', compute='_compute_summary')
    current_print_id = fields.Many2one('lafija.label.print', 'Último archivo vigente', compute='_compute_summary')
    outdated_print_count = fields.Integer('Archivos de revisiones anteriores', compute='_compute_summary')

    @api.depends('current_revision_id', 'current_revision_id.line_ids', 'revision_ids.print_ids', 'pending_ids.pending')
    def _compute_summary(self):
        for cut in self:
            cut.taken_local = business_datetime(self.env, cut.taken_at)
            cut.timezone_label = 'Hora de La Fija'
            lines = cut.current_revision_id.line_ids
            cut.meal_count = len(lines)
            def _summary(records, counter):
                return [f'{p.display_name}: {counter[p.id]}' for p in records]

            quantities = Counter(line.product_id.id for line in lines)
            desserts = Counter(line.dessert_id.id for line in lines if line.dessert_id)
            drinks = Counter(line.drink_id.id for line in lines if line.drink_id)
            products = lines.product_id.sorted(lambda p: (p.display_name, p.id))
            dessert_products = lines.dessert_id.sorted(lambda p: (p.display_name, p.id))
            drink_products = lines.drink_id.sorted(lambda p: (p.display_name, p.id))
            parts = _summary(products, quantities)
            if dessert_products:
                parts += ['Postres'] + _summary(dessert_products, desserts)
            if drink_products:
                parts += ['Bebidas'] + _summary(drink_products, drinks)
            cut.option_summary = '\n'.join(parts)
            cut.attention_count = len(cut.pending_ids.filtered('pending'))
            cut.current_print_id = cut.current_revision_id.print_ids.sorted('id', reverse=True)[:1]
            cut.outdated_print_count = len((cut.revision_ids - cut.current_revision_id).mapped('print_ids'))

    def action_print_current_labels(self):
        check_operator(self.env)
        self.ensure_one()
        return self.current_revision_id.action_print_labels()

    def action_download_current_labels(self):
        check_operator(self.env)
        self.ensure_one()
        return self.current_print_id.action_download()


class PreparationRevision(models.Model):
    _inherit = 'lafija.preparation.revision'

    is_current = fields.Boolean('Vigente', compute='_compute_revision_display')
    occurred_local = fields.Char('Cuándo · hora de La Fija', compute='_compute_revision_display')

    @api.depends('cut_id.current_revision_id', 'occurred_at')
    def _compute_revision_display(self):
        for revision in self:
            revision.is_current = revision.cut_id.current_revision_id == revision
            revision.occurred_local = business_datetime(self.env, revision.occurred_at)

    def action_open_current(self):
        check_operator(self.env)
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Lista vigente',
                'res_model': 'lafija.preparation.revision', 'res_id': self.cut_id.current_revision_id.id, 'view_mode': 'form'}


class LabelPrint(models.Model):
    _inherit = 'lafija.label.print'

    is_current = fields.Boolean(related='revision_id.is_current', string='Revisión vigente')
    generated_local = fields.Char('Generado · hora de La Fija', compute='_compute_generated_local')

    @api.depends('generated_at')
    def _compute_generated_local(self):
        for batch in self:
            batch.generated_local = business_datetime(self.env, batch.generated_at)


class LabelHandling(models.Model):
    _inherit = 'lafija.label.handling'

    occurred_local = fields.Char('Cuándo · hora de La Fija', compute='_compute_local')

    @api.depends('occurred_at')
    def _compute_local(self):
        for item in self:
            item.occurred_local = business_datetime(self.env, item.occurred_at)
