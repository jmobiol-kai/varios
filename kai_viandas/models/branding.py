"""Marca configurada del sitio: solo su logo, nunca imágenes de otros registros."""
import base64
from functools import lru_cache
from hashlib import sha256
from io import BytesIO

from lxml import etree
from PIL import Image, UnidentifiedImageError

from odoo import models
from odoo.http import request
from odoo.tools.mimetypes import guess_mimetype


@lru_cache(maxsize=16)
def logo_payload(encoded):
    """Caché por contenido, válida también tras cambiar el logo sin reiniciar.

    No modifica el archivo configurado. Omite visualmente un borde blanco
    uniforme y muy fino del raster original; no recorta dibujos ni los SVG.
    """
    if not encoded or len(encoded) > 4 * 1024 * 1024:
        return None
    try:
        content = base64.b64decode(encoded, validate=True)
        mimetype = guess_mimetype(content)
        clip = 0
        if mimetype == 'image/svg+xml':
            if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
                return None
            root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
            if etree.QName(root).localname != 'svg':
                return None
            for node in root.iter():
                if not isinstance(node.tag, str):
                    continue
                if etree.QName(node).localname.lower() in ('script', 'foreignobject'):
                    return None
                for name, value in node.attrib.items():
                    name = etree.QName(name).localname.lower()
                    if name.startswith('on') or (name == 'href' and not value.startswith('#')):
                        return None
        elif mimetype in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
            with Image.open(BytesIO(content)) as im:
                if im.width * im.height > 16_000_000:
                    return None
                # Tres filas blancas en el logo actual causaban la raya suelta.
                # Solo presentación, y solo si termina antes del 5% del alto.
                rgb = im.convert('RGB')
                limit = min(8, max(1, im.height // 20))
                y = 0
                while y < limit and rgb.crop((0, y, im.width, y + 1)).getextrema() == ((255, 255),) * 3:
                    y += 1
                if 0 < y < limit:
                    clip = round(100 * y / im.height, 4)
        else:
            return None
        return content, mimetype, sha256(content).hexdigest(), clip
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError, etree.XMLSyntaxError):
        return None


class Website(models.Model):
    _inherit = 'website'

    def _lf_logo(self):
        self.ensure_one()
        encoded = self.sudo().with_context(bin_size=False).logo
        if not encoded or encoded == self._default_logo():
            return None
        return logo_payload(encoded)


class QWeb(models.AbstractModel):
    _inherit = 'ir.qweb'

    def _lf_brand(self):
        if not request:
            return False
        if not hasattr(request, '_lf_brand_values'):
            site_id, corporate = self.env['website']._lf_host_site(request.httprequest.host)
            payload = self.env['website'].sudo().browse(site_id)._lf_logo() if corporate else None
            request._lf_brand_values = ({
                'url': '/viandas/marca/' + payload[2] + '/logo',
                # Un píxel adicional evita la línea del suavizado al reducir.
                'clip': f'clip-path:inset(calc({payload[3]}% + 1px) 0 0 0)' if payload[3] else '',
            } if payload else False)
        return request._lf_brand_values
