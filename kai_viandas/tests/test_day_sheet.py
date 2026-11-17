from io import BytesIO

from freezegun import freeze_time
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import save_test_file
from odoo.tools.pdf import PdfReader

from .test_preparation import PreparationCommon


@tagged('post_install', '-at_install')
class TestDaySheet(PreparationCommon):
    def test_quantities_use_product_identity_even_when_descriptions_match(self):
        twin = self.env['product.product'].create({
            'name': 'Pollo alternativo', 'description_sale': 'Pollo', 'sale_ok': True,
        })
        self.menu.with_user(self.operator).write({'product_ids': [Command.link(twin.id)]})
        for login, product in (('abc-same-product', self.chicken), ('abc-other-product', twin)):
            employee, _ = self._create_employee(login)
            self.env['lafija.reservation'].with_user(employee)._submit_selections(
                self.website, [(self.menu.id, product.id)])
        cut = self._take()
        sheet = self.env['report.kai_viandas.day_sheet'].with_user(self.operator)._get_report_values(
            cut.current_revision_id.ids)['sheets'][0]
        self.assertEqual(sheet['total'], 3)
        self.assertEqual({p['name']: p['quantity'] for p in sheet['products']},
                         {'Pollo': 2, 'Pollo alternativo': 1})
        self.assertEqual(sum(len(company['lines']) for company in sheet['companies']), 3)

    def test_day_sheet_keeps_current_meals_and_separates_pending_requests(self):
        other, _ = self._create_employee('abc-meal-second')
        self.env['lafija.reservation'].with_user(other)._submit_selections(
            self.website, [(self.menu.id, self.pork.id)])
        cut = self._take()
        first = cut.current_revision_id
        with freeze_time('2026-09-14 13:10:00'):
            self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
            late, _ = self._create_employee('abc-meal-late')
            late_reservation = self.env['lafija.reservation'].with_user(late)._submit_selections(
                self.website, [(self.menu.id, self.chicken.id)])
        self.reservation._request_correction('Consulta privada que no debe imprimirse')
        report = self.env['report.kai_viandas.day_sheet'].with_user(self.operator)
        sheet = report._get_report_values(first.ids)['sheets'][0]
        self.assertEqual(sheet['total'], 2)
        self.assertEqual(sum(p['quantity'] for p in sheet['products']), 2)
        self.assertEqual(len(sheet['pending']), 2)
        details = [line for company in sheet['companies'] for line in company['lines']]
        self.assertNotIn(late_reservation.name, [line['reference'] for line in details])
        self.assertEqual({line['choice'] for line in details}, {'Pollo', 'Cerdo'})
        self.assertIn('Cambio de opción y consulta escrita', [p['type'] for p in sheet['pending']])
        self.assertNotIn('Consulta privada', str(sheet))
        self.assertNotIn('271828', str(sheet))
        self._resolve('accept')
        historical = report._get_report_values(first.ids)['sheets'][0]
        current = report._get_report_values(cut.current_revision_id.ids)['sheets'][0]
        self.assertFalse(historical['current'])
        self.assertTrue(current['current'])
        self.assertEqual(historical['companies'], sheet['companies'])
        self.assertIn('Pescado', [line['choice'] for company in current['companies'] for line in company['lines']])

    def test_day_sheet_pdf_is_real_price_free_and_operator_only(self):
        self.customer.name = 'Empresa Ñandú'
        cut = self._take()
        action = cut.with_user(self.operator).action_print_day_sheet()
        self.assertEqual(action['report_name'], 'kai_viandas.day_sheet')
        pdf, _ = self.env['ir.actions.report'].with_user(self.operator).with_context(force_report_rendering=True)._render_qweb_pdf(
            'kai_viandas.report_day_sheet', cut.current_revision_id.ids)
        self.assertTrue(pdf.startswith(b'%PDF'))
        save_test_file(self._testMethodName, pdf, 'planilla_', extension='pdf',
                       document_type='Planilla PDF de evaluación', directory='reports')
        text = ' '.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn('Ñandú', text)
        self.assertIn('Pollo', text)
        self.assertIn('Cantidades', text)
        self.assertIn(self.reservation.name, text)
        self.assertNotIn('271828', text)
        self.assertNotIn('271.828', text)
        for user in (self.employee, self.env.ref('base.public_user')):
            with self.assertRaises(AccessError):
                cut.with_user(user).action_print_day_sheet()
            with self.assertRaises(AccessError):
                self.env['report.kai_viandas.day_sheet'].with_user(user)._get_report_values(cut.current_revision_id.ids)
