"""Marca configurable, ayuda por rol y navegación sin alterar las reservas."""
import base64
import json
import time
from io import BytesIO
from unittest.mock import patch

from freezegun import freeze_time
from lxml import html
from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import ChromeBrowser

from ..models.branding import logo_payload
from ..models.portal_resources import resource_url
from ..models.time_utils import business_today
from .test_identity import LafijaCommon
from .test_pages import PagesCommon
from .test_release_140 import TestConflict140
from .test_ux_round2 import TestUXRound2


def configured_logo(color='#E0DBCF', white_edge=False):
    im = Image.new('RGB', (344, 146), color)
    if white_edge:
        im.paste('white', (0, 0, 344, 3))
    out = BytesIO()
    im.save(out, format='PNG')
    return base64.b64encode(out.getvalue())


@tagged('post_install', '-at_install')
class TestBrand150(LafijaCommon):
    def test_logo_cache_fingerprint_white_edge_and_config_change(self):
        original = configured_logo(white_edge=True)
        payload = logo_payload(original)
        self.assertEqual(payload[0], base64.b64decode(original), 'No se edita el logo configurado')
        self.assertAlmostEqual(payload[3], 100 * 3 / 146, places=4)
        self.assertIs(payload, logo_payload(original))
        self.assertNotEqual(payload[2], logo_payload(configured_logo('#414141'))[2])
        self.assertFalse(self.website._lf_logo(), 'El logo genérico se sustituye por texto')
        self.website.logo = original
        self.assertEqual(self.website._lf_logo(), payload)
        self.website.logo = False
        self.assertFalse(self.website._lf_logo())

    def test_logo_supports_svg_without_active_content_or_arbitrary_files(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40"><path d="M0 0h80v40H0z" fill="#414141"/></svg>'
        self.assertEqual(logo_payload(base64.b64encode(svg))[1], 'image/svg+xml')
        for content in [b'not an image', svg.replace(b'<path', b'<script/><path'),
                        svg.replace(b'<path', b'<image href="https://example.test/logo"/><path'),
                        svg.replace(b'<path', b'<path onload="alert(1)"'),
                        b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + svg]:
            self.assertIsNone(logo_payload(base64.b64encode(content)))
        with patch.object(Image, 'MAX_IMAGE_PIXELS', 100):
            self.assertIsNone(logo_payload(configured_logo('#FEFEFD')),
                              'Una imagen excesiva usa el texto de marca; no rompe el acceso')

    def test_operator_manual_is_read_only_and_not_available_to_other_roles(self):
        record = self.env.ref('kai_viandas.operator_help')
        self.assertIn('La rutina del día', record.with_user(self.operator).read(['content'])[0]['content'])
        employee, _ = self._create_employee()
        internal = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Interno sin rol La Fija', 'login': 'lf-help-internal',
            'group_ids': [Command.set(self.env.ref('base.group_user').ids)],
        })
        for user in (employee, self.private, internal):
            with self.assertRaises(AccessError):
                record.with_user(user).read(['content'])
        with self.assertRaises(AccessError):
            record.with_user(self.operator).write({'name': 'Editado'})


