import json
import time
from urllib.parse import urlsplit
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import ChromeBrowser

from .test_pages import PagesCommon


@tagged('post_install', '-at_install')
class TestHomeEntry(PagesCommon):
    def _assert_denial_with_exits(self, response):
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn('No se puede abrir esta página con este acceso', response.text)
        self.assertIn('/web/session/logout?redirect=/web/login', response.text)
        self.assertIn('Ir al sitio público', response.text)
        self.assertNotIn('lf-week-form', response.text)
        self.assertNotIn('271828', response.text)

    def test_authorized_corporate_root_redirects_only_to_own_week(self):
        employee, _ = self._create_employee()
        self._real_login(employee.login, 'employee-password-123')
        for path in ('/', '/?redirect=/shop', '/my'):
            response = self.url_open(path, allow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['Location'], '/my/viandas')
        page = self.url_open('/')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(urlsplit(page.url).path, '/my/viandas')
        self.assertIn('lf-week-form', page.text)
        self.assertTrue(page.content.lstrip().lower().startswith(b'<!doctype html>'))
        for path in ('/shop', '/website/search', f'/web/image/product.product/{self.product.id}/image_1920'):
            self._assert_denial_with_exits(self.url_open(path))
        # El acceso por raíz no amplía los métodos ni acepta un destino enviado
        # por el navegador. Mantiene también la frontera del sitio público.
        self.assertEqual(self.url_open('/', data={'probe': 'root-post'}).status_code, 403)
        cookie = self.opener.cookies.get('session_id', domain=urlsplit(self.base_url()).hostname, path='/')
        self.opener.cookies.set('session_id', cookie, domain='public.test')
        self._assert_denial_with_exits(self.url_open('/', headers={'Host': 'public.test'}))

    def test_anonymous_corporate_root_still_redirects_to_login(self):
        self._anonymous()
        response = self.url_open('/', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['Location'], '/web/login')
        page = self.url_open('/')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(urlsplit(page.url).path, '/web/login')
        self.assertIn('Entrá a tus viandas', page.text)
        self.assertNotIn('lf-week-form', page.text)

    def test_public_home_remains_native_for_visitor_and_private_customer(self):
        for user in (None, self.private):
            if user:
                self.authenticate(user.login, 'fixture')
                self.opener.cookies.set('session_id', self.session.sid, domain='public.test')
            else:
                self._anonymous()
            response = self.url_open('/', headers={'Host': 'public.test'}, allow_redirects=False)
            with patch.object(type(self.env['ir.http']), '_lf_guard', return_value=None):
                native = self.url_open('/', headers={'Host': 'public.test'}, allow_redirects=False)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.status_code, native.status_code)
            self.assertEqual(response.headers['Content-Type'], native.headers['Content-Type'])
            self.assertNotIn('lf-week-form', response.text)
            self.assertIn('id="wrapwrap"', response.text)
            self.assertNotIn('No se puede abrir esta página', response.text)

    def test_operator_and_internal_keep_public_home_backend_and_corporate_denial(self):
        internal = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Interno para entrada por raíz', 'login': 'lf-home-internal',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        for user in (self.operator, internal):
            with self.subTest(user=user.login):
                self.authenticate(user.login, 'fixture')
                self.opener.cookies.set('session_id', self.session.sid, domain='public.test')
                response = self.url_open('/', headers={'Host': 'public.test'}, allow_redirects=False)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('lf-week-form', response.text)
                # Conserva la cadena actual: raíz -> login -> página privada
                # denegada; ser interno no convierte la cuenta en empleado.
                self._assert_denial_with_exits(self.url_open('/'))
                for headers in ({}, {'Host': 'public.test'}):
                    session = self.url_open('/web/session/get_session_info', headers=headers,
                        json={'jsonrpc': '2.0', 'id': 1, 'params': {}})
                    self.assertEqual(session.status_code, 200)
                    self.assertEqual(session.json()['result']['uid'], user.id)

    def test_noncorporate_portal_account_keeps_denial_with_exits(self):
        self.assertFalse(self.private.website_id)
        self.assertFalse(self.private._lf_is_corporate_subject())
        self.authenticate(self.private.login, 'fixture')
        self._assert_denial_with_exits(self.url_open('/'))
        self._assert_denial_with_exits(self.url_open('/my/viandas'))

    def test_browser_login_then_bookmark_root_opens_week_in_standards_mode(self):
        employee, _ = self._create_employee()
        self._anonymous()
        sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
        original = ChromeBrowser._wait_code_ok

        def login_and_root(browser, code, timeout, **kwargs):
            def evaluate(expression):
                return browser._websocket_request('Runtime.evaluate', params={
                    'expression': expression, 'returnByValue': True}).get('result', {}).get('value')

            def wait(expression):
                for _ in range(200):
                    if evaluate(expression):
                        return
                    time.sleep(.05)
                self.fail('No se cumplió al navegar: ' + expression)

            def pointer(selector):
                target = 'document.querySelector(' + json.dumps(selector) + ')'
                evaluate(target + '.scrollIntoView({block:"center"})')
                time.sleep(.1)
                point = evaluate('(()=>{const e=' + target + ';const r=e.getBoundingClientRect();'
                    'const x=r.x+r.width/2,y=r.y+r.height/2;return {x,y,clear:e.contains(document.elementFromPoint(x,y))};})()')
                self.assertTrue(point['clear'], selector + ' está tapado')
                for kind in ('mousePressed', 'mouseReleased'):
                    browser._websocket_request('Input.dispatchMouseEvent', params={
                        'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1})

            def type_keys(selector, text):
                pointer(selector)
                for char in text:
                    browser._websocket_request('Input.dispatchKeyEvent', params={'type': 'keyDown', 'key': char, 'text': char})
                    browser._websocket_request('Input.dispatchKeyEvent', params={'type': 'keyUp', 'key': char})

            browser._websocket_request('Emulation.setDeviceMetricsOverride', params={
                'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': False})
            wait('document.readyState==="complete" && !!document.querySelector("#lf_login")')
            type_keys('#lf_login', employee.login)
            type_keys('#lf_password', 'employee-password-123')
            pointer('.login button[type=submit]')
            wait('location.pathname==="/my/viandas" && document.readyState==="complete" && !!document.querySelector("#lf-week-form")')
            evaluate('window.lfBeforeRoot=true')
            browser._websocket_request('Page.navigate', params={'url': self.base_url() + '/'})
            wait('!window.lfBeforeRoot && location.pathname==="/my/viandas" && document.readyState==="complete" && !!document.querySelector("#lf-week-form")')
            self.assertEqual(evaluate('document.compatMode'), 'CSS1Compat')
            self.assertTrue(evaluate('!!document.doctype && document.doctype.name.toLowerCase()==="html"'))
            self.assertTrue(evaluate('document.documentElement.scrollWidth<=innerWidth'))
            self.assertEqual(evaluate('innerWidth'), 390)
            browser.take_screenshot(prefix='raiz_corporativa_390_').result(timeout=10)
            return original(browser, code, timeout, **kwargs)

        with patch.object(ChromeBrowser, '_wait_code_ok', login_and_root):
            self.browser_js('/web/login', "console.log('test successful');", login=None,
                            cookies={'session_id': sid}, timeout=90)
        self.assertFalse(self.env['lafija.reservation'].search([('employee_partner_id', '=', employee.partner_id.id)]),
                         'Entrar por la raíz no crea reservas')
