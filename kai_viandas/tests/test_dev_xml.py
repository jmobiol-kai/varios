"""La misma lectura de vistas que utiliza el servidor con --dev xml/all."""
from pathlib import Path
from unittest.mock import patch

from lxml import etree

from odoo.addons.base.models.ir_ui_view import get_view_arch_from_file
from odoo.tests import tagged
from odoo.tools import config

from .test_identity import LafijaCommon


@tagged('post_install', '-at_install')
class TestDevelopmentViews(LafijaCommon):
    def test_every_module_view_and_template_is_readable_from_file(self):
        root = Path(__file__).resolve().parents[1]
        records = templates = 0
        for path in sorted(root.rglob('*.xml')):
            if 'static' in path.relative_to(root).parts:
                continue
            document = etree.parse(str(path))
            for node in document.xpath('//record[@model="ir.ui.view"] | //template'):
                xmlid = 'kai_viandas.' + node.get('id')
                with self.subTest(xmlid=xmlid, path=str(path)):
                    if node.tag == 'record':
                        records += 1
                        field = node.find('field[@name="arch"]')
                        if field is not None:
                            self.assertTrue(field.text, 'Separar arch y su primer hijo con un salto de línea')
                    else:
                        templates += 1
                    arch = get_view_arch_from_file(str(path), xmlid)
                    self.assertTrue(arch, xmlid)
                    etree.fromstring(arch.encode())
        self.assertGreaterEqual(records, 25)
        self.assertGreater(templates, 0)

    def test_combined_get_views_with_dev_xml_as_operator(self):
        # No se crea ni se valida ningún documento comercial. Se comprueba
        # el resultado combinado, incluidas nuestras pestañas heredadas.
        cases = [
            ('sale.order', 'sale.view_order_form', 'form', 'lf_reservation_ids'),
            ('account.move', 'account.view_move_form', 'form', 'lf_reservation_ids'),
            ('lafija.menu.day', 'kai_viandas.menu_day_form', 'form', 'product_ids'),
            ('lafija.reservation', 'kai_viandas.reservation_form', 'form', 'attention_label'),
            ('lafija.preparation.cut', 'kai_viandas.cut_form', 'form', 'current_revision_id'),
            ('lafija.label.print', 'kai_viandas.label_print_form', 'form', 'handling_ids'),
            ('lafija.reservation.event', 'kai_viandas.reservation_event_form', 'form', 'result_label'),
        ]
        try:
            with patch.dict(config.options, {'dev_mode': ['xml']}):
                self.env.registry.clear_cache()
                for model, xmlid, mode, field in cases:
                    with self.subTest(model=model):
                        values = self.env[model].with_user(self.operator).get_views(
                            [(self.env.ref(xmlid).id, mode)], {'toolbar': True})
                        arch = etree.fromstring(values['views'][mode]['arch'].encode())
                        self.assertTrue(arch.xpath(f'//field[@name="{field}"]'))
        finally:
            self.env.registry.clear_cache()
