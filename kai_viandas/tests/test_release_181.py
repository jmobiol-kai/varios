"""Presentación del resumen y entrada de fechas con el cliente web real."""
import copy
import json
import logging
import time
from datetime import date
from io import BytesIO

from freezegun import freeze_time
from lxml import etree, html
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged
from odoo.tests.common import save_test_file
from odoo.tools.pdf import PdfReader

from .test_pages import PagesCommon
from .test_preparation import PreparationCommon
from .test_release_160 import TestRelease160
from .test_release_180 import TestQuotation180

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestQuotation181(PreparationCommon):
    _summary = TestQuotation180._summary
    _another = TestQuotation180._another
    _sale = TestQuotation180._sale

    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-10-01 15:00:00', tick=True))
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.cut = self._take()
        self.model = self.env['lafija.quotation.preparation'].with_user(self.operator)

    def _text(self, batch):
        return ' '.join(html.fromstring(str(batch.summary_html)).text_content().split())

    def _pdf(self, batch, prefix):
        pdf, _ = self.env['ir.actions.report'].with_user(self.operator).with_context(force_report_rendering=True)._render_qweb_pdf(
            'kai_viandas.report_quotation_annex', batch.ids)
        self.assertTrue(pdf.startswith(b'%PDF'))
        save_test_file(self._testMethodName, pdf, prefix, extension='pdf', directory='reports')
        return pdf, ' '.join(' '.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages).split())

    def test_form_parameter_changes_invalidate_only_the_unsaved_consultation(self):
        other_customer = self.env['res.partner'].create({'name': 'Otra empresa 181', 'is_company': True})
        other_seller = self.env['res.company'].create({'name': 'Otra compañía 181'})
        self.operator.company_ids |= other_seller
        self.operator.group_ids |= self.env.ref('base.group_multi_company')
        self.model = self.model.with_context(allowed_company_ids=[self.env.company.id, other_seller.id])
        for field_name, value in [('date_from', date(2026, 9, 2)), ('date_to', date(2026, 9, 29)),
                                  ('customer_company_id', other_customer), ('company_id', other_seller)]:
            with self.subTest(field=field_name):
                batch = self._summary()
                before = copy.deepcopy(batch.snapshot)
                form = Form(batch, view='kai_viandas.quotation_preparation_form')
                setattr(form, field_name, value)
                self.assertEqual(form.state, 'draft')
                self.assertFalse(form.snapshot_token)
                self.assertFalse(form.summary_html)
                self.assertFalse(form.has_available)
                # Onchange no borra la consulta persistida antes de guardar.
                self.assertEqual(batch.snapshot, before)
                form.save()
                self.assertFalse(batch.snapshot)
                self.assertEqual(batch.state, 'draft')
                self.assertFalse(batch.order_id)
                batch.action_refresh()
                self.assertEqual(batch.state, 'review')
                self.assertTrue(batch.snapshot)

    def test_direct_prepare_after_parameter_write_refreshes_without_order(self):
        batch = self._summary()
        before = self.env['sale.order'].search_count([])
        batch.write({'date_from': '2026-09-15'})
        action = batch.action_prepare()
        self.assertEqual(action['tag'], 'lf_quotation_reload')
        self.assertEqual(batch.snapshot['date_from'], '2026-09-15')
        self.assertFalse(batch.has_available)
        self.assertFalse(batch.order_id)
        self.assertEqual(self.env['sale.order'].search_count([]), before)

    def test_empty_result_does_not_offer_prepare_but_direct_calls_still_rejected(self):
        batch = self._summary(date_from='2026-08-01', date_to='2026-08-31')
        self.assertFalse(batch.has_available)
        self.assertIn('No hay viandas disponibles', self._text(batch))
        before = self.env['sale.order'].search_count([])
        with self.assertRaises(UserError):
            batch.action_prepare()
        with self.assertRaises(AccessError):
            batch.write({'has_available': True})
        self.assertFalse(batch.order_id)
        self.assertEqual(self.env['sale.order'].search_count([]), before)

    def test_saved_consultation_refresh_and_retry_keep_original_and_issued_pdf(self):
        batch = self._summary()
        batch.action_prepare()
        original = copy.deepcopy(batch.prepared_snapshot)
        order = batch.order_id
        for text in ('Consulta guardada del', 'Disponibles en esa consulta · 1 vianda', 'Ya incluidas en esa consulta · 0 reservas'):
            self.assertIn(text, self._text(batch))
        self.assertNotIn('Este resumen actualizado', self._text(batch))
        pdf, _ = self._pdf(batch, 'lf181_anexo_original_')
        attachment = self.env['ir.attachment'].create({
            'name': 'Anexo emitido 181.pdf', 'raw': pdf, 'res_model': batch._name, 'res_id': batch.id})
        batch.action_refresh()
        self.assertIn('Disponibles en esa consulta · 0 viandas', self._text(batch))
        self.assertIn('Ya incluidas en esa consulta · 1 reserva', self._text(batch))
        self.assertEqual(batch.prepared_snapshot, original)
        values = self.env['report.kai_viandas.quotation_annex'].with_user(self.operator)._get_report_values(batch.ids)
        self.assertEqual(values['sheets'][0]['summary'], original)
        self.assertEqual(batch.action_prepare()['res_id'], order.id)
        self.assertEqual(attachment.raw, pdf)
        self.assertFalse(order.invoice_ids)

    def test_period_order_view_keeps_native_actions_and_all_four_order_states(self):
        orders = self.env['sale.order']
        for state in ('draft', 'sent', 'sale', 'cancel'):
            orders |= self._sale(state=state)
        batch = self._summary()
        action = batch.action_period_orders()
        daily = self.reservation._lf_daily_orders()
        self.assertEqual(set(action['domain'][0][2]), set(orders.ids) | set(daily.ids))
        self.assertEqual(set(orders.mapped('state')), {'draft', 'sent', 'sale', 'cancel'})
        self.assertEqual(action['views'][0], (self.env.ref('sale.view_quotation_tree').id, 'list'))
        view = orders.with_user(self.operator).get_view(action['views'][0][0], 'list')
        arch = etree.fromstring(view['arch'])
        self.assertEqual(arch.xpath('//field[@name="state"]/@optional'), ['show'])
        self.assertEqual(arch.xpath('//field[@name="invoice_status"]/@optional'), ['hide'])
        invoice_action = str(self.env.ref('sale.action_view_sale_advance_payment_inv').id)
        self.assertTrue(arch.xpath('//header/button[@type="action" and @name=$name]', name=invoice_action))
        self.assertEqual(self.model._fields['state'].string, 'Estado')

    def test_summary_pluralization_uses_real_available_included_and_missing_days(self):
        batch = self._summary()
        self.assertIn('Disponibles para preparar · 1 vianda', self._text(batch))
        self._another('lf181-segundo')
        batch.action_refresh()
        self.assertIn('Disponibles para preparar · 2 viandas', self._text(batch))
        self._sale()
        batch.action_refresh()
        self.assertIn('Ya incluidas en un pedido · 1 reserva', self._text(batch))
        self._another('lf181-sin-lista', menu=self.menus[1])
        batch.action_refresh()
        self.assertIn('ABC de prueba: 1 vianda', self._text(batch))
        self._another('lf181-sin-lista-dos', menu=self.menus[1])
        batch.action_refresh()
        self.assertIn('ABC de prueba: 2 viandas', self._text(batch))
        self.assertNotIn('1 viandas', self._text(batch))
        self.assertNotIn('1 reservas', self._text(batch))

    def test_empty_pdf_explains_query_without_changing_headers_or_quantities(self):
        batch = self._summary(date_from='2026-08-01', date_to='2026-08-31')
        _, text = self._pdf(batch, 'lf181_anexo_vacio_')
        for expected in (self.customer.name, '01/08/2026', '31/08/2026', 'Resumen sin cotización preparada',
                         'No hay viandas disponibles en esta consulta. Las ya incluidas y las incidencias se revisan en el resumen.',
                         '0 viandas'):
            self.assertIn(expected, text)
        self.assertFalse(batch.order_id)
        self.assertFalse(batch.snapshot['eligible'])

    def test_one_and_two_viandas_in_report_and_real_pdf(self):
        for count in (1, 2):
            if count == 2:
                self._another('lf181-pdf-dos')
            batch = self._summary()
            values = self.env['report.kai_viandas.quotation_annex'].with_user(self.operator)._get_report_values(batch.ids)
            self.assertEqual(len(values['sheets'][0]['summary']['eligible']), count)
            _, text = self._pdf(batch, f'lf181_anexo_{count}_')
            self.assertIn(f'Detalle por empleado y fecha · {count} ' + ('vianda' if count == 1 else 'viandas'), text)
            self.assertNotIn('1 viandas', text)


