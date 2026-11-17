from odoo import api, fields, models

from .time_utils import day_label


class Reservation(models.Model):
    _inherit = 'lafija.reservation'

    lf_sale_order_ids = fields.Many2many('sale.order', string='Pedidos vinculados',
                                       compute='_compute_lf_sale_orders', groups='kai_viandas.group_operator')

    @api.depends_context('uid')
    def _compute_lf_sale_orders(self):
        orders = self.env['sale.order'].search([('lf_reservation_ids', 'in', self.ids)])
        for reservation in self:
            reservation.lf_sale_order_ids = orders.filtered(lambda order: reservation in order.lf_reservation_ids)

    @api.depends('name', 'date', 'employee_partner_id.name')
    @api.depends_context('lf_origin_display', 'uid')
    def _compute_display_name(self):
        super()._compute_display_name()
        if self.env.context.get('lf_origin_display') and self.env.user.has_group('kai_viandas.group_operator'):
            for reservation in self:
                reservation.display_name = f'{reservation.name} · {reservation.employee_partner_id.name} · {day_label(reservation.date)}'


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    lf_origin_label = fields.Text('Procedencia de las viandas', compute='_compute_lf_origin_label',
                                 groups='base.group_user')

    @api.depends('lf_origin', 'lf_reservation_ids', 'name')
    @api.depends_context('uid')
    def _compute_lf_origin_label(self):
        for order in self:
            origins = {'sale.order': [], 'reserva': []}
            for line in (order.lf_origin or '').splitlines():
                model, separator, identifier = line.partition(':')
                if separator and model in origins and identifier.isdigit():
                    origins[model].append(int(identifier))
            # Solo lectura de las referencias conservadas: quitar una relación
            # del formulario no hace desaparecer la procedencia original.
            sales = self.browse(origins['sale.order']).exists()
            reservations = self.env['lafija.reservation'].browse(origins['reserva']).exists()
            if self.env['lafija.reservation'].has_access('read'):
                reservations |= order.lf_reservation_ids
            parts = []
            if sales and sales.has_access('read'):
                parts.append('Pedido de origen: ' + ', '.join(sales.mapped('name')))
            elif order.lf_origin:
                parts.append('Pedido de origen conservado')
            if reservations and reservations.has_access('read'):
                parts.append('Viandas: ' + ', '.join(reservations.sorted('id').mapped('name')))
            elif reservations:
                # Un usuario de Ventas puede consultar el pedido sin recibir
                # permiso nuevo sobre reservas por esta mejora de presentación.
                parts.append('Viandas de origen conservadas')
            order.lf_origin_label = '\n'.join(parts) or False
