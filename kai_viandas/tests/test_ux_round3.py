from odoo import Command
from lxml import html
from odoo.tests import Form, tagged

from .test_pages import PagesCommon
from . import test_ux_round2


@tagged('post_install', '-at_install')
class TestUXRound3(PagesCommon):
    # Reutiliza el conductor CDP de puntero; no hereda ni repite sus tests.
    _pointer_browser = test_ux_round2.TestUXRound2._pointer_browser

    def _unpublished_menu(self):
        return self.env['lafija.menu.day'].with_user(self.operator).create({
            'date': '2026-10-19', 'website_id': self.website.id,
            'product_ids': [Command.set(self.product.ids)],
        })

    def test_publication_is_idempotent_without_rewriting_menu_history(self):
        menu = self._unpublished_menu()
        first = menu.revision_ids
        menu.action_publish()
        published = menu.revision_ids
        self.assertTrue(menu.published)
        self.assertEqual(menu.revision, 2)
        menu.action_publish()
        self.assertEqual(menu.revision_ids, published)
        self.assertEqual(menu.revision, 2)
        self.assertFalse(first.published)
        other = self.env['product.product'].create({'name': 'Otra opción', 'sale_ok': True})
        menu.write({'product_ids': [Command.link(other.id)]})
        self.assertEqual(menu.revision, 3)
        menu.action_publish()
        self.assertEqual(menu.revision, 3)
        self.assertEqual(first.options.keys(), {str(self.product.id)})

    def test_pointer_publish_refreshes_the_open_form(self):
        menu = self._unpublished_menu()
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self._pointer_browser(f'/odoo/action-kai_viandas.menu_day_action/{menu.id}', r'''
            const published=()=>document.querySelector('.o_field_widget[name="published"] input');
            await wait(()=>published(),'Falta Publicado en la ficha');
            if (published().checked) throw new Error('El menú debía empezar sin publicar');
            const button=await wait(()=>[...document.querySelectorAll('button[name="action_publish"]')].find(visible),'Falta Publicar');
            await pointer(button);
            await wait(()=>published()?.checked,'Publicar no actualizó la ficha abierta');
            await wait(()=>document.querySelector('.o_field_widget[name="revision"]')?.textContent.trim()==='2','La ficha no muestra la revisión publicada');
            if ([...document.querySelectorAll('button[name="action_publish"]')].some(visible)) throw new Error('Publicar sigue visible después de publicar');
            if (document.querySelector('.o_error_dialog')) throw new Error('Error al publicar');
        ''', self.operator.login, min_clicks=1)
        menu.invalidate_recordset()
        self.assertTrue(menu.published)
        self.assertEqual(menu.revision, 2)
        self.assertEqual(len(menu.revision_ids), 2)

    def test_week_copy_keeps_current_and_pending_distinct_after_cut(self):
        employee, _ = self._create_employee()
        model = self.env['lafija.reservation'].with_user(employee)
        record = model._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        record._request_correction('La consulta debe seguir pendiente')
        self.menus[0].with_user(self.operator).action_take_list()
        self._real_login(employee.login, 'employee-password-123')
        page = self.url_open('/my/viandas?week=2026-09-14')
        self.assertNotIn('Los cambios se aplican al guardar', page.text)
        self.assertIn('Guardás las elecciones de toda esta semana', page.text)
        self.assertIn('lo enviado queda para revisión', page.text)
        self.assertIn('Consulta escrita abierta', page.text)
        doc = html.fromstring(page.content)
        self.assertEqual(doc.xpath(f'//input[@name="menu_{self.menus[0].id}" and @checked]/@value'), [str(self.product.id)])
        self.assertIn('Vigente:', doc.xpath('//details[@data-menu]')[0].text_content())

    def test_revoked_session_returns_to_login_with_neutral_context(self):
        employee, _ = self._create_employee()
        self._real_login(employee.login, 'employee-password-123')
        page = self.url_open('/my/viandas?week=2026-09-14')
        token = html.fromstring(page.content).xpath('//input[@name="csrf_token"]/@value')[0]
        self._manage(employee, 'disable').action_apply()
        denied = self.url_open('/my/viandas/reservar', data={
            'csrf_token': token, 'week': '2026-09-14', f'menu_{self.menus[0].id}': str(self.product.id)})
        self.assertIn('Entrá para continuar', denied.text)
        self.assertIn('Ayuda para recuperar el acceso', denied.text)
        self.assertIn('/viandas/ayuda-acceso', denied.text)
        self.assertNotIn('dado de baja', denied.text)
        self.assertFalse(self.env['lafija.reservation'].search([]))

    def test_pending_queue_action_and_readable_sale_origin_do_not_change_data(self):
        action = self.env['lafija.reservation'].with_user(self.operator).action_pending_all_dates()
        self.assertEqual(action['res_model'], 'lafija.reservation')
        self.assertIn('search_default_pending', action['context'])
        employee, _ = self._create_employee()
        reservation = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        order = self.env['sale.order'].with_user(self.operator).create({
            'partner_id': self.customer.id, 'lf_reservation_ids': [Command.set(reservation.ids)]})
        original = order.lf_origin
        self.assertIn(order.name, order.lf_origin_label)
        self.assertIn(reservation.name, order.lf_origin_label)
        self.assertNotIn('sale.order:', order.lf_origin_label)
        order.lf_reservation_ids = [Command.clear()]
        self.assertEqual(order.lf_origin, original)
        self.assertTrue(order.lf_protected)
        self.assertIn(reservation.name, order.lf_origin_label)
        sales_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Ventas sin rol La Fija', 'login': 'sales-without-lafija',
            'group_ids': [Command.set([self.env.ref('sales_team.group_sale_manager').id])],
        })
        self.assertFalse(sales_user.has_group('kai_viandas.group_operator'))
        self.assertFalse(reservation.with_user(sales_user).has_access('read'))
        self.assertIn('Viandas de origen conservadas', order.with_user(sales_user).lf_origin_label)
        self.assertNotIn(reservation.name, order.with_user(sales_user).lf_origin_label)

    def test_native_sale_pricing_and_tax_mapping_remain_available_to_operator(self):
        # Verificación de integración nativa, sin cálculo propio, facturas ni
        # escritura manual de price_unit. Todos los datos son de esta prueba.
        # Equivale al ajuste nativo de Ventas «Listas de precios»; sin habilitar
        # esa función Odoo no usa la lista configurada en la empresa cliente.
        self.env.ref('base.group_user').write({'implied_ids': [
            Command.link(self.env.ref('product.group_product_pricelist').id),
        ]})
        taxes = self.env['account.tax'].create([
            {'name': 'Impuesto de prueba origen', 'amount': 10, 'type_tax_use': 'sale'},
            {'name': 'Impuesto de prueba destino', 'amount': 5, 'type_tax_use': 'sale'},
        ])
        position = self.env['account.fiscal.position'].create({
            'name': 'Posición fiscal de evaluación',
            'tax_ids': [Command.set(taxes[1].ids)],
        })
        taxes[1].original_tax_ids = taxes[0]
        shared = self.env['product.pricelist'].create({'name': 'Lista B2C compartida de evaluación'})
        self.customer.write({'property_product_pricelist': shared.id, 'property_account_position_id': position.id})
        self.product.write({'list_price': 2700, 'taxes_id': [Command.set(taxes[0].ids)]})
        with Form(self.env['sale.order'].with_user(self.operator)) as sale:
            sale.partner_id = self.customer
            self.assertEqual(sale.pricelist_id, shared)
            self.assertEqual(sale.fiscal_position_id, position)
            with sale.order_line.new() as line:
                line.product_id = self.product
        order = sale.record
        self.assertEqual(order.order_line.price_unit, 2700)
        self.assertEqual(order.order_line.tax_ids, taxes[1])
        self.assertEqual(order.state, 'draft')
        # La misma lista también debe aplicar sus reglas, no solo devolver el
        # precio público cuando no hay reglas especiales para este producto.
        self.env['product.pricelist.item'].create({
            'pricelist_id': shared.id, 'applied_on': '0_product_variant',
            'product_id': self.product.id, 'min_quantity': 2,
            'compute_price': 'fixed', 'fixed_price': 2500,
        })
        with Form(order) as sale:
            with sale.order_line.edit(0) as line:
                line.product_uom_qty = 2
        self.assertEqual(order.order_line.price_unit, 2500)
        self.assertEqual(order.order_line.tax_ids, taxes[1])