@tagged('post_install', '-at_install')
class TestQuotationBrowser181(PagesCommon):
    _employee_pointer_journey = TestRelease160._employee_pointer_journey

    def setUp(self):
        super().setUp()
        self.enterContext(freeze_time('2026-10-01 15:00:00', tick=True))
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.env['res.lang']._activate_lang('es_AR')
        self.operator.lang = 'es_AR'
        employee, _ = self._create_employee()
        with freeze_time('2026-09-08 12:00:00'):
            self.record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
                self.website, [(self.menus[0].id, self.product.id)])
        self.menus[0].with_user(self.operator).action_take_list()
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()

    @staticmethod
    def _key(browser, key, code=None, modifiers=0):
        params = {'key': key, 'modifiers': modifiers}
        if code:
            params.update(code=code, windowsVirtualKeyCode={'Tab': 9, 'Enter': 13, 'Escape': 27}.get(code, 0))
        for kind in ('keyDown', 'keyUp'):
            browser._websocket_request('Input.dispatchKeyEvent', params={'type': kind, **params})

    def test_pointer_dates_do_not_overlap_and_keyboard_entry_matches_native(self):
        batch = self.env['lafija.quotation.preparation'].with_user(self.operator).create({
            'customer_company_id': self.customer.id, 'date_from': '2026-08-01', 'date_to': '2026-08-31'})
        native = self.env['sale.order'].with_user(self.operator).create({
            'partner_id': self.customer.id, 'validity_date': '2026-08-31', 'date_order': '2026-08-01 15:00:00'})
        readings = []
        def journey(browser, evaluate, wait, pointer, type_keys):
            def read(label, first, second):
                data = evaluate('''(()=>{const info=n=>{const e=document.querySelector('[name="'+n+'"]');
                    return {text:e?.innerText, value:e?.querySelector('input')?.value}};
                    return {active:{tag:document.activeElement?.tagName, field:document.activeElement?.dataset.field,
                    role:document.activeElement?.getAttribute('role')}, first:info(%s), second:info(%s),
                    picker:document.querySelector('.o_datetime_picker')?.innerText};})()''' % (json.dumps(first), json.dumps(second)))
                readings.append({'label': label, **data})
                _logger.info('LAFIJA_181_DATE_STEP %s', json.dumps(readings[-1], ensure_ascii=False))
            def click_uncovered_field(selector):
                # El calendario abierto no debe interceptar el centro del campo.
                point = evaluate('''(()=>{const e=document.querySelector(%s), r=e.getBoundingClientRect();
                    const x=r.x+r.width/2,y=r.y+r.height/2;
                    const hit=document.elementFromPoint(x,y);
                    return {x,y,clear:e.contains(hit),hit:hit?.tagName};})()''' % json.dumps(selector))
                _logger.info('LAFIJA_181_DATE_HIT %s', json.dumps(point, ensure_ascii=False))
                self.assertTrue(point['clear'], selector)
                for kind in ('mousePressed', 'mouseReleased'):
                    browser._websocket_request('Input.dispatchMouseEvent', params={
                        'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1})
                time.sleep(.25)
            def type_date(field, text):
                pointer(f'[name="{field}"] .o_input')
                wait(f'document.querySelector("[name={field}] input") === document.activeElement')
                self._key(browser, 'a', modifiers=2)
                type_keys(text)
            wait('document.querySelector("[name=date_from]")')
            type_date('date_from', '01/09/2026')
            read('lafija: mientras escribe', 'date_from', 'date_to')
            browser.take_screenshot(prefix='lf181_calendario_abierto_').result(timeout=10)
            click_uncovered_field('[name=date_to] .o_input')
            wait('document.activeElement?.dataset.field === "date_to"')
            read('lafija: primer clic Hasta', 'date_from', 'date_to')
            browser.take_screenshot(prefix='lf181_fecha_primer_clic_').result(timeout=10)
            # Cerrar el segundo calendario antes de volver al primero.
            self._key(browser, 'Escape', 'Escape')
            wait('!document.querySelector(".o_datetime_picker")')
            # Completar con Enter permite cerrar y aplicar antes de cambiar de campo.
            type_date('date_from', '01/09/2026')
            self._key(browser, 'Enter', 'Enter')
            wait('!document.querySelector(".o_datetime_picker")')
            type_date('date_to', '30/09/2026')
            self._key(browser, 'Tab', 'Tab')
            wait('!document.querySelector(".o_datetime_picker")')
            read('lafija: Enter y Tab', 'date_from', 'date_to')
            pointer('button[name=action_refresh]')
            wait('document.querySelector(".lf-quotation-summary")')
            self.assertIn('01/09/2026', evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            self.assertIn('30/09/2026', evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            browser._websocket_request('Page.navigate', params={'url': self.base_url()+f'/odoo/sale.order/{native.id}'})
            wait('document.querySelector("[name=validity_date]")')
            type_date('validity_date', '30/09/2026')
            read('nativo: mientras escribe', 'validity_date', 'partner_id')
            click_uncovered_field('[name=partner_id] input')
            read('nativo: primer clic Cliente', 'validity_date', 'partner_id')
            browser.take_screenshot(prefix='lf181_fecha_nativa_').result(timeout=10)
            _logger.info('LAFIJA_181_DATE_DIAGNOSTIC %s', json.dumps(readings, ensure_ascii=False))
            self._key(browser, 'Escape', 'Escape')
            pointer('button.o_form_button_save')
            wait('document.querySelector(".o_form_status_indicator_buttons")?.classList.contains("invisible")')
        self._employee_pointer_journey(f'/odoo/lafija.quotation.preparation/{batch.id}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        self.assertEqual((batch.date_from, batch.date_to), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(native.validity_date, date(2026, 9, 30))

    def test_pointer_changed_period_requires_recalculation_and_empty_hides_prepare(self):
        batch = self.env['lafija.quotation.preparation'].with_user(self.operator).create({'customer_company_id': self.customer.id})
        batch.action_refresh()
        before = self.env['sale.order'].search_count([])
        def journey(browser, evaluate, wait, pointer, type_keys):
            def set_date(field, value):
                pointer(f'[name={field}] .o_input')
                wait(f'document.activeElement?.dataset.field === "{field}"')
                self._key(browser, 'a', modifiers=2)
                type_keys(value)
                self._key(browser, 'Enter', 'Enter')
                wait('!document.querySelector(".o_datetime_picker")')
            wait('document.querySelector("button[name=action_prepare]")')
            self.assertIn('30/09/2026', evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            set_date('date_to', '29/09/2026')
            wait('!document.querySelector(".lf-quotation-summary") && !document.querySelector("button[name=action_prepare]")')
            self.assertEqual(evaluate('document.querySelector("button[name=action_refresh]").textContent.trim()'), 'Ver resumen')
            self.assertIn('29/09/2026', evaluate('document.querySelector("[name=date_to]").innerText'))
            browser.take_screenshot(prefix='lf181_periodo_sin_resumen_').result(timeout=10)
            pointer('button[name=action_refresh]')
            wait('document.querySelector("button[name=action_prepare]")')
            self.assertIn('29/09/2026', evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            set_date('date_from', '16/09/2026')
            wait('!document.querySelector("button[name=action_prepare]")')
            pointer('button[name=action_refresh]')
            wait('document.querySelector(".lf-quotation-summary")?.textContent.includes("No hay viandas disponibles")')
            self.assertFalse(evaluate('Boolean(document.querySelector("button[name=action_prepare]"))'))
            browser.take_screenshot(prefix='lf181_resumen_vacio_').result(timeout=10)
        self._employee_pointer_journey(f'/odoo/lafija.quotation.preparation/{batch.id}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        self.assertEqual((batch.date_from, batch.date_to), (date(2026, 9, 16), date(2026, 9, 29)))
        self.assertEqual(batch.state, 'review')
        self.assertFalse(batch.has_available)
        self.assertFalse(batch.order_id)
        self.assertEqual(self.env['sale.order'].search_count([]), before)

    def test_pointer_saved_consultation_starts_with_order_and_notice(self):
        batch = self.env['lafija.quotation.preparation'].with_user(self.operator).create({'customer_company_id': self.customer.id})
        batch.action_refresh()
        batch.action_prepare()
        before = copy.deepcopy(batch.prepared_snapshot)
        reviewed_at = batch.reviewed_at
        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector(".lf-quotation-summary")')
            self.assertIn('Consulta guardada del', evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            self.assertIn('Disponibles en esa consulta', evaluate('document.querySelector(".lf-quotation-summary").textContent'))
            self.assertIn(batch.order_id.name, evaluate('document.querySelector("[name=order_id]").innerText'))
            self.assertTrue(evaluate('''(()=>{const order=document.querySelector('[name=order_id]'),
                notice=document.querySelector('.lf-saved-consultation-notice'), summary=document.querySelector('.lf-quotation-summary');
                return order.getBoundingClientRect().bottom <= notice.getBoundingClientRect().top
                    && notice.getBoundingClientRect().bottom < summary.getBoundingClientRect().top;})()'''))
            self.assertIn('Actualizar resumen', evaluate('document.querySelector(".lf-saved-consultation-notice").textContent'))
            browser.take_screenshot(prefix='lf181_consulta_guardada_').result(timeout=10)
            pointer('button[name=action_open_order]')
            wait('document.querySelector("[name=order_line]")')
            self.assertIn(batch.order_id.name, evaluate('document.querySelector(".o_form_view").innerText'))
        self._employee_pointer_journey(f'/odoo/lafija.quotation.preparation/{batch.id}', journey, width=1366, login=self.operator.login)
        self.env.invalidate_all()
        self.assertEqual(batch.prepared_snapshot, before)
        self.assertEqual(batch.reviewed_at, reviewed_at)

    def test_pointer_period_orders_show_each_native_order_state(self):
        orders = self.env['sale.order']
        for state in ('draft', 'sent', 'sale', 'cancel'):
            orders |= self.env['sale.order'].with_user(self.operator).create({
                'partner_id': self.customer.id, 'state': state,
                'lf_reservation_ids': [Command.set(self.record.ids)],
                'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 1})]})
        batch = self.env['lafija.quotation.preparation'].with_user(self.operator).create({'customer_company_id': self.customer.id})
        batch.action_refresh()
        states = dict(orders._fields['state']._description_selection(orders.with_context(lang='es_AR').env))
        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector("button[name=action_period_orders]")')
            pointer('button[name=action_period_orders]')
            wait('document.querySelector(".o_list_renderer th[data-name=state]")')
            text = evaluate('document.querySelector(".o_list_renderer").innerText')
            for order in orders:
                self.assertIn(order.name, text)
                self.assertIn(states[order.state], text)
            self.assertFalse(evaluate('Boolean(document.querySelector(".o_list_renderer th[data-name=invoice_status]"))'))
            browser.take_screenshot(prefix='lf181_estados_del_periodo_').result(timeout=10)
        self._employee_pointer_journey(f'/odoo/lafija.quotation.preparation/{batch.id}', journey, width=1366, login=self.operator.login)
