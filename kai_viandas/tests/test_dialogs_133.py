"""Diálogos abiertos con puntero: historia legada, campos vacíos y consulta cerrada."""
import base64
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import ChromeBrowser, save_test_file

from .test_pages import PagesCommon
from .test_preparation import PreparationCommon
from .test_ux_round2 import TestUXRound2


@tagged('post_install', '-at_install')
class TestDialogResponses(PreparationCommon):
    def test_default_reply_describes_actual_attention_without_changing_it(self):
        cut = self._take()
        revision = cut.current_revision_id
        self.service._submit_selections(self.website, [(self.menu.id, self.fish.id)])
        for state in ('without_request', 'open', 'closed'):
            with self.subTest(state=state):
                if state == 'open':
                    self.reservation._request_correction('Consulta por atender')
                elif state == 'closed':
                    self._resolve('close_request')
                expected_open = state == 'open'
                result = self._resolve('note')
                self.assertEqual(self.reservation.sudo().attention_pending, expected_open)
                self.assertEqual(self.reservation.sudo().pending_product_id, self.fish)
                self.assertEqual(cut.current_revision_id, revision)
                self.assertEqual(cut.revision_ids, revision)
                summary = result['params']['message']
                message = self.reservation._employee_values()['messages'][-1]['text']
                if expected_open:
                    self.assertIn('consulta sigue pendiente', summary)
                    self.assertIn('solicitud sigue pendiente', message)
                else:
                    self.assertIn('no hay consulta escrita pendiente', summary)
                    self.assertIn('No hay una consulta escrita pendiente', message)
                    self.assertNotIn('sigue pendiente', summary + message)
                self.assertEqual(self.reservation._employee_values()['choices'][-1]['outcome'],
                                 'Respuesta sin cierre')


