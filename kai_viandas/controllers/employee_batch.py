from odoo import http
from odoo.http import request, content_disposition
from odoo.exceptions import AccessError
from werkzeug.exceptions import Forbidden


class EmployeeBatchDownload(http.Controller):
    @http.route('/lafija/padron/<int:batch_id>/credenciales', type='http', auth='user', methods=['GET'])
    def credentials(self, batch_id, **kwargs):
        batch = request.env['lafija.employee.batch'].browse(batch_id)
        try:
            batch.check_access('read')
            data = batch._credentials()
        except AccessError:
            raise Forbidden('El CSV no está disponible para este acceso o venció su ventana. Si sos el creador del lote, usá Cambiar contraseña en el menú de acciones para establecer una nueva.') from None
        return request.make_response(data, headers=[
            ('Content-Type', 'text/csv; charset=utf-8'),
            ('Content-Disposition', content_disposition(f'{batch.name}-accesos.csv')),
            ('Cache-Control', 'no-store, private, max-age=0'),
            ('Pragma', 'no-cache'), ('X-Content-Type-Options', 'nosniff'),
        ])
