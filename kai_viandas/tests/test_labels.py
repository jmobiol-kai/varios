from io import BytesIO

from lxml import html
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import save_test_file
from odoo.tools.pdf import PdfReader

from .test_preparation import PreparationCommon


@tagged("post_install", "-at_install")
class TestLabels(PreparationCommon):
    def _generate(self, revision):
        action = revision.with_user(self.operator).action_print_labels()
        return self.env['lafija.label.print'].browse(action['res_id'])

    def _render_pdf(self, report, records):
        raw, output = self.env['ir.actions.report'].with_user(self.operator).with_context(
            force_report_rendering=True)._render_qweb_pdf(report, records.ids)
        self.assertEqual(output, 'pdf')
        return raw

    def _assert_geometry(self, raw, count, width=83, height=255):
        pages = PdfReader(BytesIO(raw)).pages
        self.assertEqual(len(pages), count)
        for number, page in enumerate(pages, 1):
            with self.subTest(page=number):
                # wkhtmltopdf 0.12.6.1 redondea 29 × 90 mm a 83 × 255 pt.
                # No cambiar por 255 × 83 ni por una rotación de la página PDF.
                self.assertAlmostEqual(float(page.mediabox.width), width, places=2)
                self.assertAlmostEqual(float(page.mediabox.height), height, places=2)
                self.assertEqual(page.get('/Rotate', 0), 0)
        return pages

    def _save_pdf(self, raw, prefix):
        save_test_file(self._testMethodName, raw, prefix, extension='pdf',
                       document_type='Etiquetas PDF de evaluación', directory='reports')

    def test_pdf_preserves_accents_in_employee_company_and_option(self):
        self.customer.name = "Empresa Ñandú ABC"
        self.employee.partner_id.sudo().name = "Juan Pérez"
        self.pork.description_sale = "Cerdo con puré"
        self._resolve("replace", product_id=self.pork.id)
        cut = self._take()
        result = cut.current_revision_id.with_user(self.operator).action_print_labels()
        raw = self.env["lafija.label.print"].browse(result["res_id"]).attachment_id.raw
        text = " ".join(page.extract_text() for page in PdfReader(BytesIO(raw)).pages)
        self.assertIn("Ñandú", text)
        self.assertIn("Pérez", text)
        self.assertIn("puré", text)
        self.assertNotIn("Ã", text)
        self.assertIn('14/09', text)
        self.assertIn(self.reservation.name, text)
        self.assertNotIn('Archivo', text)
        self._assert_geometry(raw, 1)
        self._save_pdf(raw, 'lf1100_acentos_')

    def test_real_pdf_keeps_snapshot_and_replacement_has_separate_evidence(self):
        cut = self._take()
        first = cut.current_revision_id
        result = first.with_user(self.operator).action_print_labels()
        original = self.env["lafija.label.print"].browse(result["res_id"])
        raw = original.attachment_id.raw
        self.assertTrue(raw.startswith(b"%PDF"))
        text = " ".join(page.extract_text() for page in PdfReader(BytesIO(raw)).pages)
        self.assertIn("ABC", text)
        self.assertIn("Juan", text)
        self.assertIn("Pollo", text)
        self.assertNotIn("271828", text)
        self.assertNotIn("271.828", text)
        self.assertFalse(original.handling_ids)
        self.chicken.description_sale = "Descripción distinta de la original"
        self._resolve("replace", product_id=self.pork.id)
        result = cut.current_revision_id.with_user(self.operator).action_print_labels()
        replacement = self.env["lafija.label.print"].browse(result["res_id"])
        self.assertNotEqual(replacement.attachment_id, original.attachment_id)
        self.assertEqual(original.attachment_id.raw, raw)
        self.env["lafija.label.replacement"].with_user(self.operator).create({
            "new_print_id": replacement.id, "old_print_id": original.id,
            "note": "Se coordinó quitar la etiqueta anterior y colocar la nueva.",
        }).action_apply()
        self.assertEqual(replacement.handling_ids.old_print_id, original)
        self.assertEqual(replacement.handling_ids.actor_id, self.operator)
        self.assertEqual(first.line_ids.description, "Pollo")
        self.assertEqual(cut.current_revision_id.line_ids.description, "Cerdo")
        self.assertEqual(self.reservation.state, "active")

    def test_employee_cannot_render_collective_labels_even_with_known_ids(self):
        cut = self._take()
        batch = self._generate(cut.current_revision_id)
        with self.assertRaises(AccessError):
            cut.current_revision_id.with_user(self.employee).action_print_labels()
        with self.assertRaises(AccessError):
            self.env["report.kai_viandas.labels"].with_user(self.employee)._get_report_values(batch.ids)
        with self.assertRaises(AccessError):
            self.env['ir.actions.report'].with_user(self.employee).with_context(
                force_report_rendering=True)._render_qweb_pdf('kai_viandas.report_labels', batch.ids)

    def test_one_portrait_page_per_line_in_single_and_collective_files(self):
        other, _ = self._create_employee('abc-label-second')
        other.partner_id.sudo().name = 'Ana Gómez'
        self.env['lafija.reservation'].with_user(other)._submit_selections(
            self.website, [(self.menu.id, self.pork.id)])
        self.service._submit_selections(self.website, [(self.menus[1].id, self.fish.id)])
        first_cut = self._take()
        action = self.menus[1].with_user(self.operator).action_take_list()
        second_cut = self.env['lafija.preparation.cut'].browse(action['res_id'])
        first = self._generate(first_cut.current_revision_id)
        second = self._generate(second_cut.current_revision_id)
        self._assert_geometry(first.attachment_id.raw, 2)
        self._assert_geometry(second.attachment_id.raw, 1)
        batches = first + second
        lines = first.revision_id.line_ids + second.revision_id.line_ids
        raw = self._render_pdf('kai_viandas.report_labels', batches)
        pages = self._assert_geometry(raw, len(lines))
        for page, line in zip(pages, lines):
            text = ' '.join(page.extract_text().split())
            for expected in (line.date.strftime('%d/%m'), line.company_name,
                             line.employee_name, line.description):
                self.assertIn(expected, text)
            self.assertIn(line.reservation_id.name, text)
            self.assertNotIn('Archivo', text)
        self.assertIn('14/09', pages[0].extract_text())
        self.assertIn('15/09', pages[-1].extract_text())
        self._save_pdf(raw, 'lf1100_colectivas_')

    def test_long_text_uses_pdf_ellipsis_without_truncating_preparation_data(self):
        company = 'Empresa Ñandú de Servicios Alimentarios Integrales del Río de la Plata'
        employee = 'María de los Ángeles Fernández Gutiérrez'
        choice = 'Milanesa de soja con puré mixto y ensalada de estación'
        self.customer.name = company
        self.employee.partner_id.sudo().name = employee
        self.pork.description_sale = choice
        self._resolve('replace', product_id=self.pork.id)
        cut = self._take()
        batch = self._generate(cut.current_revision_id)
        document, _ = self.env['ir.actions.report'].with_user(self.operator)._render_qweb_html(
            'kai_viandas.report_labels', batch.ids)
        tree = html.fromstring(document)
        blocks = tree.xpath('//div[contains(@class, "lf-label-line")]')
        reservation = cut.current_revision_id.line_ids.reservation_id
        self.assertEqual([block.text_content() for block in blocks],
                         ['14/09 · ' + reservation.name + ' · ' + company, employee, choice])
        self.assertFalse(tree.xpath('//html/@data-report-margin-top | //html/@data-report-margin-bottom'))
        line = cut.current_revision_id.line_ids
        self.assertEqual((line.company_name, line.employee_name, line.description), (company, employee, choice))
        pages = self._assert_geometry(batch.attachment_id.raw, 1)
        self.assertIn('14/09', pages[0].extract_text())
        self.assertIn('…', pages[0].extract_text())
        self._save_pdf(batch.attachment_id.raw, 'lf1100_textos_largos_')

    def test_label_paperformat_does_not_change_day_sheet_or_annex_a4(self):
        labels = self.env.ref('kai_viandas.report_labels')
        paper = self.env.ref('kai_viandas.paperformat_vianda_label')
        self.assertEqual(labels.paperformat_id, paper)
        self.assertFalse(paper.default)
        self.assertEqual((paper.format, paper.page_width, paper.page_height, paper.orientation),
                         ('custom', 29, 90, 'Portrait'))
        self.assertEqual((paper.margin_top, paper.margin_bottom, paper.margin_left, paper.margin_right,
                          paper.header_spacing, paper.dpi), (0, 0, 0, 0, 0, 96))
        self.assertFalse(paper.header_line)
        self.assertTrue(paper.disable_shrinking)
        self.assertIn(self.env.ref('kai_viandas.group_operator'), labels.group_ids)
        self.env.company.paperformat_id = self.env.ref('base.paperformat_euro')
        cut = self._take()
        batch = self._generate(cut.current_revision_id)
        self._assert_geometry(batch.attachment_id.raw, 1)
        summary = self.env['lafija.quotation.preparation'].with_user(self.operator).create({
            'customer_company_id': self.customer.id, 'date_from': self.menu.date, 'date_to': self.menu.date})
        summary.action_refresh()
        for xmlid, records in (('kai_viandas.report_day_sheet', cut.current_revision_id),
                               ('kai_viandas.report_quotation_annex', summary)):
            with self.subTest(report=xmlid):
                report = self.env.ref(xmlid)
                self.assertFalse(report.paperformat_id)
                self.assertEqual(report.get_paperformat(), self.env.company.paperformat_id)
                raw = self._render_pdf(xmlid, records)
                self._assert_geometry(raw, 1, width=595, height=842)
                self._save_pdf(raw, 'lf1100_a4_' + xmlid.rsplit('.', 1)[1] + '_')

    def test_preexisting_a4_attachment_is_unchanged_after_new_label_generation(self):
        report = self.env.ref('kai_viandas.report_labels')
        template = self.env.ref('kai_viandas.labels').with_context(lang=None)
        new_arch, new_paper = template.arch_db, report.paperformat_id
        self.env.company.paperformat_id = self.env.ref('base.paperformat_euro')
        # Simular un archivo emitido con la plantilla anterior, sin tocar fuentes
        # ni actualizar datos del demo. La actualización no reescribe sus bytes.
        template.arch_db = '''<t t-name="kai_viandas.labels">
            <html><head><meta charset="utf-8"/></head><body><main>
                <div t-foreach="docs" t-as="batch" class="article page" data-oe-model="lafija.label.print" t-att-data-oe-id="batch.id">
                    <div t-foreach="batch.revision_id.line_ids" t-as="line">
                        <strong t-field="line.company_name"/><br/><strong t-field="line.employee_name"/>
                        <p t-field="line.description"/><small><span t-field="line.date"/> · <span t-field="line.reservation_id.name"/>
                        · R<span t-field="batch.revision_id.number"/> · Archivo <span t-out="batch.id"/></small>
                    </div>
                </div>
            </main></body></html></t>'''
        report.paperformat_id = False
        cut = self._take()
        try:
            original = self._generate(cut.current_revision_id)
        finally:
            template.arch_db = new_arch
            report.paperformat_id = new_paper
        raw = original.attachment_id.raw
        self._assert_geometry(raw, 1, width=595, height=842)
        current = self._generate(cut.current_revision_id)
        self._assert_geometry(current.attachment_id.raw, 1)
        self.assertNotEqual(original.attachment_id, current.attachment_id)
        self.assertEqual(original.attachment_id.raw, raw)
        action = original.with_user(self.operator).action_download()
        self.assertEqual(action['url'], f'/web/content/{original.attachment_id.id}?download=true')
        self.assertFalse(original.handling_ids | current.handling_ids)
