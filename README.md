# Addons de Odoo

Este repositorio es una carpeta de addons para Odoo 19 Community. En el servidor, `addons_path` debe apuntar a la raíz de este repositorio, no a la carpeta de un módulo.

Hay dos módulos de Odoo Mates, con el nombre técnico y la licencia del autor. El código de cada uno es el árbol de la revisión citada, sin renombrar archivos y sin cambiar avisos. Los textos de licencia que acompañan esa publicación están en `LICENSES/` y son las copias oficiales de la GNU. Esos archivos no cambian la licencia de ningún módulo.

La ficha de Odoo Apps pide iniciar sesión para descargar el ZIP. La copia de esta rama sale del repositorio público del autor, `https://github.com/odoomates/odooapps`, rama `19.0`, revisión `18521763dcdfa3dced6cb24dfae893bf896eaa78` (5 Nov 2026, mensaje `[BOT] post-merge updates`). Ese commit no toca estos dos módulos. El árbol de cada uno coincide con el último commit que sí los cambia.

## om_whatsapp_base

WhatsApp Connector Base, de Odoo Mates. El código sigue el manifiesto `1.1` de ese autor, que Odoo 19 adapta a `19.0.1.1`. Esta copia usa `19.0.1.1.1` solo para poder actualizar el módulo e importar `i18n/es.po`. No hay otro cambio de lógica.

- Nombre técnico: `om_whatsapp_base`
- Licencia del manifiesto y de la ficha: LGPL-3 (`https://www.gnu.org/licenses/lgpl-3.0-standalone.html`)
- Autor y mantenedor: Odoo Mates, `odoomates@gmail.com`
- Fuente: `https://github.com/odoomates/odooapps/tree/19.0/om_whatsapp_base`
- Último commit del módulo: `fba5f3cb8447a2e4d954c8e7d71dd8f07fa84793` (23 Oct 2026, mensaje `[IMP] om_whatsapp_base: link the three connectors`)
- Árbol de código: `c8c647c0786d829214585a560058454b0c1ec796`. Encima de eso solo está `i18n/es.po` y la versión `19.0.1.1.1`.
- Ficha: `https://apps.odoo.com/apps/modules/19.0/om_whatsapp_base` (serie 19.0, Community y Enterprise, nombre técnico `om_whatsapp_base`, licencia LGPL-3)
- Dependencias del manifiesto: `mail` y `phone_validation`. Las dos están en Odoo 19 Community (`https://github.com/odoo/odoo`, rama `19.0`, directorio `addons/`, licencia LGPL-3). `phone_validation` depende de `base` y `mail`.

Este módulo trae plantillas, un compositor y el registro de mensajes. Por sí solo envía con Click to Chat: abre `https://wa.me/<número>?text=<texto>` y quien envía confirma en WhatsApp. No manda el mensaje solo y no adjunta archivos por ese camino.

## om_whatsapp_device

WhatsApp Connector QR, versión de manifiesto `1.0`, de Odoo Mates. Depende solo de `om_whatsapp_base`.

- Nombre técnico: `om_whatsapp_device`
- Licencia del manifiesto, de `bridge/package.json` y de la ficha: LGPL-3
- Fuente: `https://github.com/odoomates/odooapps/tree/19.0/om_whatsapp_device`
- Último commit del módulo: `e4736f6efc941539036e01c2b871bb0fa9e51a8a` (2 Nov 2026, mensaje `[FIX] om_whatsapp_device: make the secret at install`)
- Árbol: `a5c9e384873e0c18cd61339020022d1bf5bbd55c`
- Ficha: `https://apps.odoo.com/apps/modules/19.0/om_whatsapp_device` (serie 19.0, Community y Enterprise, on premise, nombre técnico `om_whatsapp_device`, licencia LGPL-3, dependencia comunitaria WhatsApp Connector Base)

El puente Node.js va dentro del módulo, en `om_whatsapp_device/bridge`. `package.json` pide Node.js `>=20` y depende de `@whiskeysockets/baileys` `7.0.0-rc14` (MIT) y `qrcode` `1.5.4`. Baileys habla el protocolo de dispositivo enlazado, el mismo esquema que WhatsApp Web. No es la API oficial de Meta (Cloud API / WhatsApp Business API).

`om_whatsapp` (WhatsApp Connector Meta) y `om_whatsapp_web` (WhatsApp Connector Web) no están en este repositorio. Ningún manifiesto de los dos módulos de esta rama los declara.

El autor advierte que WhatsApp puede bloquear un número que envía demasiado, demasiado rápido, o a quien no lo pidió. El secreto del puente lo genera Odoo en el primer uso (`ir.config_parameter` `om_whatsapp_device.secret`) y se muestra en la cuenta. No hay un secreto escrito en el código.

LGPL-3 permite publicar estas copias literales. Esta rama conserva el aviso de licencia del manifiesto y adjunta `LICENSES/LGPL-3.0.txt` y `LICENSES/GPL-3.0.txt` (la LGPL-3 incorpora la GPL-3).

## Puente y variables

En el servidor de Odoo, con Node.js 20 o posterior:

