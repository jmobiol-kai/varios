========================
WhatsApp AI Suggestions
========================

Sugerencias para mensajes de WhatsApp que ya entraron por Odoo Mates
(``om_whatsapp_base`` y, en 00blinis, ``om_whatsapp_device``). Una persona
revisa el texto y, si corresponde, confirma un presupuesto en borrador.

El módulo no modifica esos addons. Se engancha en
``om.whatsapp.account._om_whatsapp_receive``, que es el método con el que el
webhook del puente QR termina guardando el mensaje. El webhook no llama al
proveedor. Un cron solo prepara el texto de las sugerencias en cola. No hay
envío automático.

Qué hace esta versión
=====================

* Empieza apagada. Sin **Enabled**, un mensaje entrante no llama al proveedor
  y no crea sugerencia.
* Con el proveedor habilitado, el webhook solo deja la sugerencia en cola
  (**Queued**). No espera al proveedor. El cron toma hasta cinco por ejecución,
  cada una con tope de 15 segundos, o una persona usa **Generate suggestion**.
  Si el proveedor falla, el mensaje de WhatsApp ya está guardado.
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

* No responde solo. El cron prepara sugerencias; no envía ni crea pedidos.
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

Gemini 2.5 Flash-Lite, para la primera prueba, se elige en **Provider preset**.
Eso completa la URL ``https://generativelanguage.googleapis.com/v1beta/openai`` y el
modelo ``gemini-2.5-flash-lite``. No guarda una clave y deja **Enabled** apagado:
hay que pegar el secreto de la cuenta de Google y volver a activar a mano.
La llamada es ``POST {base}/chat/completions`` con ``response_format``
``json_object`` y el token en ``Authorization``. No se manda la clave en la URL.
Si la respuesta trae ``usage.prompt_tokens``, ``completion_tokens``,
``prompt_tokens_details.cached_tokens`` o ``completion_tokens_details.reasoning_tokens``,
se guardan. Si un número no viene, queda desconocido: no se anota como cero.

Medición y reporte mensual
==========================

Una consulta facturable es un mensaje de texto entrante del cliente, una sola
vez por id de WhatsApp. Un reintento del modelo no abre otra consulta.
Cada intento del proveedor es una fila que no se edita: fecha UTC, resultado,
latencia, error ya sin secreto, proveedor y modelo de ese momento, y la
tarjeta de precio copiada en esa fila. Cambiar la tarjeta después no reescribe
el historial.

La tarjeta de precio del proveedor está en USD por millón de tokens y la carga
el administrador. Es una estimación, no la factura de Google. Si falta un
consumo que la tarjeta cobra, o falta la tarifa de un consumo informado, el
costo estimado queda desconocido. La tarifa que se le cobra al cliente, por
consulta, también la carga el administrador: hoy no hay un importe. Si no hay
tarifa vigente, el importe a facturar queda desconocido, no cero.

**WhatsApp → Usage summary** lo ve un usuario de la cuenta: mes, compañía,
cuenta, etiqueta de cliente, cantidad de consultas e importe a facturar si
existe. No muestra proveedor, modelo, tokens ni costo interno.
**WhatsApp → Configuration → Monthly usage** arma el mes en la zona horaria
del usuario de Odoo. **Provider calls**, **Provider rate cards** y **Client
rates** son solo del administrador. La lista y la tabla dinámica se exportan
con la exportación normal de Odoo. No se programa el envío del reporte y no
se crea una factura.

El usuario de la empresa cliente no ve el proveedor, la clave, los tokens ni
el costo interno: eso está en los grupos y en las reglas de registro, no solo
en el menú. No reemplaza un aviso de privacidad. Si un modelo externo lee el
mensaje, el cliente final tiene que poder saberlo por el canal que corresponda.

El POST a ``{API base URL}/chat/completions`` lo hace el cron o **Generate
suggestion**, con ``temperature`` 0 y ``response_format`` JSON. El webhook de
WhatsApp no lo hace. No se llama si el proveedor está apagado, si el mensaje
es saliente, si ese id ya tiene sugerencia, o si la sugerencia ya está
**Ready**. El timeout máximo es 15 segundos. Un error no reintenta solo: queda
en **Provider error** y una persona puede volver a pedir **Generate suggestion**.

Quién ve cada cosa: la compañía del registro, y además los **Allowed Users**
de la cuenta. Si la sugerencia tiene conversación, el usuario también tiene
que ser miembro de ese canal. El secreto no lo lee el grupo User. Una
configuración de toda la compañía (cuenta vacía) la ven los usuarios de esa
compañía.

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
instrucciones, el secreto fuera del error, el preset de Gemini, el consumo
desconocido, el reintento sin otra consulta, la tarjeta de precio histórica
y el corte de mes en ``America/Argentina/Buenos_Aires``.

``kai_whatsapp_ai/tests/test_suggestion.py`` es un ``TransactionCase`` de
Odoo 19. En el entorno que armó el módulo no había Odoo ni una base, así que
ese archivo no se ejecutó. No llama a un proveedor real: el HTTP está
simulado.
