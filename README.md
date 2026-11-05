# Addons de Odoo

Este repositorio es una carpeta de addons para Odoo 19 Community. En el servidor, `addons_path` debe apuntar a la raíz de este repositorio, no a la carpeta de un módulo.

Hay dos módulos en la raíz, con el nombre técnico y la licencia del autor. El código de cada uno es el árbol de la revisión citada, sin renombrar archivos y sin cambiar encabezados. Los textos que esos encabezados piden acompañar al programa están en `LICENSES/` y son las copias oficiales de la GNU. Esos archivos no cambian la licencia de ningún módulo.

## whatsapp_mail_messaging

Odoo Whatsapp Connector 19.0.1.0.0 de Cybrosys Techno Solutions.

- Nombre técnico: `whatsapp_mail_messaging`
- Versión del manifiesto: `19.0.1.0.0`
- Autor: Cybrosys Techno Solutions
- Licencia declarada en el manifiesto, en `README.rst` y en la ficha de Odoo Apps: LGPL-3 (`https://www.gnu.org/licenses/lgpl-3.0-standalone.html`)
- Fuente pública del autor: `https://github.com/CybroOdoo/CybroAddons/tree/19.0/whatsapp_mail_messaging`
- Revisión: `381a9d8861d8796ba261179f6cfa766f7f103b37` (23 Sep 2026, mensaje `Sep 23: [UPDT] Feature Updated 'whatsapp_mail_messaging'`)
- Árbol de ese directorio: `25949f8ca3c1e34306d621f2e1999fca662d90ca`
- Ficha de Odoo Apps 19.0: `https://apps.odoo.com/apps/modules/19.0/whatsapp_mail_messaging` (la descarga del ZIP pide iniciar sesión). Esa ficha publica el mismo nombre técnico, autor, versión 19.0.1.0.0 y licencia LGPL-3, con fecha de release 6 Apr 2026. Ese día coincide con el commit inicial `9ec0d3929d80c7615ff3ebc034bbefb9b78b5e84`. El único cambio de la revisión del 23 Sep es agregar `cybrosys_support_client` a `depends`.

El `__manifest__.py`, `README.rst` y los archivos `wizard/whatsapp_send_message.py`, `wizard/portal_share.py`, `wizard/__init__.py` y `__init__.py` traen encabezado LGPL-3. Estos archivos traen encabezado AGPL-3 y se dejaron así: `controllers/__init__.py`, `controllers/whatsapp_mail_messaging.py`, `model/__init__.py`, `model/account_move.py`, `model/res_company.py`, `model/res_config_settings.py`, `model/sale_order.py`, `model/selection_message.py`, `model/website.py`, `wizard/message_mail_composer.py`. Los XML, JS y CSS de este módulo no traen encabezado.

LGPL-3 y AGPL-3 permiten publicar estas copias literales del código fuente. Esta rama conserva los avisos de copyright, de licencia y de ausencia de garantía, y adjunta `LICENSES/LGPL-3.0.txt`, `LICENSES/GPL-3.0.txt` (la LGPL-3 incorpora la GPL-3) y `LICENSES/AGPL-3.0.txt`.

Al confirmar un envío, el módulo abre `https://api.whatsapp.com/send?phone=<número>&text=<texto>` en una pestaña nueva. Quien envía termina el mensaje en WhatsApp Web o en la app de WhatsApp. El código arma ese enlace de salida. No hay bandeja de chat entrante ni webhook que reciba mensajes de WhatsApp.

El número de un contacto sale de `res.partner.phone` (con código de país, porque el enlace lo concatena tal cual). El ícono de la systray abre el asistente `whatsapp.send.message`. En el pedido de venta hay un botón «Send by Whatsapp»; en la lista de cotizaciones el mismo botón arma un texto con varios pedidos cuando todos son del mismo cliente. En una factura publicada (`state == posted`) hay el mismo botón, y en la lista de facturas de cliente el envío de varias exige el mismo cliente. En Compartir (`portal.share`) la opción Whatsapp abre el enlace con la nota y la URL de acceso del documento. El sitio web agrega un ícono en el footer (`website.footer_custom`): el visitante escribe un texto, o elige una plantilla de `selection.message`, y el navegador abre WhatsApp hacia `website.mobile_number`. Las plantillas están en Sitio web → Configuración → Whatsapp Message Templates. La plantilla de pedidos y facturas está en Ajustes, en el bloque Whatsapp (el xpath queda después de `pwa_settings`, que en Odoo 19 Community está en `base_setup`). El ícono de correo de la systray es otro flujo: abre `message.mail.composer`, crea un `mail.mail` y lo envía por el servidor de correo saliente de Odoo.

