import base64
from collections import Counter
from datetime import timedelta
import hashlib
import json
import logging
import secrets
import time
import uuid

from odoo import api, Command, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from .identity import check_operator
from . import padron_io
from .time_utils import business_datetime

_logger = logging.getLogger(__name__)
_INPUTS = {'customer_company_id', 'website_id', 'prefix', 'source_text', 'upload', 'upload_name',
           'line_ids', 'confirm_duplicate_names'}
_LINE_INPUTS = {'batch_id', 'row_number', 'name', 'login', 'legajo'}
# Presupuesto fijo de tiempo real, con margen frente a 320 s de CPU externos.
# Incluye validación y altas; se comprueba también después de la última fila.
# No interrumpe una llamada bloqueante: no reemplaza los límites del servidor.
MAX_RUN_SECONDS = 240


class EmployeeBatch(models.Model):
    _name = 'lafija.employee.batch'
    _description = 'Alta desde padrón'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char('Lote', compute='_compute_name', store=True)
    customer_company_id = fields.Many2one('res.partner', 'Empresa cliente', domain=[('is_company', '=', True)], ondelete='restrict')
    website_id = fields.Many2one('website', 'Sitio corporativo', domain=[('lf_corporate_site', '=', True)], ondelete='restrict')
    prefix = fields.Char('Prefijo para usuarios propuestos')
    source_text = fields.Text('Padrón pegado')
    upload = fields.Binary('Archivo CSV', attachment=False)
    upload_name = fields.Char('Nombre de archivo')
    confirm_duplicate_names = fields.Boolean('Confirmo que los nombres repetidos son personas diferentes')
    line_ids = fields.One2many('lafija.employee.batch.line', 'batch_id', 'Vista previa')
    state = fields.Selection([('draft', 'Revisar padrón'), ('validated', 'Validado'), ('queued', 'En segundo plano'),
                              ('done', 'Altas confirmadas'), ('failed', 'Sin altas · revisar')], default='draft', readonly=True)
    validation_hash = fields.Char(readonly=True, groups='base.group_system')
    credential_token = fields.Char(readonly=True, groups='base.group_system', copy=False)
    notice = fields.Text('Resultado', readonly=True)
    completed_at = fields.Datetime('Altas confirmadas el', readonly=True)
    credentials_until = fields.Datetime('Archivo disponible hasta', readonly=True)
    credentials_status = fields.Char('Entrega de accesos', compute='_compute_progress')
    download_available = fields.Boolean(compute='_compute_progress')
    progress_id = fields.Many2one('lafija.employee.batch.progress', readonly=True, copy=False)
    progress_text = fields.Char('Avance', compute='_compute_progress')
    row_count = fields.Integer('Personas', compute='_compute_progress')

    @api.depends('create_date')
    def _compute_name(self):
        for batch in self:
            batch.name = f'P-{batch.id:06d}' if isinstance(batch.id, int) else 'Nuevo padrón'

    def _compute_progress(self):
        now = fields.Datetime.now()
        for batch in self:
            progress = batch.sudo().progress_id
            batch.row_count = len(batch.line_ids)
            batch.download_available = bool(batch.state == 'done' and batch.credentials_until and now < batch.credentials_until)
            batch.credentials_status = (
                'CSV disponible hasta ' + business_datetime(batch.env, batch.credentials_until) + ' · hora de La Fija'
                if batch.download_available else
                'La ventana terminó. Para recuperar un acceso, usá Cambiar contraseña en el menú de acciones.'
                if batch.state == 'done' else 'El archivo estará disponible durante 15 minutos después de confirmar todas las altas.')
            if batch.state == 'queued':
                batch.progress_text = (f'Procesando {progress.processed} de {batch.row_count}. Avance provisional: todavía no se confirmó ninguna alta.'
                                       if progress.attempt else 'En espera del proceso de segundo plano. Podés cerrar esta pestaña y volver al lote.')
            elif batch.state == 'done':
                batch.progress_text = (f'{batch.row_count} ' + ('alta confirmada' if batch.row_count == 1 else 'altas confirmadas')
                                       + '. El lote no se volverá a ejecutar.')
            elif batch.state == 'failed':
                batch.progress_text = 'No se creó ninguna cuenta de este intento. Corregí y volvé a validar.'
            else:
                batch.progress_text = 'La vista previa no crea cuentas ni envía correo.'

    @api.model
    def default_get(self, names):
        result = super().default_get(names)
        if 'website_id' in names:
            sites = self.env['website'].search([('lf_corporate_site', '=', True)], limit=2)
            if len(sites) == 1:
                result.setdefault('website_id', sites.id)
        return result

    def _check_owner(self):
        check_operator(self.env)
        self.ensure_one()
        if self.create_uid != self.env.user or not self.env.user.active:
            raise AccessError(_('Solo el operador que creó el lote puede usarlo o descargar sus accesos.'))

    def _store(self, values):
        return super(EmployeeBatch, self.sudo()).write(values)

    def _edit(self):
        self._check_owner()
        if self.state in ('queued', 'done'):
            raise ValidationError(_('El lote ya fue confirmado. Consultá su avance o resultado; no vuelvas a cargarlo.'))
        self.env.cr.execute('SELECT id FROM lafija_employee_batch WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        if self.state in ('queued', 'done'):
            raise ValidationError(_('El lote ya fue confirmado. Volvé a abrir su resultado.'))

    def _invalidate_preview(self):
        self._edit()
        self._store({'state': 'draft', 'validation_hash': False, 'notice': False})

    @api.model_create_multi
    def create(self, vals_list):
        check_operator(self.env)
        for vals in vals_list:
            if set(vals) - _INPUTS:
                raise AccessError(_('El estado y el resultado los registra el proceso del lote.'))
            self._check_source(vals)
        context = {key: value for key, value in self.env.context.items()
                   if not key.startswith('default_') or key[8:] in {'customer_company_id', 'website_id', 'prefix'}}
        return super(EmployeeBatch, self.with_context(context)).create(vals_list)

    @api.model
    def _check_source(self, values):
        # Rechazar columnas prohibidas y límites antes de persistir el archivo.
        # La vista previa por fila sigue siendo un paso explícito independiente.
        if values.get('source_text'):
            padron_io.parse_padron(values['source_text'])
        if values.get('upload'):
            try:
                raw = base64.b64decode(values['upload'], validate=True)
            except ValueError:
                raise ValidationError(_('No se pudo leer el archivo CSV.')) from None
            padron_io.parse_padron(raw)

    def write(self, values):
        if set(values) - _INPUTS:
            raise AccessError(_('El estado y el resultado los registra el proceso del lote.'))
        self._check_source(values)
        for batch in self:
            batch._invalidate_preview()
        return super().write(values)

    @api.onchange('customer_company_id', 'website_id', 'prefix', 'source_text', 'upload', 'line_ids', 'confirm_duplicate_names')
    def _onchange_preview(self):
        if self.state not in ('queued', 'done'):
            self.state = 'draft'
            self.notice = False

    def _reload(self):
        return {'type': 'ir.actions.client', 'tag': 'lf_batch_reload', 'params': {
            'form': {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                     'view_mode': 'form', 'target': 'current', 'name': self.name}}}

    def action_load(self):
        self._edit()
        if bool(self.upload) == bool((self.source_text or '').strip()):
            raise ValidationError(_('Elegí un archivo CSV o pegá el padrón, una sola entrada.'))
        try:
            raw = base64.b64decode(self.upload, validate=True) if self.upload else self.source_text
        except ValueError:
            raise ValidationError(_('No se pudo leer el archivo CSV.')) from None
        rows = padron_io.parse_padron(raw)
        self._store({'line_ids': [Command.clear()] + [Command.create(row) for row in rows],
                     'state': 'draft', 'validation_hash': False, 'confirm_duplicate_names': False})
        return self.action_validate()

    def _fingerprint(self):
        data = [self.customer_company_id.id, self.website_id.id, self.prefix, self.confirm_duplicate_names,
                [(r.id, r.name, r.login, r.legajo) for r in self.line_ids]]
        return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()

    def _validate_rows(self, *, propose):
        problems = []
        if not self.customer_company_id.active or not self.customer_company_id.is_company or not self.website_id.lf_corporate_site:
            problems.append('Elegí una empresa cliente activa y un sitio corporativo.')
        if not 1 <= len(self.line_ids) <= padron_io.MAX_ROWS:
            problems.append(f'El lote necesita entre 1 y {padron_io.MAX_ROWS} filas. Cargá un padrón más grande en varios envíos, cada uno con su vista previa, confirmación y CSV de accesos.')
        service = self.env['lafija.employee.onboarding']
        names = Counter(padron_io.normal_name(r.name) for r in self.line_ids)
        used = set()
        for row in self.line_ids:
            errors, warnings = [], []
            login = (row.login or '').strip()
            generated = not login or login == row.sudo().generated_login
            if not (row.name or '').strip() or len(row.name or '') > 256:
                errors.append('Completá un nombre de hasta 256 caracteres.')
            if row.legajo and login and not generated:
                errors.append('Usá usuario explícito o legajo para proponerlo, no ambos.')
            if generated and propose:
                prefix = (self.prefix or '').strip().lower()
                stem = padron_io.identifier(row.legajo or row.name or '')
                if not padron_io.safe_login(prefix) or not stem:
                    errors.append('Indicá un prefijo que empiece con una letra y un nombre o legajo utilizable.')
                else:
                    base = (prefix + '.' + stem)[:118]
                    login = base
                    suffix = 2
                    while login in used or service._existing_logins([login]):
                        login = f'{base}.{suffix}'
                        suffix += 1
                    if login != base:
                        warnings.append('Se agregó un sufijo porque la propuesta ya estaba en uso. Revisá que corresponda a una persona nueva.')
                    row._store({'login': login, 'generated_login': login})
            if not padron_io.safe_login(login):
                errors.append('El usuario debe empezar con una letra y usar letras sin acentos, números, punto, guion o guion bajo (hasta 128).')
            if login in used:
                errors.append('Usuario repetido en el lote. Elegí identificadores distintos.')
            used.add(login)
            if names[padron_io.normal_name(row.name)] > 1:
                warnings.append('Nombre repetido: confirmá que son personas diferentes con usuarios distintos.')
                if not self.confirm_duplicate_names:
                    errors.append('Falta confirmar los nombres repetidos.')
            row._store({'error': '\n'.join(errors), 'warning': '\n'.join(warnings)})
            if errors:
                problems.append(f'Fila {row.row_number}: ' + ' '.join(errors))
        existing = service._existing_logins(self.line_ids.mapped('login'))
        for row in self.line_ids.filtered(lambda r: r.login in existing):
            row._store({'error': '\n'.join(filter(None, [row.error, 'Usuario ya existente (también puede estar archivado o en otro sitio).']))})
            problems.append(f'Fila {row.row_number}: usuario ya existente.')
        return problems

    def action_validate(self):
        self._edit()
        problems = self._validate_rows(propose=True)
        self._store({'state': 'draft' if problems else 'validated',
                     'validation_hash': False if problems else self._fingerprint(),
                     'notice': ('Revisá las filas señaladas. No se creó ninguna cuenta. ' + ' '.join(problems[:5]) if problems else
                                'Vista previa validada. Confirmá para crear todas las cuentas en segundo plano.')})
        return self._reload()

    def action_confirm(self):
        self._check_owner()
        if self.state in ('queued', 'done'):
            return self._reload()
        self._edit()
        if self.state != 'validated' or self.sudo().validation_hash != self._fingerprint():
            raise ValidationError(_('La vista previa cambió. Volvé a validar antes de confirmar.'))
        problems = self._validate_rows(propose=False)
        if problems:
            self._store({'state': 'draft', 'validation_hash': False, 'notice': 'La validación cambió. Revisá las filas antes de confirmar.'})
            return self._reload()
        progress = self.env['lafija.employee.batch.progress'].sudo().create({'batch_id': self.id})
        self._store({'state': 'queued', 'progress_id': progress.id, 'credential_token': uuid.uuid4().hex,
                     'notice': 'En segundo plano. Podés cerrar esta pestaña; volver a confirmar no duplica el lote.'})
        self.message_post(body=f'Lote {self.name} confirmado para procesar {len(self.line_ids)} personas. Empresa: {self.customer_company_id.name}. Sitio: {self.website_id.name}.',
                          subtype_xmlid='mail.mt_note')
        self.env.ref('kai_viandas.cron_employee_batch').sudo()._trigger()
        return self._reload()

    def _create_all(self, progress=None):
        """Una transacción para todas las identidades; ningún commit por fila."""
        started = time.monotonic()

        def check_budget():
            if time.monotonic() - started >= MAX_RUN_SECONDS:
                raise ValidationError('El proceso superó su tiempo de trabajo. No se confirmó ninguna alta.')

        self._check_owner()
        if self.state != 'queued':
            return
        service = self.env['lafija.employee.onboarding']
        service._lock_logins(self.line_ids.mapped('login'))
        if self._validate_rows(propose=False):
            raise ValidationError(_('El padrón cambió desde la confirmación. Volvé a validarlo.'))
        credentials = []
        for number, row in enumerate(self.line_ids, 1):
            check_budget()
            password = str(secrets.randbelow(900000) + 100000)
            partner, user = service._create_identity(
                name=row.name, login=row.login, password=password, company=self.customer_company_id,
                website=self.website_id, reason='Alta desde padrón', batch_reference=self.name)
            row._store({'partner_id': partner.id, 'user_id': user.id})
            credentials.append((row.name, row.login, password))
            if progress:
                progress(number)
        check_budget()
        data = padron_io.credentials_csv(self.name, self.customer_company_id.name, self.website_id.get_base_url(), credentials)
        padron_io.publish_credentials(self.env.cr.dbname, self.sudo().credential_token, data)
        now = fields.Datetime.now()
        self._store({'state': 'done', 'completed_at': now, 'credentials_until': now + timedelta(seconds=padron_io.CREDENTIAL_SECONDS),
                     'source_text': False, 'upload': False,
                     'notice': 'Todas las altas fueron confirmadas. Descargá el CSV dentro de los 15 minutos; después, los accesos se recuperan por restablecimiento.'})
        self.message_post(body=f'Lote {self.name}: {len(self.line_ids)} altas confirmadas. Cada fila conserva su contacto y cuenta. Las credenciales no forman parte de esta auditoría.', subtype_xmlid='mail.mt_note')

    @api.model
    def _run_one(self, batch_id):
        """Ejecutor de cron con cursor propio; el progreso usa otra transacción."""
        registry = self.env.registry
        progress_id = None
        try:
            with registry.cursor() as cr:
                cr.execute("SELECT id, create_uid, progress_id FROM lafija_employee_batch WHERE id=%s AND state='queued' FOR UPDATE SKIP LOCKED", [batch_id])
                row = cr.fetchone()
                if not row:
                    return False
                _, owner_id, progress_id = row
                run_env = api.Environment(cr, owner_id, {})
                batch = run_env[self._name].browse(batch_id)
                with registry.cursor() as monitor:
                    monitor.execute('UPDATE lafija_employee_batch_progress SET attempt=attempt+1, processed=0, updated_at=NOW() WHERE id=%s RETURNING attempt', [progress_id])
                    attempt = monitor.fetchone()[0]
                    monitor.commit()
                if attempt > 3:
                    raise ValidationError('Se interrumpieron tres intentos. Revisá los límites del proceso antes de reintentar.')
                last_report = [0.0]
                def report(number):
                    if time.monotonic() - last_report[0] >= 1 or number == len(batch.line_ids):
                        with registry.cursor() as monitor:
                            monitor.execute('UPDATE lafija_employee_batch_progress SET processed=%s, updated_at=NOW() WHERE id=%s', [number, progress_id])
                            monitor.commit()
                        last_report[0] = time.monotonic()
                batch._create_all(progress=report)
                cr.commit()
            _logger.info('LAFIJA_PADRON_DONE batch=%s', batch_id)
        except Exception as error:
            # No registrar str(error), argumentos, CSV, valores de creación ni
            # traceback con datos de otros addons: podrían contener credenciales.
            _logger.error('LAFIJA_PADRON_FAILED batch=%s exception_type=%s', batch_id, type(error).__name__)
            with registry.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_root').id, {})
                batch = env[self._name].browse(batch_id).exists()
                if batch and batch.state == 'queued':
                    batch._store({'state': 'failed', 'validation_hash': False,
                                  'notice': 'El lote no pudo completarse. No se creó ninguna cuenta. Volvé a validar; si se repite, pedí al administrador que revise el registro LAFIJA_PADRON_FAILED.'})
                    batch.message_post(body=f'Lote {batch.name}: intento fallido, cero altas confirmadas. Tipo de incidencia: {type(error).__name__}.', subtype_xmlid='mail.mt_note')
                    if batch.sudo().credential_token:
                        padron_io.credential_path(cr.dbname, batch.sudo().credential_token).unlink(missing_ok=True)
                cr.commit()
        return True

    @api.model
    def _set_cron_interval(self):
        """Aplicar el intervalo fijo al instalar/actualizar, incluso con noupdate.

        No reactivar tareas neutralizadas ni cambiar ejecutor, próxima corrida
        o disparos ya pendientes.
        """
        cron = self.env.ref('kai_viandas.cron_employee_batch').sudo()
        if (cron.interval_number, cron.interval_type) != (1, 'hours'):
            cron.write({'interval_number': 1, 'interval_type': 'hours'})

    @api.model
    def _cron_process(self):
        padron_io.purge_credentials(self.env.cr.dbname)
        for batch in self.sudo().search([('state', '=', 'queued')], order='id', limit=10):
            if self._run_one(batch.id):
                break
        if self.sudo().search_count([('state', '=', 'queued')]):
            self.env.ref('kai_viandas.cron_employee_batch').sudo()._trigger()

    def _credentials(self):
        self._check_owner()
        if self.state != 'done' or not self.credentials_until or fields.Datetime.now() >= self.credentials_until:
            raise AccessError(_('El CSV ya no está disponible. Recuperá los accesos con Cambiar contraseña en el menú de acciones.'))
        try:
            path = padron_io.credential_path(self.env.cr.dbname, self.sudo().credential_token)
            return path.read_bytes()
        except FileNotFoundError:
            raise AccessError(_('El archivo temporal ya no está disponible. Recuperá los accesos por restablecimiento; el lote no se vuelve a crear.')) from None

    def action_download(self):
        self._credentials()
        return {'type': 'ir.actions.act_url', 'url': f'/lafija/padron/{self.id}/credenciales', 'target': 'download'}


class EmployeeBatchLine(models.Model):
    _name = 'lafija.employee.batch.line'
    _description = 'Persona del padrón'
    _order = 'row_number, id'

    batch_id = fields.Many2one('lafija.employee.batch', required=True, ondelete='cascade')
    row_number = fields.Integer('Fila', required=True)
    name = fields.Char('Nombre')
    login = fields.Char('Usuario definitivo propuesto')
    legajo = fields.Char('Legajo (opcional)')
    generated_login = fields.Char(readonly=True, groups='base.group_system')
    error = fields.Text('Errores', readonly=True)
    warning = fields.Text('Advertencias', readonly=True)
    partner_id = fields.Many2one('res.partner', 'Empleado creado', readonly=True, ondelete='restrict')
    user_id = fields.Many2one('res.users', 'Cuenta creada', readonly=True, ondelete='restrict')

    def _store(self, values):
        return super(EmployeeBatchLine, self.sudo()).write(values)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if set(values) - _LINE_INPUTS:
                raise AccessError(_('El resultado de la fila lo registra el proceso del lote.'))
            batch = self.env['lafija.employee.batch'].browse(values['batch_id'])
            if not self.env.su:
                batch._invalidate_preview()
        context = {key: value for key, value in self.env.context.items()
                   if not key.startswith('default_') or key[8:] in _LINE_INPUTS}
        return super(EmployeeBatchLine, self.with_context(context)).create(vals_list)

    def write(self, values):
        if set(values) - (_LINE_INPUTS - {'batch_id'}):
            raise AccessError(_('Solo se pueden corregir los datos de entrada de la misma fila.'))
        for batch in self.batch_id:
            batch._invalidate_preview()
        return super().write(values)

    def unlink(self):
        if not self.env.su:
            for batch in self.batch_id:
                batch._invalidate_preview()
        return super().unlink()


class EmployeeBatchProgress(models.Model):
    _name = 'lafija.employee.batch.progress'
    _description = 'Avance provisional del padrón'

    batch_id = fields.Many2one('lafija.employee.batch', required=True, ondelete='cascade')
    processed = fields.Integer(default=0)
    attempt = fields.Integer(default=0)
    updated_at = fields.Datetime()
