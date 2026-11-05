========================
WhatsApp AI Suggestions
========================

Sugerencias para mensajes de WhatsApp que ya entraron por Odoo Mates
(``om_whatsapp_base`` y, en 00blinis, ``om_whatsapp_device``). Una persona
revisa el texto y, si corresponde, confirma un presupuesto en borrador.

El módulo no modifica esos addons. Se engancha en
``om.whatsapp.account._om_whatsapp_receive``, que es el método con el que el
webhook del puente QR termina guardando el mensaje. No hay cron y no hay envío
automático.

Qué hace esta versión
=====================

* Empieza apagada. Sin **Enabled**, un mensaje entrante no llama al proveedor
  y no crea sugerencia.
* Con el proveedor habilitado, un mensaje del cliente crea un registro en
  **WhatsApp → AI Suggestions**. El texto propuesto se puede editar.
* **Send reply** es el único envío. Lo aprieta una persona. Usa el
  ``message_post`` de la conversación de Discuss, el mismo camino que ya manda
  WhatsApp. Esta copia del repositorio no apretó ese botón contra una base real.
* **Create draft quotation** crea un ``sale.order`` en borrador, con el
  producto, la unidad de venta y la cantidad ya resueltos. No llama a
  ``action_confirm``. No factura, no cobra y no mueve stock.
* La FAQ y el catálogo son por compañía y, si se elige, por cuenta de
  WhatsApp. Otra compañía no entra en el contexto.
* El precio sale de la tarifa del contacto (``property_product_pricelist``)
  en esa compañía. Si no hay contacto o no hay tarifa, no se inventa un
  número. El stock es ``free_qty`` solo si Inventario está instalado. Si no,
  la sugerencia dice que no hay dato.
* Un mensaje propio (``from_me`` o una notificación saliente), un duplicado
  del mismo id de WhatsApp y un mensaje vacío de cliente no generan otra
  sugerencia.
* El texto del cliente se manda como dato, no como instrucciones. El modelo
  no puede fijar precios, costos ni respuestas de FAQ: la FAQ se copia
  textual si la pregunta coincide por palabras, y el precio que se muestra
  es el de la tarifa.

Qué no hace
===========

* No responde solo, ni de noche ni por cron.
* No confirma el pedido, no crea factura, no reserva mercadería.
* No conoce horarios, medios de pago ni zonas de envío. Esas frases no están
  cargadas. Hay que escribirlas en la FAQ si se quieren usar. Si no hay FAQ
  que coincida, la sugerencia dice que lo tiene que ver una persona.
* No vende en otra unidad distinta de la unidad del producto. Si el cliente
  pide kilos y el producto está en unidades, hace falta una persona.
* No adivina un producto parecido. Si el nombre matchea más de uno, o no está
  en el catálogo habilitado, no arma el presupuesto.
* Un archivo sin texto no crea sugerencia. El mensaje sigue en
  **WhatsApp → Messages**.
* No lee costos, notas internas ni conversaciones de otros números.
* No incluye el conector Meta ni el de WhatsApp Web.
* El solapamiento de palabras de la FAQ es débil. Igual nadie envía sin el
  botón.

Configuración que falta cargar
==============================

No hay datos de negocio en este módulo. Después de instalar, un administrador
de WhatsApp AI (grupo **Administrator** del privilegio **WhatsApp AI**) abre
**WhatsApp → Configuration → AI Provider** y crea un registro:

* **Enabled**: dejarlo apagado hasta tener URL, modelo y secreto.
* **WhatsApp Account**: vacío usa esa configuración para la compañía; con
  cuenta, solo para esa cuenta.
* **API base URL**: raíz compatible con la API de chat completions, sin
  ``/chat/completions``. No hay un valor por defecto y no se crea ninguna
  cuenta de proveedor desde aquí.
* **Model**: el nombre del modelo en ese servicio.
* **API secret**: solo lo ve el grupo **Administrator**. No se copia a la
  sugerencia. Si el proveedor falla, el secreto se saca del texto del error.
* **FAQ**: pregunta y respuesta. Vacío hasta que se escriban los hechos que
  se pueden repetir.
* **Catalog**: productos con **Can be Sold**. Solo esos se pueden citar o
  pedir.

Cada sugerencia, con el proveedor habilitado, hace un POST a
``{API base URL}/chat/completions`` con ``temperature`` 0 y
``response_format`` JSON. No se llama si está apagado, si el mensaje es
saliente o si ese id de WhatsApp ya tiene sugerencia. El timeout por defecto
es 20 segundos y queda dentro del webhook: si el proveedor tarda, el mensaje
de WhatsApp igual se guardó; la sugerencia queda para una persona con el
error, sin reintentos.

Quien aprieta **Send reply** tiene que estar en **Allowed Users** de la
cuenta. Quien aprieta **Create draft quotation** además necesita permiso de
ventas (``sales_team.group_sale_salesman`` o más) y un contacto en la
sugerencia. El contacto se toma de la conversación si el número ya existe en
Odoo. Si no, hay que elegirlo en **Customer** y usar **Refresh prices** antes
del presupuesto.

Menús, en inglés como el resto de la pantalla de WhatsApp:

* **WhatsApp → AI Suggestions**
* **WhatsApp → Configuration → AI Provider**
* Botones: **Send reply**, **Refresh prices**, **Create draft quotation**,
  **Discard**

Pruebas
=======

Sin Odoo, desde la raíz del repositorio::

    python -m unittest discover -s kai_whatsapp_ai/standalone_tests -v

Cubren proveedor apagado, mensajes propios, duplicados, otra compañía,
precio del modelo ignorado, FAQ textual, unidad incorrecta, inyección de
instrucciones y que el secreto no queda en el error.

``kai_whatsapp_ai/tests/test_suggestion.py`` es un ``TransactionCase`` de
Odoo 19. En el entorno que armó el módulo no había Odoo ni una base, así que
ese archivo no se ejecutó. No llama a un proveedor real: el HTTP está
simulado.