El módulo deja una nota en el chatter del contacto o del documento. En el asistente de WhatsApp esa nota guarda el texto ya convertido a `%20`. La imagen del contacto se muestra en el asistente y no viaja en el enlace. Las rutas públicas `/whatsapp_message` y `/mobile_number` leen con sudo las plantillas y el teléfono del website. `views/mail_form_views.xml` y `views/res_company_views.xml` están en el directorio y el manifiesto no los carga.

Esa descripción sale de leer el código de la revisión de arriba. No hubo instalación en una base de Odoo, así que el xpath de Ajustes no se probó en un arranque real.

## cybrosys_support_client

Cybrosys Support Assistant 19.0.1.0.1. El manifiesto de `whatsapp_mail_messaging` lo pone en `depends`. Sin este módulo, Odoo no instala el conector.

- Nombre técnico: `cybrosys_support_client`
- Versión del manifiesto: `19.0.1.0.1`
- Autor: Cybrosys Techno Solutions
- Licencia del manifiesto, de `README.rst` y de los `.py`: LGPL-3. Los XML, JS y CSS no traen encabezado.
- Fuente pública del autor: `https://github.com/CybroOdoo/CybroAddons/tree/19.0/cybrosys_support_client`
- Revisión: `daac0d9baef308d9e5fbfb35fc2b3a908cf0b737` (19 Ago 2026, mensaje `Aug 19 [FIX] Updated to Git`)
- Árbol de ese directorio: `b6bf7b39a53fe29b4c9b6aaa053ef23ec113efeb`
- Dependencias del manifiesto: `base` y `web` (Odoo 19 Community). El asistente importa `requests` y `markupsafe`, que vienen con Odoo.

Al instalarse, el módulo carga el parámetro `cybrosys_support_client.endpoint_url` con el valor `https://support.cybrosys.com/help/request`. El propio `README.rst` del módulo dice que no sale nada de la base hasta que un usuario interno pulse Submit o WhatsApp. Submit hace un POST a esa URL. El botón WhatsApp abre `https://wa.me/919074270811` con el texto del formulario. Esta incorporación no abrió el asistente y no llamó a ninguno de los dos destinos.

## Dependencias

`whatsapp_mail_messaging` declara `sale`, `account`, `website`, `sale_management` y `cybrosys_support_client`. Las cuatro primeras están en Odoo 19 Community (`https://github.com/odoo/odoo`, rama `19.0`, directorio `addons/`, licencia LGPL-3). `cybrosys_support_client` está en la raíz de este repositorio.

En ese código de Odoo 19.0, `account` depende de `base_setup` y de `portal`. `website` y `portal` traen `mail`. Hace falta `base_setup` para el bloque de Ajustes. Para el ícono de correo hace falta un servidor de correo saliente. Para el enlace de WhatsApp hace falta que el navegador pueda abrir `api.whatsapp.com`.

Los XML del conector heredan vistas que existen en esa rama de Odoo: `sale.view_order_form`, `sale.view_quotation_tree_with_onboarding`, `account.view_move_form`, `account.view_out_invoice_tree`, `website.view_website_form`, `website.footer_custom`, `portal.portal_share_wizard`, `base.res_config_settings_view_form` y, en archivos que el manifiesto no carga, `base.view_company_form` y `mail.view_mail_form`. El bloque `pwa_settings` está en `base_setup`.

## Cómo probarlo

En una base de Odoo 19 Community: poner la raíz de este repositorio en `addons_path`, actualizar la lista de aplicaciones a mano, instalar `whatsapp_mail_messaging`, cargar `phone` en el contacto y `mobile_number` en el website, y usar el botón. La pestaña de WhatsApp se abre con el texto; el envío se confirma en WhatsApp.

Esta incorporación no instaló el módulo, no inició sesión, no actualizó la lista de aplicaciones, no desplegó a ningún servidor y no envió correos ni mensajes de WhatsApp. La comprobación de esta copia es estática: sintaxis de Python, XML bien formado, rutas del manifiesto y de los assets, imports de los `__init__.py`, y que cada árbol coincide con la revisión citada.