```
cd /ruta/de/este/repositorio/om_whatsapp_device/bridge
npm ci
npm test
```

El `npm test` del autor usa un WhatsApp falso: no abre el teléfono y no usa la red. Para dejarlo corriendo, una opción es un servicio. El ejemplo no lleva un secreto real. El valor es el que muestra la cuenta en Odoo, pestaña WhatsApp QR.

```
# /etc/om-whatsapp-bridge.env
# chmod 600, y que solo lo lea el usuario del servicio
OM_WA_SECRET=<secreto-que-muestra-odoo>
OM_WA_PORT=8077
OM_WA_HOST=127.0.0.1
OM_WA_DATA=/var/lib/om-whatsapp-bridge
```

| Variable o parámetro | Valor de referencia |
|---|---|
| `OM_WA_SECRET` | obligatorio, 16 caracteres como mínimo; el de `om_whatsapp_device.secret` |
| `OM_WA_PORT` | `8077` |
| `OM_WA_HOST` | `127.0.0.1` |
| `OM_WA_DATA` | carpeta de las claves del dispositivo enlazado; tratarla como una contraseña |
| `om_whatsapp_device.bridge_url` | `http://127.0.0.1:8077` si no se cambia |
| `om_whatsapp_device.odoo_url` | solo si Odoo no escucha en `http://127.0.0.1:<http_port>` |
| `om_whatsapp_device.node` | ruta completa de `node` cuando el de Odoo no está en el `PATH` |
| `om_whatsapp_device.autostart` | lo pone el botón Start the Bridge |

El puente escucha en local y avisa a Odoo en `/om_whatsapp_device/webhook`. La unidad de ejemplo está en `om_whatsapp_device/bridge/om-whatsapp-bridge.service`. El detalle de instalación que escribió el autor está en `om_whatsapp_device/README.rst` y `om_whatsapp_device/bridge/README.md`.

## Cómo probarlo después

En una base de Odoo 19 Community, on premise: poner la raíz de este repositorio en `addons_path`, instalar Node.js 20 o posterior, ejecutar `npm ci` en el puente, reiniciar Odoo, actualizar la lista de aplicaciones a mano e instalar `om_whatsapp_device` (trae `om_whatsapp_base`). Luego crear la cuenta, arrancar el puente y escanear el QR desde WhatsApp, Dispositivos vinculados.

Esta incorporación no instaló el módulo, no reinició servicios, no actualizó la lista de aplicaciones, no desplegó a ningún servidor, no emparejó WhatsApp y no envió mensajes.

## Comprobaciones de esta copia

- Sintaxis de Python, XML bien formado, rutas de datos del manifiesto e imports de los `__init__.py`.
- Cada árbol coincide con la revisión citada.
- `npm test` del puente, con `npm ci --ignore-scripts`, 15 pruebas y 0 fallos, contra un socket falso. Node.js de esa corrida: v22.23.4.
- Los tests de Python del autor (`tests/test_om_whatsapp.py`, `tests/test_om_whatsapp_device.py`) son casos de Odoo (`TransactionCase`, `HttpCase`). No se ejecutaron: no hay una base de Odoo en esta copia.

Los archivos de descripción (`static/description`) son imágenes y HTML del autor. No hay ejecutables sueltos ni un secreto fijo en el código.

## kai_whatsapp_ai

Addon aparte, licencia LGPL-3, versión `19.0.1.7.0`. No cambia la lógica de `om_whatsapp_base` ni de `om_whatsapp_device`.

Al recibir un mensaje de un cliente, si hay un proveedor de IA habilitado, el webhook solo encola una sugerencia. El texto lo pide después un cron o el botón **Generate suggestion**. No envía WhatsApp solo. El envío es el botón **Send reply**. El presupuesto es el botón **Create draft quotation** y queda en borrador: no confirma, no factura y no reserva stock. Cada mensaje entrante cuenta una consulta; cada intento del modelo queda en un registro que no se edita. El reporte mensual está en **WhatsApp → Usage summary** y, para el administrador, en **Configuration → Monthly usage**. No hay tarifa cargada ni factura automática.

Depende de `om_whatsapp_base` y `sale`. El puente QR entra por `_om_whatsapp_receive`, que es el método que ya llama el webhook del dispositivo. Inventario es opcional: si `stock` no está instalado, la sugerencia dice que no hay dato de stock. La lectura de fotos está apagada: si se enciende, la imagen sale del adjunto del mensaje y se manda al proveedor. El reporte mensual separa las consultas que trajeron foto. La planilla vacía para fichas técnicas está en `kai_whatsapp_ai/data/templates/`. El dueño entrena al agente desde el contacto **Agente IA** en Mensajes directos, o desde un número cargado en Entrenadores. Esas consultas se cuentan igual que las de un cliente.

La configuración, las etiquetas y lo que todavía no hace está en `kai_whatsapp_ai/README.rst`. La FAQ y las políticas de horario, pago y envío quedan vacías hasta que alguien las escriba. No hay una clave de API en el repositorio. Esta copia no instaló el módulo ni llamó a ningún proveedor.
