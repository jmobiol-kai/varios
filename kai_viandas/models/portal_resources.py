"""Versionado de los dos recursos privados, sin abrir rutas de assets adicionales."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from odoo import models


@lru_cache(maxsize=2)
def resource_url(filename):
    # El despliegue reinicia los procesos. No depende de la base ni lee por petición.
    if filename not in ('viandas.css', 'viandas.js'):
        raise ValueError('Recurso no permitido')
    content = (Path(__file__).resolve().parents[1] / 'static' / 'src' / filename).read_bytes()
    return f'/kai_viandas/static/src/{filename}?v={sha256(content).hexdigest()}'


class QWeb(models.AbstractModel):
    _inherit = 'ir.qweb'

    def _lf_resource_url(self, filename):
        return resource_url(filename)