@tagged('post_install', '-at_install')
class TestOperatorDialogs(PagesCommon):
    def _operator_site(self):
        self.website.domain = 'http://corporate.test'
        self.website.flush_recordset(['domain'])
        self.public_site.domain = self.base_url()

    def _record(self):
        employee, _ = self._create_employee()
        record = self.env['lafija.reservation'].with_user(employee)._submit_selections(
            self.website, [(self.menus[0].id, self.product.id)])
        return employee, record

    def _pointer_browser(self, url, script, min_clicks):
        original = ChromeBrowser._wait_code_ok

        def capture(browser, code, timeout, **kwargs):
            result = original(browser, code, timeout, **kwargs)
            png = base64.b64decode(browser._websocket_request('Page.captureScreenshot')['data'])
            save_test_file(self._testMethodName, png, 'dialogo_133_', extension='png', directory='screenshots')
            return result

        with patch.object(ChromeBrowser, '_wait_code_ok', capture):
            TestUXRound2._pointer_browser(self, url, script, self.operator.login,
                                         min_clicks=min_clicks, viewport=(1366, 900))

    def test_pointer_history_dialog_normalizes_legacy_without_rewriting_and_has_one_clock(self):
        employee, record = self._record()
        self.env.ref('base.user_admin').tz = 'America/Argentina/Buenos_Aires'
        legacy_text = 'Cambio solicitado retirado por el empleado'
        # Preparación de historia legada con permisos internos; el empleado no
        # obtiene lectura de la revisión de oferta ni acceso directo a eventos.
        internal = record.with_user(self.operator)
        old = internal._record_event(employee, fields.Datetime.to_datetime('2026-09-13 06:29:00'),
                                    'withdrawal', 'Guiso', 'Pollo legado', 'Guiso', legacy_text)
        internal._record_event(employee, fields.Datetime.to_datetime('2026-09-13 12:55:00'),
                               'withdrawal', 'Guiso', 'Pollo nuevo', 'Guiso', 'Cambio anulado por el empleado')
        before = {event['id']: event for event in record.sudo().event_ids.read(['result', 'occurred_at', 'kind'])}
        self._operator_site()
        self._pointer_browser(f'/odoo/action-kai_viandas.reservation_action/{record.id}', r'''
            for (const [choice, time] of [['Pollo nuevo','13/09/2026 09:55'], ['Pollo legado','13/09/2026 03:29']]) {
                const row=await wait(()=>[...document.querySelectorAll('[name="event_ids"] .o_data_row')].find(
                    e=>e.textContent.includes(choice)), 'No aparece el evento en la lista');
                await pointer(row.querySelector('[name="received_description"]'));
                const modal=await wait(()=>document.querySelector('.modal [name="result_label"]')?.closest('.modal'),
                    'El clic no abrió el formulario del evento');
                if(modal.querySelector('[name="result"]') || modal.querySelector('[name="occurred_at"]'))
                    throw new Error('El diálogo entrega el resultado crudo o el reloj del navegador');
                if(modal.querySelectorAll('[name="result_label"]').length!==1 ||
                   modal.querySelectorAll('[name="occurred_local"]').length!==1) throw new Error('Datos duplicados');
                if(!modal.querySelector('[name="occurred_local"]').textContent.includes(time))
                    throw new Error('No se usa la hora de La Fija con Chrome en UTC');
                const labels=[...modal.querySelectorAll('label')].map(e=>e.textContent.trim());
                if(!labels.includes('Reserva') || labels.includes('Reservation')) throw new Error('Etiqueta sin traducir');
                if(/retir/i.test(modal.innerText)) throw new Error('Texto legado expuesto en el diálogo');
                if(!modal.querySelector('[name="result_label"]').textContent.includes('Cambio anulado por el empleado'))
                    throw new Error('Falta el resultado normalizado');
                if(modal.querySelectorAll('textarea, input:not([disabled]), .o_form_button_save').length)
                    throw new Error('La historia permite edición en el formulario');
                if(choice==='Pollo nuevo') {
                    // Cierre nativo del diálogo: su traducción depende del idioma
                    // de esta base; no confundirlo con los rótulos propios bajo prueba.
                    await pointer(modal.querySelector('.modal-footer button.btn-primary'));
                    await wait(()=>!document.querySelector('.modal'), 'No cerró el evento');
                }
            }
        ''', min_clicks=3)
        self.env.invalidate_all()
        self.assertEqual(old.result, legacy_text)
        # El ORM ordena por fecha al volver a leer; la carga de eventos legados
        # los agrega inicialmente a la caché por orden de creación. Comparar
        # identidad y contenido, no ese orden transitorio de la preparación.
        after = {event['id']: event for event in record.sudo().event_ids.read(['result', 'occurred_at', 'kind'])}
        self.assertEqual(after, before)

    def test_pointer_replacement_note_is_visible_without_focus_and_accepts_keyboard(self):
        _, record = self._record()
        result = self.menus[0].with_user(self.operator).action_take_list()
        cut = self.env['lafija.preparation.cut'].browse(result['res_id'])
        revision = cut.current_revision_id
        result = revision.with_user(self.operator).action_print_labels()
        printed = self.env['lafija.label.print'].browse(result['res_id'])
        pdf = printed.attachment_id.raw
        self._operator_site()
        self._pointer_browser(f'/odoo/action-kai_viandas.cut_action/{cut.id}', r'''
            await pointer(await wait(()=>document.querySelector('[name="current_revision_id"] a'), 'Falta revisión vigente'));
            await pointer(await wait(()=>document.querySelector('[name="print_ids"] .o_data_row [name="name"]'),
                'Falta archivo conservado'));
            await pointer(await wait(()=>document.querySelector('.modal button[name="action_register_replacement"]'),
                'Falta Registrar sustitución'));
            const field=await wait(()=>document.querySelector('.modal [name="note"] textarea'), 'No abrió coordinación');
            if(document.activeElement===field || field.matches(':hover')) throw new Error('Debe verse sin foco ni hover');
            const style=getComputedStyle(field);
            if(parseFloat(style.borderBottomWidth)<1 || style.borderBottomStyle==='none' ||
               ['transparent','rgba(0, 0, 0, 0)'].includes(style.borderBottomColor)) throw new Error('Campo sin borde');
            if(field.placeholder!=='Describí qué etiquetas se reemplazaron y cómo se coordinó con preparación')
                throw new Error('Campo sin ayuda de escritura');
            const widget=field.closest('[name="note"]');
            if(!widget.classList.contains('o_required_modifier')) throw new Error('Se perdió la obligación del motivo');
            await typeKeys(field, 'Coordinación de prueba por teclado.');
            if(field.value!=='Coordinación de prueba por teclado.') throw new Error('No recibió el teclado');
            await pointer([...field.closest('.modal').querySelectorAll('button')].find(e=>visible(e)&&e.textContent.trim()==='Volver'));
            await wait(()=>!document.querySelector('.modal [name="note"] textarea'), 'No canceló la coordinación');
            await pointer(document.querySelector('.modal button[name="action_register_replacement"]'));
            await wait(()=>document.querySelector('.modal [name="note"] textarea')?.value==='', 'Quedó un borrador cancelado');
        ''', min_clicks=6)
        self.env.invalidate_all()
        self.assertFalse(printed.handling_ids)
        self.assertEqual(printed.attachment_id.raw, pdf)
        self.assertEqual(cut.revision_ids, revision)
        self.assertEqual(revision.line_ids.reservation_id, record.sudo())

    def test_pointer_closed_request_reply_uses_true_status_and_keeps_reason_private(self):
        employee, record = self._record()
        record._request_correction('Consulta que ya fue resuelta')
        self.env['lafija.reservation.correction'].with_user(self.operator).create({
            'reservation_id': record.id, 'operation': 'close_request', 'reason': 'Consulta atendida',
        }).action_apply()
        self._operator_site()
        self._pointer_browser(f'/odoo/action-kai_viandas.reservation_action/{record.id}', r'''
            const attend=async()=>{
                await pointer(await wait(()=>document.querySelector('button[name="action_correct"]'), 'Falta Atender'));
                return await wait(()=>document.querySelector('.modal [name="employee_message"] textarea')?.closest('.modal'),
                    'No abrió el asistente');
            };
            let modal=await attend();
            if(!modal.querySelector('[name="request_text"]').textContent.includes('Sin solicitud escrita pendiente'))
                throw new Error('La consulta no está cerrada');
            if(modal.querySelector('[name="operation"] input')?.value!=='Responder al empleado')
                throw new Error('La operación promete una solicitud inexistente');
            const alerts=[...modal.querySelectorAll('[role="status"]')].filter(visible).map(e=>e.textContent).join('\n');
            if(alerts.includes('sigue pendiente') || !alerts.includes('enviar una respuesta no la abre'))
                throw new Error('Aviso contradictorio con consulta cerrada');
            const send=[...modal.querySelectorAll('button[name="action_apply"]')].filter(visible);
            if(send.length!==1 || send[0].textContent.trim()!=='Enviar respuesta') throw new Error('Botón incorrecto');
            await typeKeys(modal.querySelector('[name="employee_message"] textarea'), 'Te confirmamos lo acordado.');
            await typeKeys(modal.querySelector('[name="reason"] textarea'), 'INTERNO 918273 privado');
            await pointer(send[0]);
            await wait(()=>!document.querySelector('.modal'), 'No envió la respuesta');
            const notice=await wait(()=>[...document.querySelectorAll('.o_notification')].find(e=>visible(e)), 'Falta confirmación');
            if(!notice.textContent.includes('no hay consulta escrita pendiente') || notice.textContent.includes('sigue pendiente'))
                throw new Error('Confirmación falsa');
            modal=await attend();
            if(!modal.querySelector('[name="request_text"]').textContent.includes('Sin solicitud escrita pendiente'))
                throw new Error('Responder reabrió la consulta');
        ''', min_clicks=5)
        self.env.invalidate_all()
        self.assertFalse(record.sudo().attention_pending)
        self.assertFalse(record.sudo().pending)
        values = record._employee_values()
        self.assertIn('Te confirmamos lo acordado.', [m['text'] for m in values['messages']])
        self.assertNotIn('918273', str(values))
        self.assertIn('918273', record.sudo().event_ids[-1].result)
