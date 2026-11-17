import copy
from datetime import date
from io import BytesIO
from unittest.mock import patch

from freezegun import freeze_time
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import save_test_file
from odoo.tools.pdf import PdfReader

from .test_preparation import PreparationCommon
from .test_pages import PagesCommon
from .test_release_160 import TestRelease160


@tagged('post_install', '-at_install')
class TestQuotation180(PreparationCommon):
    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-10-01 15:00:00', tick=True))
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.cut = self._take()
        self.model = self.env['lafija.quotation.preparation'].with_user(self.operator)

    def _summary(self, **values):
        batch = self.model.create({'customer_company_id': self.customer.id, **values})
        batch.action_refresh()
        return batch

    def _another(self, login='lf180-extra', product=None, menu=None):
        employee, _ = self._create_employee(login)
        with freeze_time('2026-09-08 12:00:00'):
            # La lista del día ya existe: resolver la nueva solicitud conscientemente.
            record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
                self.website, [((menu or self.menu).id, (product or self.chicken).id)])
        if not record.sudo().current_product_id:
            self.env['lafija.reservation.correction'].with_user(self.operator).create({
                'reservation_id': record.id, 'operation': 'accept', 'reason': 'Preparación sintética 180',
            }).action_apply()
        return record.with_user(self.operator)

    def _sale(self, reservations=None, state='draft', **values):
        return self.env['sale.order'].with_user(self.operator).create({
            'partner_id': self.customer.id, 'state': state,
            'lf_reservation_ids': [Command.set((reservations or self.reservation).ids)],
            'order_line': [Command.create({'product_id': self.chicken.id, 'product_uom_qty': 1})], **values})

    def test_default_previous_calendar_month_uses_business_midnight_and_year(self):
        for moment, expected in [('2026-10-01 02:59:59', (date(2026, 8, 1), date(2026, 8, 31))),
                                 ('2026-10-01 03:00:00', (date(2026, 9, 1), date(2026, 9, 30))),
                                 ('2027-01-01 03:00:00', (date(2026, 12, 1), date(2026, 12, 31)))]:
            with freeze_time(moment):
                batch = self.model.create({'customer_company_id': self.customer.id})
                self.assertEqual((batch.date_from, batch.date_to), expected)

    def test_invalid_period_and_person_customer_rejected(self):
        for values in ({'date_from': '2026-10-02', 'date_to': '2026-10-01'},
                       {'customer_company_id': self.employee.partner_id.id}):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self._summary(**values)

    def test_summary_groups_variants_not_description_and_never_sums_revisions(self):
        twin = self.env['product.product'].create({'name': 'Otra variante 180', 'description_sale': 'Pollo'})
        self.menu.with_user(self.operator).write({'product_ids': [Command.link(twin.id)]})
        extra = self._another()
        other = self._another('lf180-twin', twin)
        self._resolve('replace', product_id=self.chicken.id)
        batch = self._summary()
        self.assertEqual({p['id']: p['quantity'] for p in batch.snapshot['products']}, {self.chicken.id: 2, twin.id: 1})
        self.assertEqual({r['id'] for r in batch.snapshot['eligible']}, {self.reservation.id, extra.id, other.id})
        self.assertTrue(all(r['revision_id'] == self.cut.current_revision_id.id for r in batch.snapshot['eligible']))

    def test_dates_inclusive_and_reservation_company_survives_employee_transfer(self):
        other_company = self.env['res.partner'].create({'name': 'Otra empresa 180', 'is_company': True})
        self._manage(self.employee, 'update', customer_company_id=other_company.id, website_id=self.website.id).action_apply()
        exact = self._summary(date_from='2026-09-14', date_to='2026-09-14')
        self.assertEqual(len(exact.snapshot['eligible']), 1)
        self.assertFalse(self._summary(customer_company_id=other_company.id).snapshot['eligible'])
        self.assertFalse(self._summary(date_from='2026-09-15').snapshot['eligible'])

    def test_missing_list_is_grouped_by_day_and_customer(self):
        record = self._another(menu=self.menus[1])
        batch = self._summary()
        self.assertEqual([d['quantity'] for d in batch.snapshot['missing_days']], [1])
        self.assertEqual(batch.snapshot['missing_days'][0]['menu_id'], record.menu_id.id)
        self.assertEqual([r['id'] for r in batch.snapshot['eligible']], [self.reservation.id])
        self.assertIn('todas las empresas', str(batch.summary_html))

    def test_hidden_commercial_link_stops_instead_of_counting_as_available(self):
        company = self.env['res.company'].create({'name': 'Vendedor separado 180'})
        self.env['sale.order'].with_company(company).create({
            'partner_id': self.customer.id, 'company_id': company.id,
            'lf_reservation_ids': [Command.set(self.reservation.ids)],
        })
        with self.assertRaises(AccessError):
            self._summary()

    def test_selected_authorized_seller_is_used_without_website_on_order(self):
        company = self.env['res.company'].create({'name': 'Vendedor habilitado 180'})
        self.operator.company_ids = self.env.company | company
        self.website.company_id = company
        batch = self.model.with_context(allowed_company_ids=[company.id, self.env.company.id]).create({
            'company_id': company.id, 'customer_company_id': self.customer.id})
        batch.action_refresh()
        batch.action_prepare()
        self.assertEqual(batch.order_id.company_id, company)
        self.assertFalse(batch.order_id.website_id)

    def test_pending_choice_uses_current_and_open_request_does_not_exclude(self):
        with freeze_time('2026-09-14 14:00:00'):
            self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
            employee, _ = self._create_employee('lf180-pending')
            new = self.env['lafija.reservation'].with_user(employee)._submit_selections(self.website, [(self.menu.id, self.pork.id)])
        self.reservation._request_correction('Consulta de preparación 180')
        batch = self._summary()
        self.assertEqual([p['id'] for p in batch.snapshot['products']], [self.chicken.id])
        self.assertEqual({r['type'] for r in batch.snapshot['issues']}, {'request', 'new_pending'})
        self.assertNotIn(new.id, [r['id'] for r in batch.snapshot['eligible']])

    def test_cancelled_after_preparation_uses_conserved_company_date_and_revision(self):
        self._resolve('cancel')
        batch = self._summary()
        self.assertFalse(batch.snapshot['eligible'])
        issue = next(r for r in batch.snapshot['issues'] if r['type'] == 'cancelled_prepared')
        self.assertEqual((issue['date'], issue['company'], issue['product']),
                         ('2026-09-14', self.customer.name, self.chicken.display_name))
        self.assertEqual(issue['revision'], 1)

    def test_archived_not_sellable_and_non_unit_products_require_review(self):
        for values, kind in [({'active': False}, 'product'), ({'sale_ok': False}, 'product'),
                             ({'uom_id': self.env.ref('uom.product_uom_kgm').id}, 'unit')]:
            with self.subTest(values=values), self.cr.savepoint():
                previous = {name: self.chicken[name].id if name == 'uom_id' else self.chicken[name] for name in values}
                self.chicken.write(values)
                batch = self._summary()
                self.assertFalse(batch.snapshot['eligible'])
                self.assertIn(kind, [r['type'] for r in batch.snapshot['issues']])
                self.chicken.write(previous)

    def test_draft_sent_and_confirmed_links_exclude_cancelled_warns(self):
        for state in ('draft', 'sent', 'sale', 'cancel'):
            with self.subTest(state=state):
                order = self._sale(state=state)
                batch = self._summary()
                self.assertEqual(bool(batch.snapshot['eligible']), state == 'cancel')
                self.assertEqual(bool(batch.snapshot['included']), state != 'cancel')
                if state == 'cancel':
                    self.assertIn('cancelled_order', [row['type'] for row in batch.snapshot['issues']])
                order.lf_reservation_ids = False

    def test_cancelled_and_live_links_exclude_and_duplicate_copy_is_visible(self):
        self._sale(state='cancel')
        live = self._sale()
        duplicate = live.copy()
        batch = self._summary()
        self.assertFalse(batch.snapshot['eligible'])
        self.assertEqual({o['id'] for o in batch.snapshot['included'][0]['orders']}, {live.id, duplicate.id})
        self.assertIn('duplicate', [row['type'] for row in batch.snapshot['issues']])

    def test_create_one_native_draft_protected_with_exact_products_and_source(self):
        extra = self._another()
        batch = self._summary()
        revision_ids = self.cut.revision_ids.ids
        action = batch.action_prepare()
        order = batch.order_id
        self.assertEqual(action['res_id'], order.id)
        daily = self.reservation._lf_daily_orders()
        self.assertEqual(order, daily)
        self.assertEqual(order.state, 'sale')
        self.assertEqual(order.partner_id, self.customer)
        self.assertEqual(order.company_id, self.website.company_id)
        self.assertFalse(order.website_id)
        lines = order.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty)
        self.assertEqual(lines.product_id, self.chicken)
        self.assertEqual(sum(lines.mapped('product_uom_qty')), 2)
        self.assertEqual(set(order.lf_reservation_ids.ids), {extra.id, self.reservation.id})
        self.assertTrue(order.lf_protected)
        self.assertIn(str(self.cut.date), order.origin or '')
        self.assertEqual(batch.prepared_snapshot['eligible'], batch.snapshot['eligible'])
        self.assertEqual(self.cut.revision_ids.ids, revision_ids)
        self.assertFalse(order.invoice_ids)

    def test_server_native_pricelist_quantity_fiscal_position_and_taxes(self):
        self.env.ref('base.group_user').write({'implied_ids': [Command.link(self.env.ref('product.group_product_pricelist').id)]})
        origin, mapped = self.env['account.tax'].create([
            {'name': 'Origen 180', 'amount': 10, 'type_tax_use': 'sale'},
            {'name': 'Destino 180', 'amount': 5, 'type_tax_use': 'sale'},
        ])
        mapped.original_tax_ids = origin
        position = self.env['account.fiscal.position'].create({'name': 'Posición 180', 'tax_ids': [Command.set(mapped.ids)]})
        shared = self.env['product.pricelist'].create({'name': 'B2C compartida 180'})
        self.customer.write({'property_product_pricelist': shared.id, 'property_account_position_id': position.id})
        self.chicken.write({'list_price': 2700, 'taxes_id': [Command.set(origin.ids)]})
        self._another()
        self.env['product.pricelist.item'].create({'pricelist_id': shared.id, 'applied_on': '0_product_variant',
            'product_id': self.chicken.id, 'min_quantity': 2, 'compute_price': 'fixed', 'fixed_price': 2500})
        batch = self._summary()
        before = self.env['sale.order'].search_count([])
        daily = self.reservation._lf_daily_orders()
        native = type(self.env['sale.order']).create
        captured = []
        def observe(records, vals):
            captured.extend(vals if isinstance(vals, list) else [vals])
            return native(records, vals)
        with patch.object(type(self.env['sale.order']), 'create', observe):
            batch.with_context(default_website_id=self.website.id).action_prepare()
        self.assertFalse(captured)
        self.assertEqual(self.env['sale.order'].search_count([]), before)
        self.assertEqual(batch.order_id, daily)
        self.assertEqual(batch.order_id.state, 'sale')
        self.assertFalse(batch.order_id.website_id)
        # Los importes son los del pedido diario confirmado al tomar o revisar la lista.
        self.assertEqual(batch.order_id.order_line.filtered(lambda l: l.product_id == self.chicken and l.product_uom_qty).product_uom_qty, 2)

    def test_same_operation_retry_opens_same_order_even_after_cancellation(self):
        batch = self._summary()
        first = batch.action_prepare()
        second = batch.action_prepare()
        self.assertEqual(first, second)
        batch.order_id.state = 'cancel'
        self.assertEqual(batch.action_prepare()['res_id'], first['res_id'])
        again = self._summary()
        self.assertEqual(len(again.snapshot['eligible']), 1)
        self.assertIn('cancelled_order', [row['type'] for row in again.snapshot['issues']])

    def test_overlapping_previews_second_refreshes_without_creating(self):
        first, second = self._summary(), self._summary()
        first.action_prepare()
        before = self.env['sale.order'].search_count([])
        result = second.action_prepare()
        self.assertEqual(result['tag'], 'lf_quotation_reload')
        self.assertFalse(second.order_id)
        self.assertIn('No se creó ninguna cotización', second.notice)
        self.assertEqual(self.env['sale.order'].search_count([]), before)
        self.assertEqual(len(second.snapshot['included']), 1)

    def test_changed_current_choice_reopens_summary_then_prepares_new_choice(self):
        batch = self._summary()
        token = batch.snapshot_token
        self._resolve('replace', product_id=self.pork.id)
        batch.with_context(lf_seen_summary=token).action_prepare()
        self.assertFalse(batch.order_id)
        self.assertEqual(batch.snapshot['products'][0]['id'], self.pork.id)
        batch.action_prepare()
        self.assertEqual(batch.order_id.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty).product_id, self.pork)

    def test_new_request_and_missing_cut_resolved_require_summary_review(self):
        extra = self._another(menu=self.menus[1])
        batch = self._summary()
        self.reservation._request_correction('Consulta recibida después del resumen')
        extra.menu_id.with_user(self.operator).action_take_list()
        batch.action_prepare()
        self.assertFalse(batch.order_id)
        self.assertFalse(batch.snapshot['missing_days'])
        self.assertEqual(len(batch.snapshot['eligible']), 2)

    def test_business_correction_after_preparing_is_flagged_without_sync_or_reinclusion(self):
        batch = self._summary()
        batch.action_prepare()
        original = copy.deepcopy(batch.prepared_snapshot)
        self.assertFalse(batch.order_id.lf_quotation_difference)
        self._resolve('replace', product_id=self.pork.id)
        self.assertIn('reserva cambió', batch.order_id.lf_quotation_difference)
        current = self._summary()
        self.assertFalse(current.snapshot['eligible'])
        self.assertIn('difference', [row['type'] for row in current.snapshot['issues']])
        # El pedido diario se ajusta a la lista vigente; la consulta preparada y el anexo no se reescriben.
        self.assertEqual(batch.order_id.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty).product_id, self.pork)
        self.assertEqual(batch.prepared_snapshot, original)
        self.assertIn('reserva cambió', batch.order_id.lf_quotation_difference)

    def test_removed_link_and_manual_line_changes_are_visible_not_synchronized(self):
        batch = self._summary()
        batch.action_prepare()
        order = batch.order_id
        order.lf_reservation_ids = False
        order.order_line.product_uom_qty = 4
        current = self._summary()
        self.assertEqual(len(current.snapshot['eligible']), 1)  # Historia no es asignación vigente.
        self.assertTrue({'difference', 'order_difference'} <= {r['type'] for r in current.snapshot['issues']})
        self.assertTrue(order.lf_protected)
        self.assertEqual(order.order_line.product_uom_qty, 4)

    def test_period_orders_include_existing_and_cancelled_not_unrelated(self):
        linked = self._sale()
        cancelled = self._sale(state='cancel')
        unrelated = self._sale()
        unrelated.lf_reservation_ids = False
        batch = self._summary()
        daily = self.reservation._lf_daily_orders()
        self.assertEqual(set(batch.action_period_orders()['domain'][0][2]), {linked.id, cancelled.id} | set(daily.ids))

    def test_snapshot_inputs_are_not_writable_and_prepared_parameters_stay_fixed(self):
        batch = self._summary()
        for values in ({'snapshot': {}}, {'operation_key': 'forged'}, {'state': 'prepared'}, {'order_id': False}):
            with self.assertRaises(AccessError):
                batch.write(values)
        batch.action_prepare()
        with self.assertRaises(ValidationError):
            batch.date_to = '2026-10-01'

    def test_operator_only_and_protected_annex_delivery(self):
        batch = self._summary()
        for user in (self.employee, self.private, self.env.ref('base.public_user')):
            self.assertFalse(batch.with_user(user).has_access('read'))
            with self.assertRaises(AccessError):
                batch.with_user(user).action_prepare()
            with self.assertRaises(AccessError):
                self.env['report.kai_viandas.quotation_annex'].with_user(user)._get_report_values(batch.ids)
            with self.assertRaises(AccessError):
                self.env['ir.actions.report'].with_user(user)._render_qweb_html('kai_viandas.report_quotation_annex', batch.ids)
        self.assertTrue(self.env['lafija.access.policy']._is_protected(batch))

    def test_real_annex_pdf_preserves_original_selection_and_contains_no_prices(self):
        self.chicken.list_price = 271828.75
        batch = self._summary()
        batch.action_prepare()
        self._resolve('replace', product_id=self.pork.id)
        action = batch.order_id.action_lf_quotation_annex()
        self.assertEqual(action['report_name'], 'kai_viandas.quotation_annex')
        values = self.env['report.kai_viandas.quotation_annex'].with_user(self.operator)._get_report_values(batch.ids)
        self.assertEqual(values['sheets'][0]['summary']['products'][0]['id'], self.chicken.id)
        pdf, _ = self.env['ir.actions.report'].with_user(self.operator).with_context(force_report_rendering=True)._render_qweb_pdf(
            'kai_viandas.report_quotation_annex', batch.ids)
        self.assertTrue(pdf.startswith(b'%PDF'))
        text = ' '.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        for expected in (self.customer.name, self.reservation.name, 'Pollo', '01/09/2026'):
            self.assertIn(expected, text)
        self.assertNotIn('271828', text)
        self.assertNotIn('271.828', text)
        save_test_file(self._testMethodName, pdf, 'anexo_180_', extension='pdf', directory='reports')
        self.assertEqual(batch.order_id.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty).product_id, self.pork)


