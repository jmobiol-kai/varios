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
* Una foto sin texto sí crea una sugerencia. Si la interpretación de fotos
  está apagada, el tipo no es jpeg/png/webp o el archivo supera el máximo,
  el texto dice que una persona tiene que mirar la foto. No se adivina el
  producto. Un adjunto que no es imagen y no tiene texto no crea sugerencia.
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
modelo ``gemini-2.5-flash-lite``. Ese preset marca que el modelo puede leer
fotos, pero deja **Interpret customer photos** y **Enabled** apagados.
El preset Grok no completa URL, modelo ni lectura de fotos: hay que cargarlos
a mano si el endpoint que se use acepta imágenes. No guarda una clave.
La llamada es ``POST {base}/chat/completions`` con ``response_format``
``json_object`` y el token en ``Authorization``. No se manda la clave en la URL.
Si la respuesta trae ``usage.prompt_tokens``, ``completion_tokens``,
``prompt_tokens_details.cached_tokens`` o ``completion_tokens_details.reasoning_tokens``,
se guardan. Si un número no viene, queda desconocido: no se anota como cero.

Medición y reporte mensual
==========================

Una consulta facturable es un mensaje entrante del cliente, una sola vez por
id de WhatsApp. Si ese mensaje trae una foto, la consulta queda marcada como
consulta de imagen aunque la foto no se haya mandado al modelo. El reporte
mensual muestra **Image consultations** aparte de **Consultations**. Un
reintento del modelo no abre otra consulta. Cada llamada guarda cuántas
fotos se mandaron de verdad (cero si se derivó la foto). Si el proveedor
informa ``prompt_tokens_details.image_tokens``, se guardan; si no, el conteo
de tokens de imagen queda desconocido. Los ``prompt_tokens`` se guardan
enteros cuando vienen, y ahí ya incluyen lo que el proveedor contó por la foto.
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
cuenta, etiqueta de cliente, cantidad de consultas, consultas de imagen e
importe a facturar si existe. No muestra proveedor, modelo, tokens ni costo
interno.
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

Envases, tapas y descuento por volumen
=======================================

El precio sale de la lista de precios del contacto (``property_product_pricelist``),
que es la que define si ese cliente es B2B o B2C. Los escalones son las reglas
de Odoo con **Min. Quantity** (``min_quantity``), expresadas en la unidad del
producto. El módulo pide el precio a Odoo con ``_get_product_price`` para la
cantidad pedida y para cada mínimo cargado. No calcula un descuento propio:
si los dos precios de Odoo coinciden, dice que no hay descuento por volumen
cargado.

Odoo 19 Community no trae un modelo de bulto en ``product``. La ficha del
producto tiene **Units per pack**. Si el cliente pide cajas y ese dato está
vacío, la sugerencia pregunta. No inventa cuántas unidades entran.

**Product sheets**, **Activity guide** y **Jar and closure fit** los puede
cargar un usuario de WhatsApp AI. La ficha tiene capacidad (ml o cc),
material (vidrio, PET, PP), diámetro de boca en mm, tipo de rosca (TO /
twist-off o rosca), alto y diámetro, color, apto alimento, llenado en
caliente, pasteurización, usos, unidades por bulto y pedido mínimo. Qué
tapa va con qué envase sigue en **Jar and closure fit**. Si el dato no está,
la sugerencia pregunta o deriva a una persona. No completa la ficha por su
cuenta.

Fotos del cliente
=================

**Interpret customer photos** está apagado. Solo lo ve el administrador, por
compañía o por cuenta, igual que el resto del proveedor. También se cargan
el máximo en bytes (4 MB por defecto) y los tipos ``image/jpeg``,
``image/png`` y ``image/webp``.

La foto se lee del ``ir.attachment`` del ``mail.message`` de la conversación.
Odoo Mates la guarda ahí cuando el puente QR manda ``media`` (nombre, tipo y
base64): ``om_whatsapp_base`` la decodifica y la adjunta con ``message_post``.
No se usa la foto de perfil del canal. Si hay epígrafe, se usan los dos.
Si la foto se acepta, va en el mensaje del usuario como parte
``image_url`` con un data URL base64, el formato de la API compatible con
OpenAI. Gemini Flash-Lite acepta ese formato. La clave no viaja en la URL
ni en el texto que se guarda si el proveedor falla.

Encender esto manda la foto del cliente al proveedor externo. El formulario
lo dice. Conviene un plan pago que no entrene con esos datos. Igual hay que
avisarle al cliente por el canal que corresponda: ocultar el proveedor en
Odoo no reemplaza ese aviso.

