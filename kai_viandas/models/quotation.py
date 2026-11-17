"""Preparación comercial: selección conservada, sin valoración ni facturación propias."""
from collections import Counter, defaultdict
from datetime import timedelta
import hashlib
import json
import uuid

from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .identity import check_operator
from .reservation import check_operation, operation_context
from .time_utils import business_datetime, business_today


def previous_month(env):
    end = business_today(env).replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def quotation_date(value):
    """Solo presentación: las fechas conservadas y su huella siguen en ISO."""
    return fields.Date.to_date(value).strftime('%d/%m/%Y') if value else ''


class QuotationPreparation(models.Model):
    _name = 'lafija.quotation.preparation'
    _description = 'Resumen para preparar cotización'
    _order = 'id desc'

    name = fields.Char('Resumen', compute='_compute_name')
    company_id = fields.Many2one('res.company', 'Compañía vendedora', required=True,
                                default=lambda self: self.env.company, ondelete='restrict')
    customer_company_id = fields.Many2one('res.partner', 'Empresa cliente', required=True,
                                          domain=[('is_company', '=', True)], ondelete='restrict')
    date_from = fields.Date('Desde', required=True, default=lambda self: previous_month(self.env)[0])
    date_to = fields.Date('Hasta', required=True, default=lambda self: previous_month(self.env)[1])
    state = fields.Selection([('draft', 'Elegir período'), ('review', 'Resumen disponible'),
                              ('prepared', 'Cotización preparada')], string='Estado', default='draft', readonly=True)
    operation_key = fields.Char(default=lambda self: str(uuid.uuid4()), readonly=True, copy=False)
    operation_version = fields.Integer(default=0, readonly=True)
    snapshot = fields.Json('Resumen mostrado', readonly=True, copy=False)
    snapshot_token = fields.Char(readonly=True, copy=False)
    prepared_snapshot = fields.Json('Selección conservada', readonly=True, copy=False)
    reviewed_at = fields.Datetime('Resumen consultado el', readonly=True)
    order_id = fields.Many2one('sale.order', 'Cotización preparada', readonly=True,
                              ondelete='set null', copy=False)
    order_reference = fields.Char('Referencia conservada del pedido', readonly=True, copy=False)
    notice = fields.Text('Aviso', readonly=True)
    summary_html = fields.Html('Resumen para preparar cotización', compute='_compute_summary_html', sanitize=True)
    has_available = fields.Boolean('Viandas disponibles', compute='_compute_has_available')

    _key_unique = models.Constraint('unique(operation_key)', 'Esta operación ya existe.')

    @api.depends('customer_company_id.name', 'date_from', 'date_to')
    def _compute_name(self):
        for record in self:
            record.name = (f'{record.customer_company_id.name} · {record.date_from:%d/%m/%Y} – {record.date_to:%d/%m/%Y}'
                           if record.customer_company_id and record.date_from and record.date_to
                           else 'Resumen para preparar cotización')

    @api.onchange('customer_company_id', 'company_id', 'date_from', 'date_to')
    def _onchange_parameters(self):
        # El borrador del formulario no debe ofrecer resultados de otros criterios.
        # write() conserva la invalidación real y action_prepare() su revalidación.
        if self.state != 'prepared':
            self.snapshot = False
            self.snapshot_token = False
            self.state = 'draft'
            self.notice = False

    @api.depends('state', 'snapshot')
    def _compute_has_available(self):
        for record in self:
            record.has_available = bool(record.state == 'review' and (record.snapshot or {}).get('eligible'))

    @api.model_create_multi
    def create(self, values_list):
        check_operator(self.env)
        allowed = {'company_id', 'customer_company_id', 'date_from', 'date_to'}
        if any(set(values) - allowed for values in values_list):
            check_operation(self.env)
        records = super().create(values_list)
        records._validate_parameters()
        return records

    def write(self, values):
        check_operator(self.env)
        settings = {'company_id', 'customer_company_id', 'date_from', 'date_to'}
        if set(values) - settings:
            check_operation(self.env)
        if set(values) & settings:
            if any(record.state == 'prepared' for record in self):
                raise ValidationError(_('La selección preparada se conserva. Abrí otro resumen para un nuevo período.'))
            values = dict(values, snapshot=False, snapshot_token=False, state='draft', notice=False)
        result = super().write(values)
        self._validate_parameters()
        return result

    def unlink(self):
        raise AccessError(_('Las operaciones de preparación se conservan.'))

    def _validate_parameters(self):
        for record in self:
            if record.company_id not in self.env.companies:
                raise AccessError(_('Seleccioná una compañía vendedora habilitada para tu usuario.'))
            if not record.customer_company_id.is_company:
                raise ValidationError(_('El cliente del resumen debe ser una empresa cliente.'))
            if not record.date_from or not record.date_to or record.date_from > record.date_to:
                raise ValidationError(_('Indicá un período válido: Desde no puede ser posterior a Hasta.'))

    def _store(self, values):
        return self.with_context(**operation_context()).write(values)

    def _check(self):
        check_operator(self.env)
        self.ensure_one()
        self.check_access('read')
        self._validate_parameters()

    def _reservation_domain(self):
        return [('date', '>=', self.date_from), ('date', '<=', self.date_to),
                ('customer_company_id', '=', self.customer_company_id.id)]

    def _period_batches(self):
        return self.search([('state', '=', 'prepared'), ('company_id', '=', self.company_id.id),
                            ('customer_company_id', '=', self.customer_company_id.id),
                            ('date_from', '<=', self.date_to), ('date_to', '>=', self.date_from)])

    def _orders_for(self, reservations):
        # Detectar un vínculo oculto no lo vuelve elegible. No entregar sus datos
        # ni crear la venta con sudo: detenerse si el alcance comercial es insuficiente.
        records = self.env['sale.order'].sudo().search([('lf_reservation_ids', 'in', reservations.ids)])
        orders = self.env['sale.order'].browse(records.ids)
        if not orders.has_access('read'):
            raise AccessError(_('Hay pedidos vinculados fuera de tu alcance comercial. Revisá las compañías habilitadas antes de continuar.'))
        return orders

    def _commercial_orders(self, orders):
        """Los pedidos diarios de la lista no cierran el período hasta que se reutilizan al preparar la cotización.

        Así el resumen sigue mostrando las viandas disponibles para el anexo y no se crea un segundo
        pedido de facturación. Una vez preparada la cotización del período, ese mismo pedido diario
        queda como «ya incluido».
        """
        acknowledged = self.env['lafija.quotation.preparation'].sudo().search([
            ('state', '=', 'prepared'), ('order_id', '!=', False),
            ('customer_company_id', '=', self.customer_company_id.id),
            ('company_id', '=', self.company_id.id),
        ]).order_id
        return orders.filtered(lambda order: not order.lf_preparation_date or order in acknowledged)

    def _row(self, reservation, line=None):
        product = reservation.current_product_id.with_context(active_test=False)
        dessert = reservation.current_dessert_id.with_context(active_test=False)
        drink = reservation.current_drink_id.with_context(active_test=False)
        return {'id': reservation.id, 'reference': reservation.name,
                'employee': reservation.employee_partner_id.name,
                'employee_id': reservation.employee_partner_id.id,
                'date': str(reservation.date), 'company_id': reservation.customer_company_id.id,
                'company': reservation.customer_company_id.name, 'menu_id': reservation.menu_id.id,
                'product_id': product.id or False, 'product': product.display_name or '',
                'description': reservation.current_description or '', 'quantity': 1,
                'dessert_id': dessert.id or False, 'dessert': reservation.current_dessert_description or dessert.display_name or '',
                'drink_id': drink.id or False, 'drink': reservation.current_drink_description or drink.display_name or '',
                'revision_id': line.revision_id.id if line else False,
                'revision': line.revision_id.number if line else False,
                'line_id': line.id if line else False}

    @staticmethod
    def _group_products(rows):
        groups = {}
        for row in rows:
            group = groups.setdefault(row['product_id'], {'id': row['product_id'], 'name': row['product'],
                                                          'quantity': 0, 'reservations': []})
            group['quantity'] += 1
            group['reservations'].append(row)
        return sorted(groups.values(), key=lambda item: (item['name'].casefold(), item['id'] or 0))

    @staticmethod
    def _group_sides(rows, ident, name):
        groups = {}
        for row in rows:
            if not row.get(ident):
                continue
            group = groups.setdefault(row[ident], {'id': row[ident], 'name': row.get(name) or '',
                                                   'quantity': 0, 'reservations': []})
            group['quantity'] += 1
            group['reservations'].append(row)
        return sorted(groups.values(), key=lambda item: (item['name'].casefold(), item['id']))

    def _collect(self):
        self._check()
        reservations = self.env['lafija.reservation'].with_context(active_test=False).search(
            self._reservation_domain(), order='date, employee_partner_id, id')
        historical = self.env['lafija.preparation.line'].search([
            ('date', '>=', self.date_from), ('date', '<=', self.date_to),
            ('customer_company_id', '=', self.customer_company_id.id),
            ('reservation_id.state', '=', 'cancelled'),
            ('revision_id.cut_id.menu_id.website_id.company_id', '=', self.company_id.id)], order='id desc')
        batches = self._period_batches()
        source_ids = {row['id'] for batch in batches for row in (batch.prepared_snapshot or {}).get('eligible', [])
                      if str(self.date_from) <= row['date'] <= str(self.date_to)}
        originals = self.env['lafija.reservation'].browse(sorted(source_ids)).exists()
        all_reservations = reservations | historical.reservation_id | originals
        orders = self._orders_for(all_reservations)
        commercial = self._commercial_orders(orders)
        order_map = defaultdict(list)
        state_labels = dict(self.env['sale.order']._fields['state']._description_selection(self.env))
        for order in orders.sorted('id'):
            for reservation in order.lf_reservation_ids & all_reservations:
                order_map[reservation.id].append({'id': order.id, 'name': order.name,
                                                  'state': order.state, 'state_label': state_labels[order.state]})
        cuts = self.env['lafija.preparation.cut'].search([('menu_id', 'in', reservations.menu_id.ids)])
        cut_map = {cut.menu_id.id: cut for cut in cuts}
        line_map = {line.reservation_id.id: line for line in cuts.current_revision_id.line_ids}
        eligible, included, issues, missing_days = [], [], [], {}
        signatures = []
        unit = self.env.ref('uom.product_uom_unit')
        for reservation in reservations:
            line = line_map.get(reservation.id)
            row = self._row(reservation, line)
            links = order_map[reservation.id]
            live = [order for order in links if order['state'] != 'cancel' and order['id'] in commercial.ids]
            signatures.append([row, reservation.state, reservation.pending_product_id.id,
                               reservation.attention_pending, str(reservation.last_employee_change_at),
                               links, reservation.current_product_id.active, reservation.current_product_id.sale_ok,
                               reservation.current_product_id.uom_id.id, reservation.menu_id.website_id.company_id.id])
            if live:
                included.append(dict(row, orders=live))
            if len(live) > 1:
                issues.append(dict(row, type='duplicate', text='Vínculos duplicados: aparece en más de un pedido no cancelado.', orders=live))
            cancelled_orders = [order for order in links if order['state'] == 'cancel']
            if cancelled_orders:
                issues.append(dict(row, type='cancelled_order', text='Tuvo un pedido cancelado. Revisá su historia comercial antes de volver a incluirla.', orders=cancelled_orders))
            if reservation.attention_pending:
                issues.append(dict(row, type='request', text='Consulta escrita abierta: aviso; no excluye la vianda vigente.'))
            if reservation.state != 'active' or not reservation.current_product_id:
                if reservation.state == 'active' and reservation.pending_product_id:
                    issues.append(dict(row, type='new_pending', text='Reserva nueva sin vianda vigente: no se incluye.'))
                continue
            if reservation.menu_id.website_id.company_id != self.company_id:
                issues.append(dict(row, type='seller', text='Corresponde a otra compañía vendedora. Prepará su resumen en esa compañía.'))
                continue
            if reservation.menu_id.id not in cut_map:
                item = missing_days.setdefault(reservation.menu_id.id, dict(
                    menu_id=reservation.menu_id.id, date=str(reservation.date), company=self.customer_company_id.name,
                    quantity=0, website=reservation.website_id.name))
                item['quantity'] += 1
                continue
            product = reservation.current_product_id
            if not product.active or not product.sale_ok or (product.company_id and product.company_id != self.company_id):
                issues.append(dict(row, type='product', text='Producto archivado, no vendible o de otra compañía: no se incluye.'))
                continue
            if product.uom_id != unit:
                issues.append(dict(row, type='unit', text='El producto no usa Unidades. Revisá la unidad comercial de esta vianda; no se convierte automáticamente.'))
                continue
            if not line or (line.product_id != product or line.customer_company_id != reservation.customer_company_id
                            or line.date != reservation.date):
                issues.append(dict(row, type='revision', text='La vianda vigente no coincide con la revisión actual de preparación: requiere corrección.'))
                continue
            if not live:
                eligible.append(row)
        seen = set()
        for line in historical:
            if line.reservation_id.id in seen:
                continue
            seen.add(line.reservation_id.id)
            issues.append({'type': 'cancelled_prepared', 'id': line.reservation_id.id,
                           'reference': line.reservation_id.name, 'employee': line.employee_name,
                           'date': str(line.date), 'product': line.product_id.display_name,
                           'company': line.company_name, 'revision': line.revision_id.number,
                           'text': 'Cancelada después de figurar en preparación. No se incluye; La Fija decide cómo resolverla.',
                           'orders': order_map[line.reservation_id.id]})
        for batch in batches:
            issues.extend(batch._discrepancies(self.date_from, self.date_to))
        return {'company': self.customer_company_id.name, 'company_id': self.customer_company_id.id,
                'seller': self.company_id.name, 'seller_id': self.company_id.id,
                'date_from': str(self.date_from), 'date_to': str(self.date_to),
                'eligible': eligible, 'products': self._group_products(eligible),
                'desserts': self._group_sides(eligible, 'dessert_id', 'dessert'),
                'drinks': self._group_sides(eligible, 'drink_id', 'drink'),
                'included': included,
                'issues': issues, 'missing_days': list(missing_days.values()),
                'menu_ids': sorted(set(reservations.menu_id.ids + originals.menu_id.ids)),
                'signature': signatures}

    def _discrepancies(self, date_from=None, date_to=None):
        """Comparar con lo preparado, sin usar la procedencia como cerrojo comercial."""
        self.ensure_one()
        if not self.prepared_snapshot:
            return []
        snapshot = self.prepared_snapshot
        rows = snapshot['eligible']
        selected = [row for row in rows if (not date_from or str(date_from) <= row['date'])
                    and (not date_to or row['date'] <= str(date_to))]
        if not selected:
            return []
        order = self.order_id
        order.check_access('read')
        records = {r.id: r for r in self.env['lafija.reservation'].browse([r['id'] for r in rows]).exists()}
        issues = []
        for row in selected:
            record = records.get(row['id'])
            reasons = []
            if not record or (record.state != 'active' or record.current_product_id.id != row['product_id']
                              or record.customer_company_id.id != row['company_id']
                              or str(record.date) != row['date'] or record.current_description != row['description']):
                reasons.append('La reserva cambió después de preparar la cotización')
            if not order or not record or record not in order.lf_reservation_ids:
                reasons.append('El vínculo comercial original ya no está presente')
            if reasons:
                issues.append(dict(row, type='difference', text='. '.join(reasons) + '. Revisá el pedido; no se sincroniza solo.',
                                   orders=[{'id': order.id, 'name': order.name or self.order_reference,
                                            'state_label': dict(order._fields['state']._description_selection(self.env)).get(order.state, '')}] if order else []))
        expected = Counter(row['product_id'] for row in rows)
        actual = Counter()
        for line in order.order_line.filtered(lambda line: not line.display_type):
            actual[line.product_id.id] += line.product_uom_qty
        if order and (actual != expected or order.partner_id.id != snapshot['company_id']
                      or set(order.lf_reservation_ids.ids) != {row['id'] for row in rows}
                      or any(line.product_uom_id != line.product_id.uom_id for line in order.order_line if not line.display_type)):
            issues.append({'type': 'order_difference', 'text': 'El cliente, las líneas, cantidades o vínculos del pedido difieren de la selección preparada. Revisá el pedido.',
                           'orders': [{'id': order.id, 'name': order.name, 'state_label': dict(order._fields['state']._description_selection(self.env))[order.state]}]})
        return issues

    @api.depends('snapshot', 'state', 'prepared_snapshot', 'reviewed_at', 'order_reference')
    def _compute_summary_html(self):
        for record in self:
            record.summary_html = (record.env['ir.qweb']._render('kai_viandas.quotation_summary', {
                'summary': record.snapshot, 'prepared': record.state == 'prepared',
                'reviewed_at': business_datetime(record.env, record.reviewed_at),
                'quotation_date': quotation_date,
            }) if record.snapshot else False)

    def _form_action(self):
        return {'type': 'ir.actions.act_window', 'name': _('Resumen para preparar cotización'),
                'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'current',
                'views': [(self.env.ref('kai_viandas.quotation_preparation_form').id, 'form')]}

    def _reload_action(self, feedback=False):
        return {'type': 'ir.actions.client', 'tag': 'lf_quotation_reload',
                'params': {'form': self._form_action(), 'feedback': feedback}}

    def action_refresh(self):
        self._check()
        snapshot = self._collect()
        self._store({'snapshot': snapshot, 'snapshot_token': digest(snapshot), 'reviewed_at': fields.Datetime.now(),
                     'state': 'prepared' if self.state == 'prepared' else 'review', 'notice': False})
        return self._reload_action(feedback=_('Resumen actualizado.'))

    def action_prepare(self):
        self._check()
        self.check_access('write')
        self.flush_recordset()
        # La fila de operación coordina también dos clics del mismo formulario.
        self.env.cr.execute('UPDATE lafija_quotation_preparation SET operation_version = operation_version + 1 WHERE id = %s', [self.id])
        self.invalidate_recordset()
        if self.state == 'prepared':
            return self.action_open_order()
        if not self.snapshot:
            return self.action_refresh()
        seen_token = self.env.context.get('lf_seen_summary') or self.snapshot_token
        menus = self.env['lafija.menu.day'].search([
            ('date', '>=', self.date_from), ('date', '<=', self.date_to),
            ('website_id.company_id', '=', self.company_id.id)])
        menus |= self.env['lafija.menu.day'].browse(self.snapshot.get('menu_ids', [])).exists()
        menus._lock_for_operation()
        self.env.invalidate_all()
        snapshot = self._collect()
        if digest(snapshot) != seen_token:
            self._store({'snapshot': snapshot, 'snapshot_token': digest(snapshot), 'reviewed_at': fields.Datetime.now(),
                         'notice': 'El resumen cambió. No se creó ninguna cotización. Revisá el estado actualizado y volvé a preparar.'})
            return self._reload_action()
        if not snapshot['eligible']:
            raise UserError(_('No hay viandas disponibles para preparar cotización. Revisá las incluidas y las incidencias.'))
        eligible = self.env['lafija.reservation'].browse([row['id'] for row in snapshot['eligible']])
        daily = eligible._lf_daily_orders().filtered(lambda order: order.company_id == self.company_id)
        covered = eligible.filtered(lambda reservation: reservation in daily.lf_reservation_ids)
        uncovered = eligible - covered
        # Pedidos diarios confirmados al tomar la lista: no se crea otro pedido ni otra facturación.
        if covered and not uncovered:
            order = daily if len(daily) == 1 else self.env['sale.order']
            values = {'state': 'prepared', 'prepared_snapshot': snapshot, 'notice': False}
            if order:
                values.update(order_id=order.id, order_reference=order.name)
            self._store(values)
            return self.action_open_order() if order else self.action_period_orders()
        # Contexto de compañía y cálculo comercial nativos. No asignar website_id:
        # este borrador no es un carrito y no entra en el checkout de la tienda.
        # Solo se crea un pedido de período para reservas históricas sin pedido diario.
        period = f'{self.date_from:%d/%m/%Y} al {self.date_to:%d/%m/%Y}'
        commercial_context = {key: value for key, value in self.env.context.items()
                              if not key.startswith('default_')}
        leftover = [row for row in snapshot['eligible'] if row['id'] in uncovered.ids]
        leftover_products = self._group_products(leftover)
        order = self.env['sale.order'].with_context(commercial_context).with_company(self.company_id).create({
            'partner_id': self.customer_company_id.id, 'company_id': self.company_id.id,
            'lf_reservation_ids': [Command.set([row['id'] for row in leftover])],
            'order_line': [Command.create({'product_id': product['id'], 'product_uom_qty': product['quantity'],
                                            'name': f"{product['name']}\nPeríodo: {period}"})
                           for product in leftover_products],
        })
        self._store({'state': 'prepared', 'prepared_snapshot': snapshot, 'order_id': order.id,
                     'order_reference': order.name, 'notice': False})
        return self.action_open_order()

    def action_open_order(self):
        self._check()
        if not self.order_id:
            if self.state == 'prepared':
                return self.action_period_orders()
            raise UserError(_('La cotización de esta operación ya no está disponible. Revisá su referencia conservada; un reintento no crea otra.'))
        self.order_id.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Cotización preparada'), 'res_model': 'sale.order',
                'res_id': self.order_id.id, 'views': [(self.env.ref('sale.view_order_form').id, 'form')],
                'view_mode': 'form', 'target': 'current'}

    def action_period_orders(self):
        self._check()
        reservations = self.env['lafija.reservation'].search(self._reservation_domain())
        historical = self._period_batches().filtered(lambda batch: any(
            str(self.date_from) <= row['date'] <= str(self.date_to)
            for row in (batch.prepared_snapshot or {}).get('eligible', [])))
        orders = self._orders_for(reservations) | historical.order_id
        orders = orders.filtered(lambda order: order.company_id == self.company_id)
        return {'type': 'ir.actions.act_window', 'name': _('Pedidos del período'), 'res_model': 'sale.order',
                'view_mode': 'list,form', 'domain': [('id', 'in', orders.ids)],
                'views': [(self.env.ref('sale.view_quotation_tree').id, 'list'),
                          (self.env.ref('sale.view_order_form').id, 'form')],
                'context': {'default_partner_id': self.customer_company_id.id,
                            'allowed_company_ids': self.env.companies.ids}}

    def action_print_annex(self):
        self._check()
        if not (self.prepared_snapshot or self.snapshot):
            raise UserError(_('Consultá el resumen antes de imprimir su anexo.'))
        return self.env.ref('kai_viandas.report_quotation_annex').report_action(self)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    lf_quotation_preparation_ids = fields.One2many('lafija.quotation.preparation', 'order_id',
        string='Selección conservada al preparar', readonly=True, groups='kai_viandas.group_operator')
    lf_quotation_difference = fields.Text('Cambios respecto de lo preparado', compute='_compute_lf_quotation_difference',
                                         groups='kai_viandas.group_operator')

    @api.depends('lf_quotation_preparation_ids', 'lf_reservation_ids', 'order_line.product_id',
                 'order_line.product_uom_qty', 'order_line.product_uom_id', 'partner_id',
                 'lf_reservation_ids.state', 'lf_reservation_ids.current_product_id',
                 'lf_reservation_ids.current_description', 'lf_reservation_ids.customer_company_id',
                 'lf_reservation_ids.date')
    def _compute_lf_quotation_difference(self):
        for order in self:
            order.lf_quotation_difference = '\n'.join(dict.fromkeys(
                issue['text'] for batch in order.lf_quotation_preparation_ids for issue in batch._discrepancies()))

    def action_lf_quotation_annex(self):
        check_operator(self.env)
        self.ensure_one()
        self.check_access('read')
        batch = self.lf_quotation_preparation_ids
        if not batch:
            raise UserError(_('Este pedido no tiene un resumen preparado por La Fija.'))
        return batch.action_print_annex()


class QuotationAnnex(models.AbstractModel):
    _name = 'report.kai_viandas.quotation_annex'
    _description = 'Anexo de viandas por empresa y período, sin importes'

    def _get_report_values(self, docids, data=None):
        check_operator(self.env)
        batches = self.env['lafija.quotation.preparation'].browse(docids).exists()
        batches.check_access('read')
        sheets = []
        for batch in batches:
            batch._check()
            snapshot = batch.prepared_snapshot or batch.snapshot
            if not snapshot:
                raise UserError(_('Consultá el resumen antes de imprimir su anexo.'))
            sheets.append({'id': batch.id, 'summary': snapshot,
                           'order': batch.order_reference or '', 'prepared': batch.state == 'prepared',
                           'generated_at': business_datetime(self.env, fields.Datetime.now())})
        return {'doc_ids': batches.ids, 'doc_model': batches._name, 'docs': batches, 'sheets': sheets,
                'quotation_date': quotation_date}