@tagged('post_install', '-at_install')
class TestQuotationBrowser180(PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey

    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-10-01 15:00:00', tick=True))
        employee, _ = self._create_employee()
        with freeze_time('2026-09-08 12:00:00'):
            self.record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
                self.website, [(self.menus[0].id, self.product.id)])
        self.menus[0].with_user(self.operator).action_take_list()
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()

    def test_pointer_real_form_summary_prepare_and_native_order(self):
        batch_ids = self.env['lafija.quotation.preparation'].search([]).ids
        action = self.env.ref('kai_viandas.quotation_preparation_action').id
        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector("[name=customer_company_id] input")')
            pointer('[name=customer_company_id] input')
            type_keys(self.customer.name)
            wait('document.querySelector(".o-autocomplete--dropdown-item")')
            pointer('.o-autocomplete--dropdown-item')
            pointer('button[name=action_refresh]')
            wait('document.querySelector(".lf-quotation-summary")')
            self.assertIn(self.record.name, evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            self.assertNotIn('271828', evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            browser.take_screenshot(prefix='lf180_resumen_').result(timeout=10)
            pointer('button[name=action_prepare]')
            wait('document.querySelector("[name=order_line]")')
            self.assertIn('Vianda prueba P1', evaluate('document.querySelector("[name=order_line]").textContent'))
            browser.take_screenshot(prefix='lf180_cotizacion_').result(timeout=10)
        self._employee_pointer_journey(f'/odoo/action-{action}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        batch = self.env['lafija.quotation.preparation'].search([('id', 'not in', batch_ids)])
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch.order_id.state, 'sale')
        self.assertEqual(batch.order_id.order_line.price_unit, 271828.75)
        self.assertEqual(batch.order_id.lf_reservation_ids, self.record.sudo())
        self.assertTrue(batch.order_id.lf_protected)

    def test_pointer_outdated_summary_stops_then_allows_reviewed_choice(self):
        batch = self.env['lafija.quotation.preparation'].with_user(self.operator).create({'customer_company_id': self.customer.id})
        batch.action_refresh()
        product = self.env['product.product'].create({'name': 'Opción corregida 180', 'sale_ok': True})
        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector(".lf-quotation-summary")')
            self.env['lafija.reservation.correction'].with_user(self.operator).create({
                'reservation_id': self.record.id, 'operation': 'replace', 'product_id': product.id,
                'reason': 'Corrección secuencial del fixture con la pantalla ya abierta',
            }).action_apply()
            # HttpCase usa otro Environment: publicar también la revisión pendiente
            # de flush del fixture, igual que al terminar la petición del operador.
            self.env.flush_all()
            pointer('button[name=action_prepare]')
            wait('document.querySelector("[name=notice]")?.textContent.includes("No se creó ninguna")')
            self.assertIn(product.name, evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            self.env.invalidate_all()
            self.assertTrue(batch.snapshot['eligible'], batch.snapshot['issues'])
            self.assertFalse(batch.order_id)
            pointer('button[name=action_prepare]')
            wait('document.querySelector("[name=order_line]")')
        self._employee_pointer_journey(f'/odoo/lafija.quotation.preparation/{batch.id}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        self.assertEqual(batch.order_id.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty).product_id, product)