@tagged('post_install', '-at_install')
class TestPages150(PagesCommon):
    _pointer_browser = TestUXRound2._pointer_browser
    _setup_pending = TestConflict140._setup_pending
    _operator_replace = TestConflict140._operator_replace
    _page = TestConflict140._page
    _post_data = TestConflict140._post_data

    def test_logo_public_route_is_host_bound_fingerprinted_and_conditional(self):
        self.website.logo = configured_logo(white_edge=True)
        self._anonymous()
        login = self.url_open('/web/login')
        tree = html.fromstring(login.content)
        url = tree.xpath('//header//img/@src')[0]
        self.assertIn('clip-path:inset(calc(2.0548%', tree.xpath('//header//img/@style')[0])
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, base64.b64decode(self.website.logo))
        self.assertIn('immutable', response.headers['Cache-Control'])
        self.assertIn('sandbox', response.headers['Content-Security-Policy'])
        self.assertEqual(self.url_open(url, headers={'If-None-Match': response.headers['ETag']}).status_code, 304)
        self.assertEqual(self.url_open(url, headers={'Host': 'public.test'}).status_code, 404)
        self.website.logo = configured_logo('#414141')
        new_url = html.fromstring(self.url_open('/web/login').content).xpath('//header//img/@src')[0]
        self.assertNotEqual(new_url, url)
        self.assertEqual(self.url_open(url).status_code, 404)
        self.assertEqual(self.url_open(new_url).status_code, 200)
        self.assertEqual(self.url_open('/web/image/website/%s/logo' % self.website.id).status_code, 403)

    def test_help_access_matrix_does_not_expand_the_corporate_allowlist(self):
        self._anonymous()
        response = self.url_open('/viandas/ayuda-acceso')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Mis viandas</h1>', response.text)
        self.assertNotIn('ABC de prueba', response.text)
        self.assertFalse(html.fromstring(response.content).xpath('//nav[@aria-label="Semanas"]'))
        self.assertNotEqual(self.url_open('/my/viandas/ayuda', allow_redirects=False).status_code, 200)
        self.assertEqual(self.url_open('/viandas/ayuda-acceso', headers={'Host': 'public.test'}).status_code, 404)
        employee, _ = self._create_employee()
        self._real_login(employee.login, 'employee-password-123')
        self.assertEqual(self.url_open('/my/viandas/ayuda').status_code, 200)
        sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
        self.opener.cookies.set('session_id', sid, domain='public.test')
        self.assertEqual(self.url_open('/my/viandas/ayuda', headers={'Host': 'public.test'}).status_code, 403)
        for path in ['/shop', '/web/image/product.template/1/image_1920', '/web/assets/anything/test.js',
                     '/my/invoices', '/my/viandas/ayuda/extra', '/odoo/action-kai_viandas.operator_help_action']:
            self.assertEqual(self.url_open(path).status_code, 403, path)
        self._manage(employee, 'disable').action_apply()
        self.assertNotEqual(self.url_open('/my/viandas/ayuda', allow_redirects=False).status_code, 200)
        self.authenticate(self.private.login, 'private-password-123')
        self.assertEqual(self.url_open('/my/viandas/ayuda').status_code, 403)

    def test_brand_and_help_links_in_all_employee_screens(self):
        self.website.logo = configured_logo()
        self._anonymous()
        self.assertIn('/viandas/ayuda-acceso', self.url_open('/web/login').text)
        self.assertIn('Entrá para continuar', self.url_open('/web/login?lf_session_ended=1').text)
        employee, record, _, _ = self._setup_pending()
        for path in ['/my/viandas?week=2026-09-14', f'/my/viandas/{record.id}', '/my/viandas/ayuda', '/shop']:
            response = self.url_open(path)
            tree = html.fromstring(response.content)
            self.assertTrue(response.content.lstrip().lower().startswith(b'<!doctype html>'), path)
            self.assertTrue(tree.xpath('//header//img[starts-with(@src,"/viandas/marca/")]'), path)
            self.assertTrue(tree.xpath('//header//a[starts-with(@href,"/my/viandas/ayuda")]'), path)
            self.assertIn(resource_url('viandas.css'), response.text)
            self.assertNotIn('271828', response.text)
        self.website.logo = self.website._default_logo()
        self.assertFalse(html.fromstring(self.url_open('/my/viandas').content).xpath('//header//img'))

    def test_this_week_is_calendar_week_in_business_timezone_and_landing_is_unchanged(self):
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        employee, _ = self._create_employee()
        self._real_login(employee.login, 'employee-password-123')
        for moment, expected in [('2026-09-13 15:00:00', '2026-09-07'),
                                 ('2026-09-14 02:59:59', '2026-09-07'),
                                 ('2026-09-14 03:00:00', '2026-09-14')]:
            with freeze_time(moment):
                with patch('odoo.addons.kai_viandas.controllers.viandas.business_today', wraps=business_today) as clock:
                    tree = html.fromstring(self.url_open('/my/viandas?week=2026-10-05').content)
                    self.assertEqual(clock.call_count, 1, 'Toda la respuesta usa la misma fecha')
                link = tree.xpath('//a[@class="this-week"]/@href')[0]
                self.assertEqual(link, '/my/viandas?week=' + expected)
                self.assertEqual(html.fromstring(self.url_open(link).content).xpath('//input[@name="week"]/@value'), [expected])
                self.assertEqual(html.fromstring(self.url_open('/my/viandas').content).xpath('//input[@name="week"]/@value'), ['2026-09-14'])

    def test_this_week_navigation_keeps_conflict_draft_in_its_original_week(self):
        employee, record, current, alternate = self._setup_pending()
        page = self._page()
        self._operator_replace(record, alternate)
        response = self.url_open('/my/viandas/reservar', data=self._post_data(page, current))
        self.assertIn('No se guardó ningún día', response.text)
        link = html.fromstring(response.content).xpath('//a[@class="this-week"]/@href')[0]
        self.url_open(link)
        self.url_open('/my/viandas/ayuda')
        back = self._page()
        self.assertEqual(len(back.xpath('//span[@class="draft-choice" and not(@hidden)]')), 3)
        self.assertTrue(back.xpath('//p[@class="error day-conflict"]'))
        self.assertEqual(len(self.env['lafija.reservation'].with_user(employee).search([])), 1)

    def test_pointer_cream_week_targets_contrast_states_and_flow_footer(self):
        self.website.logo = configured_logo(white_edge=True)
        employee, _, _, _ = self._setup_pending()
        for viewport in ((360, 800), (390, 844), (1366, 900)):
            self._real_login(employee.login, 'employee-password-123')
            sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')
            self._pointer_browser('/my/viandas?week=2026-09-14', r'''
                if(document.compatMode!=='CSS1Compat') throw new Error('Quirks');
                if(document.documentElement.scrollWidth>innerWidth) throw new Error('Desborde');
                const luminance=c=>{c=c.trim();const a=(c.startsWith('#')?[1,3,5].map(i=>parseInt(c.slice(i,i+2),16)):c.match(/[\d.]+/g).slice(0,3).map(Number)).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return a[0]*.2126+a[1]*.7152+a[2]*.0722};
                const contrast=(a,b)=>{const x=luminance(a),y=luminance(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
                const bodyStyle=getComputedStyle(document.body);
                if(bodyStyle.color!=='rgb(65, 65, 65)') throw new Error('No usa carbón');
                const palette=getComputedStyle(document.documentElement), color=name=>palette.getPropertyValue('--'+name);
                for(const state of ['current','pending','draft','error','cut']) {
                    if(contrast(color(state),color(state+'-bg'))<4.5) throw new Error('Estado sin contraste AA: '+state);
                }
                for(const bg of ['canvas','header','selection']) {
                    if(contrast(color('ink'),color(bg))<4.5 || contrast(color('muted'),color(bg))<4.5) throw new Error('Texto sin contraste AA: '+bg);
                    if(contrast(color('control'),color(bg))<3 || contrast(color('focus'),color(bg))<3) throw new Error('Control o foco sin contraste: '+bg);
                }
                for(const e of document.querySelectorAll('header a, nav.weeks a, .save-bar button')) {
                    const b=e.getBoundingClientRect(); if(b.height<44 || b.width<44) throw new Error('Objetivo pequeño: '+e.textContent);
                }
                for(const e of document.querySelectorAll('.badge,.notice,.save-bar button')) {
                    const s=getComputedStyle(e);if(contrast(s.color,s.backgroundColor)<4.5) throw new Error('Contraste de texto insuficiente: '+e.textContent);
                }
                for(const index of [1,2,3,4]) {
                    const day=document.querySelectorAll('details.day')[index];
                    if(!day.open) await pointer(day.querySelector('summary'));
                    await pointer([...day.querySelectorAll('.option-card')].find(e=>e.querySelector('input').value));
                    await wait(()=>!day.open,'No plegó');
                }
                const save=document.querySelector('.save-bar'), draft=document.querySelector('.draft-choice:not([hidden])');
                if(!save.textContent.includes('4 días sin guardar')) throw new Error('Contador');
                if(contrast(getComputedStyle(draft).color,getComputedStyle(draft).backgroundColor)<4.5) throw new Error('Borrador sin contraste');
                if(getComputedStyle(save).position!=='static') throw new Error('Pie superpuesto');
                if(innerWidth<=600) {
                    const b=save.getBoundingClientRect(),s=document.querySelector('.week-scroll').getBoundingClientRect();
                    if(b.top<s.bottom-1 || b.bottom>innerHeight+1) throw new Error('Guardar tapa o sale de pantalla');
                }
            ''', None, min_clicks=7, viewport=viewport, cookies={'session_id': sid})

    def test_pointer_operator_opens_help_menu_in_backend(self):
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()
        self.authenticate(self.operator.login, 'fixture')
        response = self.url_open('/web/action/load', data=json.dumps({'jsonrpc': '2.0', 'params': {
            'action_id': 'kai_viandas.operator_help_action'}}), headers={'Content-Type': 'application/json'})
        self.assertEqual(response.json()['result']['res_id'], self.env.ref('kai_viandas.operator_help').id)
        self._pointer_browser('/odoo/action-kai_viandas.workday_action', r'''
            const menu=await wait(()=>[...document.querySelectorAll('a')].find(e=>visible(e)&&e.textContent.trim()==='Ayuda'),'Falta menú Ayuda');
            await pointer(menu);
            await wait(()=>document.querySelector('.lf-operator-help'),'No abrió el contenido');
            if(!document.querySelector('.o_form_view')) throw new Error('Salió del backend');
            if(!document.querySelector('.lf-operator-help').textContent.includes('La rutina del día')) throw new Error('Contenido vacío');
            if(document.querySelector('.o_error_dialog')) throw new Error('Error de acceso');
        ''', self.operator.login, min_clicks=1)

    def test_browser_employee_help_navigation_and_all_screen_widths(self):
        employee, record, _, _ = self._setup_pending()
        original = ChromeBrowser._wait_code_ok
        for width, height in [(360, 800), (390, 844), (1366, 900)]:
            self._real_login(employee.login, 'employee-password-123')
            sid = next(c.value for c in self.opener.cookies if c.name == 'session_id' and c.domain == '127.0.0.1')

            def journey(browser, code, timeout, **kwargs):
                browser._websocket_request('Emulation.setDeviceMetricsOverride', params={
                    'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False})

                def evaluate(expression):
                    return browser._websocket_request('Runtime.evaluate', params={
                        'expression': expression, 'returnByValue': True}).get('result', {}).get('value')

                def wait(expression):
                    for _ in range(200):
                        if evaluate(expression):
                            return
                        time.sleep(.05)
                    self.fail(expression)

                def screen(name, selector):
                    wait('document.readyState==="complete" && !!document.querySelector(' + json.dumps(selector) + ')')
                    self.assertEqual(evaluate('document.compatMode'), 'CSS1Compat')
                    self.assertTrue(evaluate('document.documentElement.scrollWidth<=innerWidth'), name)
                    self.assertEqual(evaluate('getComputedStyle(document.body).color'), 'rgb(65, 65, 65)')
                    self.assertFalse(evaluate('!!document.querySelector("link[href*=\"/web/assets\"]")'))
                    browser.take_screenshot(prefix=f'a150_{width}_{name}_').result(timeout=10)

                def pointer(selector):
                    wait('!!document.querySelector(' + json.dumps(selector) + ')')
                    target = 'document.querySelector(' + json.dumps(selector) + ')'
                    evaluate(target + '.scrollIntoView({block:"center"})')
                    time.sleep(.1)
                    point = evaluate('(()=>{const e=' + target + ';const r=e.getBoundingClientRect();'
                        'const x=r.x+r.width/2,y=r.y+r.height/2;return{x,y,clear:e.contains(document.elementFromPoint(x,y))};})()')
                    self.assertTrue(point['clear'], selector)
                    evaluate('window.lfLeaving=true')
                    for kind in ('mousePressed', 'mouseReleased'):
                        browser._websocket_request('Input.dispatchMouseEvent', params={
                            'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1})
                    wait('!window.lfLeaving')

                def navigate(path):
                    evaluate('window.lfLeaving=true')
                    browser._websocket_request('Page.navigate', params={'url': self.base_url() + path})
                    wait('!window.lfLeaving')

                screen('semana', '#lf-week-form')
                pointer('header a[href^="/my/viandas/ayuda?"]')
                screen('ayuda', '.help-page')
                pointer('.back-link')
                pointer('nav .this-week')
                screen('esta_semana', '#lf-week-form')
                pointer('nav .available')
                screen('proxima', '#lf-week-form')
                navigate(f'/my/viandas/{record.id}')
                screen('detalle', '.reservation-card')
                navigate('/shop')
                screen('denegacion', '.denial')
                pointer('.denial a[href="/my/viandas"]')
                pointer('header a[href^="/web/session/logout"]')
                screen('acceso', '#lf_login')
                navigate('/web/login?lf_session_ended=1')
                screen('sesion_terminada', '.login .notice')
                pointer('a[href="/viandas/ayuda-acceso"]')
                screen('ayuda_acceso', '.help-page')
                self.assertFalse(evaluate('!!document.querySelector("nav.weeks")'))
                return original(browser, code, timeout, **kwargs)

            with patch.object(ChromeBrowser, '_wait_code_ok', journey):
                self.browser_js('/my/viandas?week=2026-09-14', "console.log('test successful');",
                                login=None, cookies={'session_id': sid}, timeout=120)