La sugerencia sigue sin enviarse sola. **Send reply** lo aprieta una persona.

Planilla para Date SRL
======================

``data/templates/date_srl_fichas_producto.xlsx`` y los CSV del mismo
directorio. No traen productos: Date SRL completa una fila por producto que
ya exista en Odoo, con su referencia interna.

La hoja **Instrucciones** explica las columnas. La hoja **Fichas** y
``date_srl_fichas_producto.csv`` tienen en la fila 1 los nombres que Odoo
importa y en la fila 2 la explicación y los valores permitidos. Hay que
borrar la fila 2 antes de importar. La columna ``product_name`` y
``compatible_closure_refs`` no se mapean: la primera es para quien llena la
planilla y la segunda es un recordatorio. La compatibilidad se importa
aparte, desde la hoja **Compatibilidad** o
``date_srl_compatibilidad.csv``, también borrando la fila 2.

Importar fichas:

1. Crear los productos en Odoo con **Internal Reference** igual a
   ``product_id/default_code``. Marcar **Can be Sold**.
2. Borrar la fila 2 del CSV (o de la hoja, si se exporta solo esa hoja).
3. **WhatsApp → Product sheets** (modelo ``kai.whatsapp.ai.spec``), menú de
   la lista (engranaje) → **Import records**.
4. Subir el archivo. La primera fila debe quedar como nombres de campo.
5. Mapear ``product_id/default_code`` al producto. Dejar sin mapear
   ``product_name`` y ``compatible_closure_refs``.
6. Valores: ``role`` es ``jar``, ``closure`` u ``other``. ``material`` es
   ``glass`` (vidrio), ``pet``, ``pp``, ``other`` o ``unknown``.
   ``thread_type`` es ``to`` (TO / twist-off), ``rosca``, ``other`` o
   ``unknown``. ``food_grade``, ``hot_fill`` y ``pasteurization`` son
   ``yes``, ``no`` o ``unknown``. ``capacity_uom`` es texto, por ejemplo
   ``ml`` o ``cc``. Lo que no esté medido se deja vacío o ``unknown``: no
   se completa con un valor supuesto.
7. Probar la importación. Si la referencia no existe, no se crea el producto.

Importar compatibilidad en **Jar and closure fit**
(``kai.whatsapp.ai.fit``): ``jar_product_id/default_code`` y
``closure_product_id/default_code`` tienen que ser referencias ya cargadas.
``note`` es el único texto que la sugerencia puede repetir sobre ese par.

Actualizar una base que ya tiene ``19.0.1.2.0``
================================================

1. Dejar **Enabled** y **Interpret customer photos** apagados.
2. Actualizar el código de la rama y, en Odoo, actualizar el módulo
   ``kai_whatsapp_ai``. No hace falta desinstalar. Las fichas anteriores
   quedan; los campos nuevos nacen vacíos o en **Not loaded**.
3. Completar boca, rosca, medidas, color y pedido mínimo, o importar la
   planilla.
4. Recién después, si corresponde, marcar **Provider can read photos** y
   **Interpret customer photos**, y volver a activar el proveedor a mano.

Actualizar una base que ya tiene ``19.0.1.1.0``
================================================

1. Dejar **Enabled** apagado.
2. Actualizar el código de la rama y, en Odoo, actualizar el módulo
   ``kai_whatsapp_ai`` (Apps, actualizar lista, Upgrade). No hace falta
   desinstalar. Las sugerencias y la medición anteriores quedan.
3. Cargar fichas, guía por actividad y compatibilidad de tapas.
4. En la lista de precios de cada contacto, cargar los mínimos de cantidad.
5. Recién después, si corresponde, volver a pegar la clave y activar el
   proveedor a mano.

Entrenamiento del dueño
=======================

El dueño no se identifica con una frase. Un cliente que escribe «soy el dueño»
sigue siendo un cliente. Entran al entrenamiento solo las personas cargadas en
**WhatsApp → Configuration → Entrenadores**: un usuario interno de Odoo, un
número de WhatsApp en formato internacional, o los dos. La lista la carga un
administrador, por compañía.

En Odoo el agente es un contacto de Discuss, **Agente IA**, armado como
OdooBot: usuario interno sin contraseña y sin licencia (queda inactivo, igual
que el usuario de OdooBot), con avatar, y visible en **Mensajes directos**.
Al entrar a Conversaciones se abre ese chat. Si quien escribe está en
Entrenadores, es entrenamiento. Si no, el agente contesta una frase fija y no
llama al modelo ni cuenta una consulta. Los mensajes del propio agente no
vuelven a entrar, así que no hay un bucle.

