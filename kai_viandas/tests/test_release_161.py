"""Foco útil al seguir escribiendo y confirmación de preparación deliberada."""
from freezegun import freeze_time

from odoo.tests import tagged

from .test_pages import PagesCommon
from .test_release_160 import TestRelease160


@tagged('post_install', '-at_install')
class TestRelease161(PagesCommon):
    _employee = TestRelease160._employee
    _employee_pointer_journey = TestRelease160._employee_pointer_journey

    def setUp(self):
        super().setUp()
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        self.enterContext(freeze_time('2026-09-13 16:00:00', tick=True))

    @staticmethod
    def _key(browser, key, code, number, modifiers=0):
        params = {'key': key, 'code': code, 'windowsVirtualKeyCode': number,
                  'nativeVirtualKeyCode': number, 'modifiers': modifiers}
        for kind in ('keyDown', 'keyUp'):
            # Enter necesita también el carácter para generar keypress y la
            # activación nativa del botón, igual que el teclado físico.
            text = {'text': '\r', 'unmodifiedText': '\r'} if key == 'Enter' and kind == 'keyDown' else {}
            browser._websocket_request('Input.dispatchKeyEvent', params={'type': kind, **params, **text})

    def _resume_consultation(self, width, select_range=False):
        _, service = self._employee()
        record = service._submit_selections(self.website, [(self.menus[0].id, self.product.id)])
        for number in range(4):
            record._post_operational_message(f'Mensaje operativo de prueba {number + 1}. La vianda sigue vigente.', self.operator)
        initial_events = record.sudo().event_ids.ids
        initial_messages = record.sudo().message_ids.ids
        message = 'Necesito ajustar mi vianda'

        def journey(browser, evaluate, wait, pointer, type_keys):
            wait('document.querySelector("#message")')
            pointer('#message')
            type_keys(message)
            for _ in range(6):
                self._key(browser, 'ArrowLeft', 'ArrowLeft', 37)
            if select_range:
                for _ in range(3):
                    self._key(browser, 'ArrowLeft', 'ArrowLeft', 37, modifiers=8)
            selection = evaluate('(()=>{const e=document.querySelector("#message");'
                                 'return [e.selectionStart,e.selectionEnd,e.selectionDirection];})()')
            self.assertEqual(selection[:2], [len(message) - (9 if select_range else 6), len(message) - 6])
            pointer('.header-actions a[href*="ayuda"]')
            wait('document.querySelector("#lf-leave-dialog").open')
            self.assertGreater(evaluate('document.querySelector("#message").getBoundingClientRect().bottom'),
                               evaluate('innerHeight'), 'El caso debe exigir volver a mostrar el campo.')
            pointer('[data-keep-choosing]')
            wait('!document.querySelector("#lf-leave-dialog").open && document.activeElement.id === "message"')
            self.assertEqual(evaluate('document.querySelector("#message").value'), message)
            self.assertEqual(evaluate('(()=>{const e=document.querySelector("#message");'
                                     'return [e.selectionStart,e.selectionEnd,e.selectionDirection];})()'), selection)
            bounds = evaluate('(()=>{const r=document.querySelector("#message").getBoundingClientRect();'
                              'return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:innerWidth,height:innerHeight};})()')
            self.assertEqual(bounds['width'], width)
            self.assertGreaterEqual(bounds['top'], 0)
            self.assertLessEqual(bounds['bottom'], bounds['height'])
            self.assertGreaterEqual(bounds['left'], 0)
            self.assertLessEqual(bounds['right'], bounds['width'])
            browser.take_screenshot(prefix=f'lf161_consulta_foco_{width}_').result(timeout=10)
            # El teclado escribe en el cursor conservado, sin otro clic en el campo.
            type_keys('X')
            self.assertEqual(evaluate('document.querySelector("#message").value'),
                             message[:selection[0]] + 'X' + message[selection[1]:])
            pointer('.header-actions a[href*="ayuda"]')
            pointer('[data-leave-unsaved]')
            wait('location.pathname.endsWith("/ayuda") && document.querySelector(".back-link")')

        self._employee_pointer_journey(f'/my/viandas/{record.id}', journey, width=width)
        self.env.invalidate_all()
        self.assertEqual(record.sudo().event_ids.ids, initial_events)
        self.assertEqual(record.sudo().message_ids.ids, initial_messages)
        self.assertFalse(record.sudo().attention_pending)

    def test_pointer_resume_consultation_focus_cursor_and_viewport_390(self):
        self._resume_consultation(390)

    def test_pointer_resume_consultation_focus_selection_and_viewport_360(self):
        self._resume_consultation(360, select_range=True)

    def test_pointer_preparation_enter_returns_then_tab_enter_confirms(self):
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        menu = self.menus[0]

        def journey(browser, evaluate, wait, pointer, _type):
            browser._websocket_request('Emulation.setDeviceMetricsOverride', params={
                'width': 1366, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
            wait('document.querySelector(".o_form_view button[name=action_take_list]")')
            pointer('.o_form_view button[name="action_take_list"]')
            wait('document.querySelector(".o_dialog .modal-footer .btn-secondary")')
            self.assertEqual(evaluate('document.activeElement.textContent.trim()'), 'Volver')
            self.assertTrue(evaluate('document.activeElement === document.querySelector(".o_dialog .modal-footer .btn-secondary")'))
            self.assertEqual(evaluate('document.querySelector(".o_dialog .modal-footer .btn-primary").textContent.trim()'), 'Tomar lista')
            browser.take_screenshot(prefix='lf161_tomar_lista_foco_volver_').result(timeout=10)
            self._key(browser, 'Enter', 'Enter', 13)
            wait('!document.querySelector(".o_dialog .modal")')
            self.env.invalidate_all()
            self.assertFalse(menu.cut_ids, 'Enter inicial no debe tomar la lista.')
            self.assertIn('Tomar lista para preparación', evaluate('document.querySelector(".o_form_view").textContent'))
            # Sigue siendo posible confirmar con el teclado, de forma deliberada.
            pointer('.o_form_view button[name="action_take_list"]')
            wait('document.activeElement.textContent.trim() === "Volver"')
            self._key(browser, 'Tab', 'Tab', 9)
            wait('document.activeElement.textContent.trim() === "Tomar lista"')
            self._key(browser, 'Enter', 'Enter', 13)
            wait('document.querySelector(".o_field_widget[name=current_revision_id]")')

        self._employee_pointer_journey(f'/odoo/action-kai_viandas.menu_day_action/{menu.id}', journey,
                                       width=1366, login=self.operator.login)
        self.env.invalidate_all()
        self.assertEqual(len(menu.cut_ids), 1)
        self.assertEqual(menu.cut_ids.current_revision_id.number, 1)
