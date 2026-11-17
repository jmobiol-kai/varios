import json
import logging
import base64
import io
import re
from urllib.parse import urlsplit
from unittest.mock import patch

from lxml import html
from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged
from odoo.http import request

from .test_identity import LafijaCommon


class PagesCommon(LafijaCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website.domain = cls.base_url()
        cls.public_site = cls.env.ref("website.default_website")
        cls.public_site.domain = "http://public.test"
        cls.product = cls.env["product.product"].create({
            "name": "Vianda prueba P1", "description_sale": "Pollo con arroz",
            "list_price": 271828.75, "is_published": True, "type": "consu",
            "categ_id": cls.plate_categ.id,
        })
        cls.menus = cls.env["lafija.menu.day"].with_user(cls.operator).create([
            {"date": f"2026-09-{day}", "website_id": cls.website.id, "published": True,
             "product_ids": [Command.set(cls.product.ids)]}
            for day in range(14, 19)
        ])

    def _anonymous(self):
        self.authenticate(None, None)
        self.opener.cookies.set("session_id", self.session.sid, domain="public.test")

    def _real_login(self, login, password):
        self._anonymous()
        response = self.url_open("/web/login")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Entrá a tus viandas", response.text)
        token = html.fromstring(response.content).xpath("//input[@name='csrf_token']/@value")[0]
        return self.url_open("/web/login", data={
            "csrf_token": token, "login": login, "password": password,
            "type": "password", "redirect": "/my/viandas",
        }, allow_redirects=False)


@tagged("post_install", "-at_install")
class TestPages(PagesCommon):
    def test_option_image_requires_authorized_account_and_menu_membership(self):
        pixels = io.BytesIO()
        Image.new("RGB", (8, 8), (25, 80, 60)).save(pixels, format="PNG")
        self.product.image_1920 = base64.b64encode(pixels.getvalue())
        self.product.is_published = False  # La foto y la elegibilidad dependen del menú, no de /shop.
        other = self.env["product.product"].create({"name": "Fuera del menú",
            "image_1920": base64.b64encode(pixels.getvalue()), "list_price": 987654.32})
        employee, _ = self._create_employee()
        self._real_login(employee.login, "employee-password-123")
        url = f"/my/viandas/opcion/{self.product.id}/imagen?menu_id={self.menus[0].id}"
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertEqual(Image.open(io.BytesIO(response.content)).getpixel((0, 0)), (25, 80, 60))
        self.assertIn("no-store", response.headers["Cache-Control"])
        forbidden = self.url_open(f"/my/viandas/opcion/{other.id}/imagen?menu_id={self.menus[0].id}")
        self.assertEqual(forbidden.status_code, 404)
        self.assertNotIn("987654", forbidden.text)
        self.product.active = False
        self.assertEqual(self.url_open(url).status_code, 404)
        self._anonymous()
        self.assertIn(self.url_open(url, allow_redirects=False).status_code, (303, 403))

    def test_00_guard_is_noop_for_public_and_internal_requests(self):
        # Mismos datos y sesión; quitar SOLO la guardia no altera la respuesta.
        self._anonymous()
        headers = {"Host": "public.test"}
        guarded = self.url_open("/shop", headers=headers)
        with patch.object(type(self.env["ir.http"]), "_lf_guard", return_value=None):
            native = self.url_open("/shop", headers=headers)
        self.assertEqual(guarded.status_code, 200)
        def without_csrf(response):
            # El token incorpora tiempo de expiración; es el único valor normalizado.
            text = response.text
            tokens = html.fromstring(response.content).xpath("//input[@name='csrf_token']/@value")
            tokens += re.findall(r'csrf_token:\s*[\"\']([^\"\']+)[\"\']', text)
            for token in tokens:
                text = text.replace(token, "CSRF_NORMALIZADO")
            return text
        self.assertEqual(without_csrf(guarded), without_csrf(native))
        self.assertEqual(guarded.headers.get("Content-Type"), native.headers.get("Content-Type"))
        self.authenticate(self.operator.login, "fixture")
        self.opener.cookies.set("session_id", self.session.sid, domain="public.test")
        payload = {"jsonrpc": "2.0", "id": 1, "params": {}}
        guarded = self.url_open("/web/session/get_session_info", headers=headers, json=payload)
        with patch.object(type(self.env["ir.http"]), "_lf_guard", return_value=None):
            native = self.url_open("/web/session/get_session_info", headers=headers, json=payload)
        self.assertEqual(guarded.json(), native.json())
        self.assertEqual(guarded.json()["result"]["uid"], self.operator.id)
        # Mismo backend con caché caliente: el despacho ajeno no hace consultas.
        counts = []
        original_guard = type(self.env["ir.http"])._lf_guard
        def measured(rule=None):
            before = request.env.cr.sql_log_count
            result = original_guard(rule)
            counts.append(request.env.cr.sql_log_count - before)
            return result
        with patch.object(type(self.env["ir.http"]), "_lf_guard", side_effect=measured):
            self.env.registry.clear_cache()
            self.url_open("/web/session/get_session_info", headers=headers, json=payload)
            self.url_open("/web/session/get_session_info", headers=headers, json=payload)
        self.assertEqual(len(counts), 2)
        self.assertLessEqual(counts[0], 10)
        self.assertEqual(counts[1], 0)
        logging.getLogger(__name__).info("LAFIJA_GUARD_SQL cold=%s warm=%s", *counts)

    def test_real_login_week_selection_and_own_history_without_amounts(self):
        employee, _ = self._create_employee()
        response = self._real_login(employee.login, "employee-password-123")
        self.assertEqual(response.status_code, 303, response.text)
        page = self.url_open("/my/viandas?week=2026-09-14")
        self.assertEqual(page.status_code, 200, page.text)
        document = html.fromstring(page.content)
        self.assertEqual(len(document.xpath("//fieldset[@class='options']")), 5)
        token = document.xpath("//input[@name='csrf_token']/@value")[0]
        response = self.url_open("/my/viandas/reservar", data={
            "csrf_token": token, "week": "2026-09-14",
            **{f"menu_{self.menus[i].id}": str(self.product.id) for i in (0, 1, 3)},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(html.fromstring(response.content).xpath("//article[@class='reservation-card']")), 3)
        self.assertIn('elección guardada', response.text)
        self.assertNotIn("271828", response.text)
        self.assertNotIn("271.828", response.text)
        self.assertIn("private, no-store", response.headers["Cache-Control"])
        self.env.invalidate_all()
        own = self.env["lafija.reservation"].search([("employee_partner_id", "=", employee.partner_id.id)])
        self.assertEqual([str(d) for d in sorted(own.mapped("date"))], ["2026-09-14", "2026-09-15", "2026-09-17"])

    def test_corporate_guard_denies_generic_routes_and_cross_host_session(self):
        employee, _ = self._create_employee()
        self._real_login(employee.login, "employee-password-123")
        for path in ("/shop", "/website/search", "/web/image/product.template/1/image_1920",
                     "/my/orders", "/my/invoices", "/my/security", "/not-a-real-route"):
            with self.subTest(path=path):
                response = self.url_open(path)
                self.assertIn(response.status_code, (403, 404), response.text)
                self.assertNotIn("271828", response.text)
        rpc = self.url_open("/web/dataset/call_kw/product.template/read", json={
            "jsonrpc": "2.0", "id": 1, "params": {"model": "product.template", "method": "read",
                "args": [self.product.product_tmpl_id.ids, ["list_price"]], "kwargs": {}},
        })
        self.assertEqual(rpc.status_code, 403, rpc.text)
        cookie = self.opener.cookies.get("session_id", domain=urlsplit(self.base_url()).hostname, path="/")
        self.opener.cookies.set("session_id", cookie, domain="public.test")
        response = self.url_open("/shop", headers={"Host": "public.test"})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.url_open("/my/account", data={"name": "Attempt"}).status_code, 403)

    def test_anonymous_catalogue_reset_and_shared_private_account_are_denied(self):
        self._anonymous()
        for path in ("/shop", "/website/search", "/web/image/product.template/1/image_1920",
                     "/web/reset_password", "/web/signup"):
            with self.subTest(path=path):
                self.assertIn(self.url_open(path).status_code, (403, 404))
        self.assertEqual(self.url_open("/web/login").status_code, 200)
        self.authenticate(self.private.login, "fixture")
        self.assertEqual(self.url_open("/my/viandas").status_code, 403)
        self.assertEqual(self.url_open("/shop", headers={"Host": "public.test"}).status_code, 200)

    def test_global_monetary_rules_intersect_additional_portal_grants(self):
        employee, _ = self._create_employee()
        model = self.env.ref("product.model_product_template")
        self.env["ir.rule"].create({"name": "Additional permissive portal rule", "model_id": model.id,
            "groups": [Command.set([self.env.ref("base.group_portal").id])], "domain_force": "[(1, '=', 1)]"})
        self.assertFalse(self.env["product.template"].with_user(employee).search([]))
        self.assertFalse(self.env["product.pricelist.item"].with_user(employee).search([]))
        with self.assertRaises(AccessError):
            self.product.with_user(employee).read(["list_price"])
        self.assertEqual(self.product.with_user(self.private).read(["list_price"])[0]["list_price"], 271828.75)

    def test_browser_uses_actual_login_and_selection_forms(self):
        employee, _ = self._create_employee()
        # Un marco conserva el conductor JS mientras el navegador sigue los formularios
        # normales de la interfaz. No llama al servicio de reservas desde JavaScript.
        self.browser_js("/web/login", """
            (async () => {
                const frame = document.createElement('iframe');
                frame.style.cssText = 'width:100%;height:800px';
                document.body.appendChild(frame);
                const loaded = () => new Promise(resolve => frame.addEventListener('load', resolve, {once:true}));
                let done = loaded(); frame.src = '/web/login'; await done;
                let doc = frame.contentDocument;
                doc.querySelector('[name=login]').value = LOGIN;
                doc.querySelector('[name=password]').value = 'employee-password-123';
                done = loaded(); doc.querySelector('button[type=submit]').click(); await done;
                if (frame.contentWindow.location.pathname !== '/my/viandas' || !frame.contentDocument.querySelector('h1')?.textContent.includes('Mis viandas')) throw new Error('Login no llegó a viandas');
                done = loaded(); frame.src = '/my/viandas?week=2026-09-14'; await done;
                doc = frame.contentDocument;
                const days = [...doc.querySelectorAll('fieldset.options')];
                if (days.length !== 5) throw new Error('Faltan días publicados');
                [0,1,3].forEach(index => days[index].querySelector('input[value="' + PRODUCT + '"]').click());
                done = loaded(); doc.querySelector('button[type=submit]').click(); await done;
                doc = frame.contentDocument;
                if (doc.querySelectorAll('article.reservation-card').length !== 3) throw new Error('No guardó los tres días');
                if (/271[.,]?828/.test(doc.documentElement.outerHTML)) throw new Error('Importe expuesto');
                done = loaded(); doc.querySelector('article a').click(); await done;
                if (!frame.contentDocument.body.textContent.includes('Pollo con arroz')) throw new Error('Falta elección propia');
                done = loaded(); frame.contentDocument.querySelector('header a[href^="/web/session/logout"]').click(); await done;
                if (!frame.contentDocument.querySelector('[name=password]')) throw new Error('No cerró sesión');
                console.log('test successful');
            })().catch(error => console.error(error.message));
        """.replace("LOGIN", json.dumps(employee.login)).replace("PRODUCT", json.dumps(str(self.product.id))), timeout=60)