Ese chat es interno: cuando el proveedor está encendido, el agente responde
solo. Primero deja «Pensando…» y el cron, con el tope de 15 segundos, publica
la respuesta. Si el proveedor está apagado, no hay llamada ni consulta; los
comandos locales igual andan.

Por WhatsApp, el número autorizado va a entrenamiento en lugar de una
sugerencia de cliente. **Responder automáticamente al entrenador** nace
apagado: la respuesta queda para que una persona apriete **Send reply** en
**Respuestas al entrenador**. Encenderlo no manda nada a los clientes.

El agente propone reglas (título, texto, alcance, prioridad) en estado
**propuesta**. Pasan a **activa** solo si el entrenador responde ``confirmar``
o ``confirmar N``, o aprieta **Confirmar** en **Reglas del agente**.
``mostrar reglas`` y ``borrar regla N`` también andan por WhatsApp o por ese
chat. Cada regla guarda quién la creó, quién la confirmó, el canal, y el
historial en el chatter.

Una regla no puede fijar un precio, un descuento, una ficha técnica, el stock,
la seguridad, el proveedor ni el envío automático. Si lo intenta, queda
marcada y no se puede confirmar. Aunque alguien la active a mano, no entra en
la sugerencia al cliente. Las reglas activas que sí sirven se agregan al
pedido del modelo, solo las globales y las que coinciden con el producto, la
categoría o la actividad, con un tope de tamaño. El precio, la tarifa, el
stock y la ficha siguen saliendo de Odoo.

Esas consultas se cuentan igual que las de un cliente. El reporte mensual no
tiene una columna ni una categoría aparte. En la llamada al proveedor queda
una marca interna, que ese reporte no muestra.

Actualizar una base que ya tiene ``19.0.1.3.0``
================================================

1. Dejar **Enabled** y **Responder automáticamente al entrenador** apagados.
2. Actualizar el módulo ``kai_whatsapp_ai``. Aparece el contacto **Agente IA**.
3. Cargar **Entrenadores**.
4. El dueño abre **Mensajes directos** y le escribe al agente. Las reglas
   quedan propuestas hasta que las confirma.

Traducción al español (19.0.1.5.0)
==================================

Los menús y las listas que se veían en inglés tienen traducción en
``i18n/es.po``. Odoo la carga para ``es_AR`` y para ``es_ES``: es el archivo
base del español. No hay un ``es_AR.po`` ni un ``es_ES.po`` aparte porque
estas etiquetas son las mismas (Mensajes, Configuración, Sugerencias de IA).

Los textos que ya estaban en español (Reglas del agente, Respuestas al
entrenador, Entrenadores) no se tocan.

En ``om_whatsapp_base`` el único agregado es ``i18n/es.po`` y la versión
``19.0.1.1.1``, para que la actualización del módulo importe Mensajes, Plantillas,
Configuración, Documento, Mensaje y Estado de WhatsApp. No cambia el conector.

Actualizar una base que ya tiene ``19.0.1.4.0``
================================================

1. Dejar el proveedor apagado. No hace falta tocar crons: este cambio no
   los reescribe.
2. Copiar el código y, en Odoo, actualizar la lista de aplicaciones.
3. Actualizar ``kai_whatsapp_ai`` y ``om_whatsapp_base``. No reinstalar.
4. Recargar el navegador. El idioma del usuario tiene que ser español
   (Argentina) o español (España).

Pruebas
=======

Sin Odoo, desde la raíz del repositorio::

    python -m unittest discover -s kai_whatsapp_ai/standalone_tests -v

Cubren proveedor apagado, mensajes propios, duplicados, otra compañía,
precio del modelo ignorado, FAQ textual, unidad incorrecta, inyección de
instrucciones, el secreto fuera del error, el preset de Gemini, el consumo
desconocido, el reintento sin otra consulta, la tarjeta de precio histórica,
el corte de mes en ``America/Argentina/Buenos_Aires``, el armado de la foto
en el mensaje, el rechazo por tamaño o tipo, la derivación si la foto está
apagada, el conteo de fotos, el número autorizado, el intento de hacerse
pasar por dueño, la confirmación de una regla, el rechazo de un precio
inventado, el tope de reglas en el pedido y que el entrenamiento suma como
una consulta común. También el chat directo: entrenador, no entrenador y el
agente que no se responde a sí mismo.

``kai_whatsapp_ai/tests/test_suggestion.py`` es un ``TransactionCase`` de
Odoo 19. En el entorno que armó el módulo no había Odoo ni una base, así que
ese archivo no se ejecutó. No llama a un proveedor real: el HTTP está
simulado.
