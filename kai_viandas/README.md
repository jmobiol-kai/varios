Versión 19.0.1.17.8. En Pedidos y en las demás listas de viandas, el botón de fila «Editar» (antes «Atender») solo aparece si la vianda requiere atención. En la ficha el botón del encabezado es «Editar» (antes «Atender / corregir») y el asistente se titula «Editar pedido». Si se aplica una elección pendiente (con Editar), la vianda queda vigente, queda el registro en el historial y se suma a la orden de fabricación en borrador de ese plato y día. Esa OF se crea o se ajusta sola cada vez que una vianda queda vigente (portal, asistente o Editar); si cambia el plato o se cancela, se baja o se mueve la cantidad. Si la OF ya está confirmada, una vianda nueva va a otra OF en borrador y una que sale se desvincula con un asiento en la orden. El chef confirma y marca hecha la orden en Manufactura o en Pedidos → Producción del día; al quedar hecha, las viandas pasan a Elaborado. En Pedidos se quitó el botón «Elaborar»; queda «Ver orden» y la columna Órdenes de fabricación como vínculo. Los pedidos de la semana siguiente se cargan hasta el sábado a las 14:00, hora de La Fija; durante esa semana el empleado puede agregar, cambiar o pedir cancelaciones hasta las 10:30 del día del menú, y eso se aplica como vigente aunque la lista ya esté tomada. Después de las 10:30 no puede modificar ese día en el portal; el operador sí, con Editar. Ambos horarios son configurables en Viandas → Horarios de pedido.

Versión 19.0.1.17.6. El presupuesto diario no se arma al confirmar la vianda ni al elaborar. Cuando está Elaborado o Entregado, «Agregar a presupuesto» (fila o selección múltiple) crea o actualiza un presupuesto en borrador por empresa y día, acumulando cantidades. Elaborar sigue juntando el mismo plato y día de todas las empresas en una sola OF. La columna Presupuesto muestra el número como vínculo recién cuando está agregado; Monto solo se ve a partir de ese momento. El presupuesto se confirma en Ventas. En Pedidos, el enlace «Nuevo pedido» (al estilo de Agregar una línea) aparece al final de la lista, debajo de cada empresa expandida y debajo de cada día expandido; el botón «Agregar pedido cliente» del encabezado se mantiene.

Versión 19.0.1.17.5. En Pedidos, el botón «Atender» de la fila solo aparece si la vianda requiere atención. El pedido de venta diario por empresa y día se arma en borrador cuando la vianda queda confirmada, se ajusta si hay un cambio o una cancelación, y se reutiliza y confirma al tomar la lista o Elaborar. La lista muestra la columna Monto (con suma por grupo) y el vínculo al pedido; Pedidos → Ventas lista esos pedidos diarios.

Versión 19.0.1.17.4. En Empleados corporativos se quita el botón «Gestionar acceso» de la ficha y de la lista. La contraseña se cambia con «Cambiar contraseña» en el menú de acciones (el engranaje), igual que en Usuarios, reutilizando el asistente nativo (lista con Nueva contraseña). Empresa cliente, sitio y Habilitado para viandas se editan en la misma ficha.

Versión 19.0.1.17.3. Se quita el menú y el botón «Alta de empleado». El alta se hace con Nuevo en Empleados corporativos: en el mismo formulario se cargan empresa, nombre, usuario, sitio y contraseña del portal, y al guardar queda creada la cuenta. Gestionar acceso se mantiene para restablecer o cambiar el acceso.

Versión 19.0.1.17.2. En Crear pedidos de empleados se quita la etiqueta suelta «Semana» del formulario vacío; los controles de la semana (rango y Semana anterior/siguiente) siguen apareciendo cuando hay empresa y empleado elegidos.

Versión 19.0.1.17.1. En Pedidos se quita «Ver pendientes de cualquier fecha». Junto al título queda el botón visible «Agregar pedido cliente», que abre el asistente Crear pedidos de empleados; se conserva el enlace del pie «Agregar pedido de cliente». Las columnas quedan Empleado, Empresa cliente, Fecha de la vianda, Vianda, Elección vigente y el resto en el mismo orden.

Versión 19.0.1.17.0. La pantalla principal del módulo es Pedidos: un listado de viandas de empleados, agrupado por empresa cliente y fecha, con el conteo de cada grupo. El filtro por defecto muestra lo de hoy en adelante y lo que sigue pendiente, sin las canceladas; se puede quitar para ver todo. Se reutiliza la lista de Hoy, con Elaborar y el enlace «Agregar pedido de cliente» (también con la lista agrupada). El menú queda Pedidos, Menús, Empleados y Ayuda. El ingreso del operador abre Pedidos.

Versión 19.0.1.16.9. Se quitan del menú las entradas «Hoy» y «Alta desde padrón». Quedan Menús, Empleados y Ayuda. Las acciones, modelos, vistas y el JS se conservan para no romper nada y poder restaurarlos después. El ingreso del operador abre Menús del día.

Versión 19.0.1.16.8. Se quita el aviso azul «No hay otros días con menú publicado en esta semana…» del asistente Crear pedidos de empleados. Si no quedan días libres, el enlace Agregar pedido sigue informando que se use Semana siguiente.

Versión 19.0.1.16.7. En Crear pedidos de empleados, el enlace «Agregar pedido» queda siempre visible debajo de la grilla (antes se ocultaba «Agregar una línea» si no quedaba ningún día publicado libre). Si no hay más días en esa semana, avisa que se use Semana siguiente y no agrega un renglón vacío. Si hay días libres, agrega el renglón como hasta ahora. Se conserva el aviso de la semana completa.

Versión 19.0.1.16.6. En Crear pedidos de empleados, Empresa cliente solo lista empresas que tienen empleados corporativos dados de alta y no archivados. El combo Empleado sigue filtrando por la empresa elegida y solo muestra empleados activos.

Versión 19.0.1.16.5. En Hoy, el enlace «Agregar pedido de cliente» se inyecta siempre al pie de la lista (agrupada o no) y abre el asistente Crear pedidos de empleados. Se desactiva la creación nativa de grupos (`group_create="0"` y un parche del ListRenderer) para que no vuelva a aparecer el vínculo «Agrega Empresa cliente» ni su carga en línea.

Versión 19.0.1.16.4. En Hoy, el enlace «Agregar pedido de cliente» (abajo de la lista, agrupada o no) abre el asistente Crear pedidos de empleados. Reemplaza el vínculo nativo «Agrega Empresa cliente» que aparece al agrupar. Se quita el botón de encabezado «Crear pedidos de clientes».

Versión 19.0.1.16.3. «Menús del día» pasa a ser la entrada de primer nivel «Menús» (después de Hoy) y abre la misma acción. Se quitan Preparación (quedaba vacío) y Reservas, con sus ítems Consultar reservas y Preparar cotización; las acciones se conservan. En Hoy, el botón «Crear pedidos de clientes» abre el asistente Crear pedidos de empleados. Las reservas que requieren atención de cualquier fecha se ven con «Ver pendientes de cualquier fecha» desde Hoy.

Versión 19.0.1.16.2. Se saca del menú Viandas la entrada «Pendientes». La acción se conserva: desde Hoy, «Ver pendientes de cualquier fecha»; desde Consultar reservas, el filtro «Requieren atención». Muestra las reservas que requieren atención de cualquier fecha (pasadas, de hoy o futuras).

Versión 19.0.1.16.1. Se sacan del menú Viandas → Preparación las entradas «Listas de preparación» y «Entregas del día». Queda Menús del día. Las listas tomadas, los datos y las acciones siguen disponibles desde el menú del día (Tomar lista, Ver lista tomada, Elaborar y entregar) y desde Hoy.

Versión 19.0.1.16.0. Desde Hoy se puede seleccionar viandas y Elaborar aunque la lista del día no esté tomada: se toma o se incorpora lo necesario, se crean los pedidos diarios por empresa y se confirma una OF por cada plato de la selección. Si hay un borrador y no se eligen todas, se parte (las elegidas quedan confirmadas y el resto en borrador). Las ya en elaboración, elaboradas o entregadas no se modifican.

Versión 19.0.1.15.0. Una sola orden de fabricación en borrador por plato y día, con la cantidad total de viandas de todas las empresas. El origen es la fecha y el plato; la pestaña Viandas muestra los números, las empresas y los pedidos. Elaborar confirma esa orden compartida. Si se suma una reserva con la OF ya confirmada, se crea otra OF en borrador por el resto (no se altera la cantidad confirmada). Al terminar la OF la vianda queda Elaborado; Entregado solo se marca con el botón.

Versión 19.0.1.14.2. El origen de la orden de fabricación es el pedido diario y el número de vianda (por ejemplo, S00643 · V-000075), con vínculos visibles en la OF, el pedido y la lista. Al terminar la OF la vianda queda Elaborado; Entregado solo se marca con el botón. Si la lista ya está tomada, el menú del día muestra un aviso para elaborar y entrega, y la oferta pasa a una pestaña secundaria.

Versión 19.0.1.14.1. Al tomar la lista (y en cada revisión) las viandas por elaborar quedan con una orden de fabricación en borrador, agrupada por plato, empresa y día. Elaborar confirma esa orden y pasa la vianda a En elaboración; Manufactura, al marcarla hecha, la deja Elaborado.

Versión 19.0.1.14.0. Al tomar la lista se crea o actualiza un pedido de venta confirmado por empresa y día (plato a precio de lista; postre y bebida a precio 0). Elaborar confirma la orden de fabricación y deja la vianda en elaboración; Manufactura, al marcarla hecha, la pasa a Elaborado (si se cancela, vuelve a Por elaborar). Entregado valida el remito de ese pedido diario. Preparar cotización del período reutiliza esos pedidos y no crea otra facturación.

Versión 19.0.1.13.4. El menú de aplicaciones del backend se llama Viandas (antes La Fija).

Versión 19.0.1.13.3. Si en la semana ya están en la grilla todos los días con menú publicado, se avisa (por ejemplo: no hay otros días publicados en esa semana para el sitio empresas) y se oculta «Agregar una línea», para que el combo de día no quede vacío.

Versión 19.0.1.13.2. Al guardar un pedido de empleado (el Guardar del encabezado o Guardar pedidos) se aplican las reservas y la grilla se refresca con el día y lo ya reservado. Se puede agregar o quitar renglones; el renglón nuevo pide el día publicado de la semana (sin repetir) y después plato, postre y bebida. Quitar un renglón no anula una reserva existente.

Versión 19.0.1.13.1. Al guardar un pedido de empleado, el formulario se refresca con lo vigente y sigue editable; ya no se pierden las elecciones del primer guardado.

Versión 19.0.1.13.0. El operador puede cargar los pedidos de la semana de un empleado (por ejemplo, los que le pasan por WhatsApp) desde La Fija → Reservas → Crear pedidos de empleados: elige la empresa cliente, el empleado y los platos, postres y bebidas de cada día. Se aplica la misma lógica que el portal (cortes, pendientes y validaciones) y queda registrado que lo cargó el operador.

# La Fija · reservas corporativas para Odoo 19 CE

Versión 19.0.1.12.0. El empleado elige por separado el plato, el postre y la bebida de cada día. Postre y bebida son opcionales e independientes, y solo se pueden pedir si hay un plato. El menú del día tiene tres listas (categorías Viandas, Postre Vianda y Bebida Vianda), con snapshots propios. Después de tomar la lista, cualquier cambio del triple queda pendiente como un todo. La cotización sigue facturando solo el plato; la planilla, el anexo y las etiquetas muestran también postre y bebida, sin importes. En la etiqueta, postre y bebida van en una línea extra más chica, sin recortar el plato. Las reservas anteriores conservan solo el plato.

Versión 19.0.1.12.0. La cuenta corporativa usa una página propia de viandas; productos, usuarios, gestión interna y reportes usan Odoo. No se utiliza el carrito de eCommerce para las reservas. La semana se presenta por días plegables y tarjetas de opción con imagen cuando el producto la tiene. La elección vigente, o la solicitada pendiente, queda preseleccionada; en móvil, Guardar ocupa su propia franja al pie, en flujo y fuera del área desplazable de la semana; no tapa días. Reenviar la misma opción conserva las solicitudes abiertas.

Etiquetas 1.10.0: **una página vertical de 29 × 90 mm por vianda**, con el contenido girado 90° y recuadro. Tres líneas: **dd/mm · empresa**, **empleado** y **plato elegido**, las dos últimas grandes y en negrita. Los textos largos se recortan con puntos suspensivos por CSS; la descripción completa sigue en la revisión. `kai_viandas.paperformat_vianda_label` se aplica únicamente a `kai_viandas.report_labels`: Portrait, márgenes 0, 96 dpi y sin smart shrinking. No cambia el papel de la compañía ni el de la planilla/anexo, que mantienen A4 en la configuración usada. El motor wkhtmltopdf 0.12.6.1 redondea la página a **83 × 255 pt**, con rotación PDF 0; no se compensa ese redondeo. Los PDF ya conservados siguen descargándose con sus bytes y formato anteriores; una nueva generación usa el formato nuevo, incluso si se genera una copia histórica. Referencia, revisión y archivo siguen en el sistema, no en la etiqueta. La calibración física en la Brother corresponde a Mariano.

Ajuste 1.9.2: padrón de hasta **200 personas por envío**, intervalo de cron **una hora** con disparo al confirmar y presupuesto interno **240 s**. Valores fijos; cada envío conserva su vista previa, confirmación y CSV propios. Detalle técnico y medición debajo.

Pulida 1.9.1: opciones con foto primero, seguidas por las filas compactas sin foto; el orden dentro de cada grupo se conserva. En escritorio se aprovecha el espacio lateral cuando hay una o dos fotos; con tres o más se usan filas completas. En móvil sigue una columna y, al elegir con un toque, el encabezado plegado y su borrador quedan visibles. La navegación con flechas mantiene abierto el día. Recalcular un resumen confirma «Resumen actualizado.» con el aviso breve del operador, después de recargar la misma ficha. Los títulos distinguen **Hoy · fecha**, **Consultar reservas** y **Listas de preparación**; el anexo vacío explica las cero viandas sin un encabezado de detalle vacío. No cambia B2, la selección enviada, los criterios comerciales ni los PDF emitidos.

## Módulos de la entrega

- `kai_viandas`: cuentas corporativas individuales o desde padrón, menús, reservas, preparación, correcciones, etiquetas, planilla del día, resumen por empresa/período con cotización y anexo, y protecciones P1/P2/P3.
- `msb_quick_checkout` 19.0.1.2.1: checkout público simplificado; limita reutilización de invitados a su procedencia y conserva al particular autenticado.
- `msb_lafija_quick_checkout` 19.0.1.0.0: conecta la clasificación/protección documental con el checkout. Depende de los otros dos; instalarlo instala el conjunto.

La especificación y la evidencia están en `/data/apps/personal/jmobiol/newvps19/docs/lafija/`. `PLAN-MVP.md` mantiene el alcance; `IMPLEMENTACION-MVP.md` registra resultados y pendientes reales.

## Instalación y configuración

1. Disponer de backup de base y filestore. Para evaluación, restaurar en una copia y ejecutar `make neutralize DB=<copia>` en ambiente19: incluye la neutralización de ARCA. No reactivar certificados ni conexiones fiscales reales en esa copia.
2. Copiar los tres directorios a una ruta de addons reconocida y actualizar el inventario de aplicaciones. Instalar `msb_lafija_quick_checkout`; registrar las tres versiones. Para actualizar una instalación previa, actualizar los tres módulos. En CLI de evaluación: `odoo -c /etc/odoo/odoo.conf -d <copia> -i msb_lafija_quick_checkout --stop-after-init --no-http`. No usar las bases de pruebas como destino de producción.
3. Configurar dominios diferentes para los sitios. En el backup de referencia, sitio 1 = `lafija`, sitio 2 = `empresas`. Marcar **Sitio corporativo de La Fija** en `empresas`, activar **Specific User Account** y alta por invitación en su configuración nativa. La Fija entrega las cuentas mediante su acción propia, sin invitación por correo. La política corporativa también bloquea los formularios de autorregistro/reset.
4. Activar **Quick Checkout** solo en el público; modo **quotation**, cotización enviada, por defecto. Asignar el usuario responsable comercial y su actividad. La tienda pública conserva sus productos, lista de precios y ajustes comerciales.
5. Asignar **Admin La Fija operativo** al usuario interno designado. El grupo concentra funciones comerciales/menús/preparación, sin administración técnica de usuarios. Ese usuario accede al backend desde el dominio público. Crear cuentas mediante **La Fija → Alta de empleado**; no convertir contactos de compradores particulares en empleados ni colocar empleados como subcontactos.
6. En **Menús del día**, crear fechas y opciones vendibles, revisar descripciones y publicar. La publicación nativa del producto en eCommerce no determina su elegibilidad corporativa. Las opciones del menú del día sí la determinan.
7. Comunicar el acceso `https://<dominio-corporativo>/my/viandas`, usuario individual y contraseña por el canal acordado. En el Chrome de evaluación: `http://lafija-empresas:8190/my/viandas`; el público/backend está en `http://lafija-publico:8190`. Son alias de la red de la demo; no son direcciones de producción. No sustituirlos por localhost/127.0.0.1: el sitio se determina por el host.

Las cuentas experimentales anteriores a la instalación pueden necesitar **Gestionar acceso → Corregir empresa y sitio**. La lista muestra señales incoherentes para su revisión; el acceso queda denegado mientras no estén completas. No se elimina la clasificación para hacer que una cuenta entre como particular.

## Operación y recuperación

- **Reservas**: consultar por fecha/empresa; filtros de pendientes de cualquier fecha y cambios posteriores a las 10:00. La referencia usa únicamente la zona horaria del usuario administrador de Odoo (`base.user_admin`, con UTC si no tiene una asignada), sin configuración horaria propia. En `lafija` es `America/Argentina/Buenos_Aires`. **No cambiar la zona horaria del usuario administrador de Odoo**: es la referencia operativa acordada; la zona horaria del admin La Fija operativo o del empleado no la reemplaza.
- La página permite completar varios días de una semana y saltear otros. `DAYS_PER_WEEK = 7` acota el número de selecciones de un envío como defensa contra un POST manipulado; no agrega un límite de negocio semanal. La regla es **una reserva por empleado y día en toda la base**. El empleado puede sustituir su elección dentro del menú del mismo día.
- En el teléfono, cada elección por toque pliega el día y deja «Sin guardar: …» en su encabezado. Solo Guardar presenta el conjunto de días. Al volver con Atrás se recupera la página desde el servidor, incluido el borrador conservado si hubo un conflicto. El aterrizaje busca la primera semana con un menú publicado, opciones habilitadas, sin lista tomada y con referencia aún vigente; consultar una semana explícita conserva la posibilidad de pedir tarde para revisión. Un día con lista tomada se identifica incluso plegado.
- **Tomar lista para preparación**: acción explícita sobre el menú del día. Repetirla devuelve el mismo corte. La primera revisión se conserva; no confirma ventas ni factura.
- Antes del corte, una nueva selección aplica. Después, queda pendiente y la elección vigente se conserva. Una nueva reserva después del corte queda fuera de la lista hasta que se atienda.
- Elegir la vianda vigente propia permite **anular el cambio pedido**, incluso si el operador había elegido ese plato fuera del menú. Esa excepción no habilita productos de otras personas ni imágenes fuera del menú. La anulación conserva la consulta escrita, la lista tomada y las etiquetas, y queda en ambas historias con autor y hora. Si la vianda cambió mientras el empleado elegía, se pide revisar antes de guardar. Una reserva nueva pendiente sin vigente sigue requiriendo corrección del operador para cancelarla.
- Desde **19.0.1.3.2**, el resumen plegado distingue «Sin guardar: anular el cambio pedido. Sigue …» de otra elección. Ambas historias identifican el cambio anulado, incluido el evento antiguo, sin reescribir sus datos ni renombrar `withdrawal`. **Momento del último acto** incluye elecciones, consultas y anulaciones; indica cuándo actuó el empleado, no que haya un pendiente. La atención se lee en su columna propia. El motivo interno dice «Motivo de esta actuación; no se muestra al empleado».
- **Editar** permite aplicar, reemplazar, restaurar una elección tomada, rechazar, cancelar y corregir atribución/día. Una solicitud escrita tiene su propia atención: **Responder al empleado** conserva su estado (no abre una consulta ni cierra una existente); **Cerrar solicitud sin cambiar la vianda** la cierra. El asistente indica si la consulta está abierta antes de enviar. Aceptar/rechazar una opción pendiente no cierra una consulta escrita, ni cerrar el texto aplica una opción. Guardar la semana sin cambios no altera estas atenciones. Requiere motivo interno; la respuesta al empleado es un texto separado, sin notas internas.
- La revisión contiene la elección usada, empresa, persona, fecha, descripción y marcas temporales. **Generar etiquetas** conserva un PDF exacto de esa revisión. **Registrar sustitución** deja constancia de la coordinación con preparación; no acredita entrega física.
- **Imprimir planilla del día** abre un PDF desde la lista tomada o su revisión vigente: cantidades por producto, detalle por empresa y empleado y pendientes de atención separados. Las opciones solicitadas y nuevas reservas pendientes no se suman a preparación. El PDF identifica fecha y revisión; no lleva importes ni mensajes internos, ni acredita entrega. Las etiquetas por vianda siguen disponibles como documento distinto.
- Cola y planilla usan los mismos rótulos: **Nueva reserva**, **Cambio de opción**, **Consulta escrita** y sus combinaciones. Los campos de respuesta y motivo interno mantienen un borde visible antes del foco. Las confirmaciones del operador se reemplazan y desaparecen solas; Publicar conserva el aviso después de actualizar la ficha.
- **Gestionar acceso** se abre desde la ficha propia de Empleados corporativos, sin campos fiscales ni correo obligatorio. Permite deshabilitar/habilitar y restablecer contraseña. Copiar el acceso antes de confirmar; el asistente confirma la copia u ofrece selección manual si el navegador no permite portapapeles. La contraseña temporal se vacía al aplicar y no se publica en notas. La deshabilitación conserva reservas e historia; no cancela automáticamente viandas.
- Los pedidos/facturas manuales tienen la sección **La Fija**, con reservas de origen y protección permanente. El comprador es la empresa cliente. Al facturar nativamente un pedido protegido, la factura conserva sus reservas de origen. Vincular reservas no genera ni consolida documentos; el operador usa las herramientas comerciales existentes. Un documento protegido y su procedencia no se desmarcan para enviarlo a un empleado.

El ingreso del operador sin destino previo abre **Hoy**; una redirección explícita se conserva. **Pendientes de cualquier fecha** mantiene visibles las solicitudes anteriores. Las fechas y horas operativas propias usan la zona del usuario administrador de Odoo, tanto para empleado como para preparación, filtros relativos e historia interna. El chatter de reservas, menús y empleados del programa también usa esa zona; las conversaciones ajenas al programa conservan la presentación nativa del dispositivo.

Las altas consecutivas pueden usar **Otra alta para esta empresa**. Si existe un único sitio corporativo, se propone sin volver a seleccionarlo. Publicar, responder y cerrar confirman qué ocurrió. La historia del empleado muestra la recepción y su resolución mediante etiquetas seguras; nunca copia el motivo interno.

La lista vigente ofrece resumen por producto y acceso directo a generar/descargar etiquetas. Una lista anterior queda identificada como histórica; sus archivos se conservan. La actualización 19.0.1.1.0 recupera del historial las solicitudes escritas que la versión anterior había quitado de pendientes por un re-guardado.

Una corrección comercial no modifica retroactivamente una lista de preparación ni quita una etiqueta impresa. El operador atiende cada consecuencia y registra la resolución. No enviar importes a mano en respuestas visibles.

## Alta desde padrón · 19.0.1.9.2

**La Fija → Empleados → Alta desde padrón** permite CSV UTF-8 separado por `;` o texto pegado. Encabezados: `nombre;usuario`, con `legajo` opcional. No admite correo, contraseña, empresa ni sitio por columna. Empresa cliente y sitio corporativo se eligen una vez. Límites fijos: **200 personas / 512 KiB por envío**, sin parámetros de sistema ni ajustes en la interfaz. El límite de bytes se conserva para admitir nombres largos y caracteres UTF-8; la cantidad de altas limita el trabajo del ejecutor.

Un padrón más grande se carga en **varios envíos**, cada uno con su propia vista previa, confirmación y CSV de accesos. Por ejemplo, 450 personas requieren tres envíos de 200, 200 y 50. Controlá que la suma coincida con el padrón original. No se omiten ni recortan filas: un envío que supera 200 se rechaza completo. Cada envío es todo o nada; el fallo de uno no deshace los demás. Los lotes ya completados conservan su auditoría; un lote anterior de más de 200 todavía en cola debe dividirse antes de volver a validarlo.

1. **Leer padrón** muestra las filas y propone usuarios; no crea cuentas. Se puede editar cada fila. **Validar vista previa** vuelve a comprobar todo. Cambiar empresa, sitio, prefijo o una fila invalida la confirmación anterior.
2. Si falta usuario, se propone `prefijo.nombre.apellido`, normalizando todos los componentes del nombre; con legajo, `prefijo.legajo`. Las colisiones llevan sufijo numérico y aviso. No combinar usuario explícito y legajo en una fila: la vista previa pide elegir uno. Los usuarios nuevos del padrón empiezan con una letra y usan letras ASCII, números, punto, guion o guion bajo, hasta 128 caracteres. Esta restricción hace que el CSV conserve literalmente los accesos sin que la planilla los convierta en números/fórmulas; no modifica los usuarios existentes ni el alta individual.
3. Nombres repetidos requieren usuarios distintos y **Confirmo que los nombres repetidos son personas diferentes**. Usuarios explícitos existentes —incluidos archivados, internos y de otros sitios— son errores. La validación se repite al confirmar y al empezar el proceso.
4. **Confirmar altas en segundo plano** encola un lote persistente. El cron crea todas las cuentas en una transacción. El contador intermedio es provisional: hasta el commit no hay ninguna alta visible. Cerrar/recargar la pestaña no cancela ni duplica. Ante fallo, se revierte todo; tras una interrupción el mismo lote se reintenta hasta tres veces. Si se completa, nunca se vuelve a ejecutar.
5. **Descargar CSV de accesos** está disponible exclusivamente para el operador creador durante **15 minutos desde que termina el lote**. Repetir descarga devuelve los mismos bytes y contraseñas. El archivo contiene empresa, persona, usuario, contraseña individual y sitio; entregarlo únicamente al contacto autorizado de la empresa. Vencido o perdido, usar **Gestionar acceso → Restablecer contraseña**, sin recrear cuentas.

Identidad compartida: `lafija.employee.onboarding._create_identity` es privado y lo usan ambos caminos. Conserva hash nativo, contexto sin correo/reset, validaciones, invalidaciones de caché y nota de auditoría. El lote agrega referencia y relación fila → contacto/cuenta. No guarda contraseñas en el lote, líneas, notas, logs propios ni adjuntos. La coordinación es por login entre las dos altas propias; no sustituye la unicidad nativa por sitio ni coordina importadores externos que no llamen al servicio.

### Proceso y archivo temporal: administración

- Modelos nuevos: `lafija.employee.batch`, `.line` y `.progress`. El grupo operador existente puede crear/consultar/corregir **sus propios lotes** y filas; el progreso se muestra mediante una proyección, sin ACL directa sobre `.progress`. No se amplían permisos en contactos/usuarios. Un administrador técnico tampoco puede descargar por HTTP el lote de otra persona: se comprueba creador y rol, no solo la regla de lectura.
- Acción programada `kai_viandas.cron_employee_batch`: **La Fija: procesar padrones y eliminar accesos vencidos**, **cada hora**, con disparo inmediato al confirmar y si quedan lotes en cola (`_trigger()`). Se ejecuta cuando el ejecutor nativo esté disponible; no espera obligatoriamente una hora. Necesita al menos un ejecutor de cron y la acción activa; `max_cron_threads=0` deja lotes esperando. La actualización aplica el intervalo incluso al registro `noupdate`, conservando activación, usuario, `nextcall` y disparos pendientes; no reactiva una copia neutralizada. No hace falta `queue_job` ni otro addon.
- Un cursor procesa identidades y auditoría del lote en una sola transacción; otro publica únicamente contador/intento/fecha de avance. Bloqueo de fila evita dos ejecuciones y bloqueos transaccionales por login coordinan con el alta individual. La comprobación de existencia lee también una conexión nueva para detectar un alta confirmada después de abrir la transacción. Se necesitan hasta tres conexiones para este trabajo, además de las solicitudes normales.
- Medición de 1.9.2 en `lafija_mvp_padron_190`: **5 filas, 1,824 s reales / 1,666 s CPU / pico 159,29 MiB**; luego **200 filas, 79,819 s reales / 74,226 s CPU / pico 160,92 MiB**. Log `lafija-192-padron-medicion-20260915T015241Z.log`. Se verificaron 200 cuentas distintas, contraseñas individuales, mismo CSV al repetir descarga y ningún duplicado al repetir ejecución. RSS es el pico del proceso Python, no del conjunto PostgreSQL/Odoo. Parámetros del ensayo: CPU 320 s, real/cron 400 s, memoria blanda/dura 512 MiB/1 GiB; se ejecutó con Odoo shell y el cursor transaccional real, sin simular el watchdog prefork. La referencia histórica de 1.9.0 (500 filas: 264,378 s reales / 247,795 s CPU) motivó reducir el máximo; ya no es un tamaño admitido.
- Presupuesto interno fijo de **240 s de tiempo real**, desde el inicio de `_create_all`, incluyendo bloqueos y revalidación. Se comprueba antes de cada alta y después de la última, antes de publicar el CSV. Al agotarse, la transacción revierte: no queda ninguna cuenta creada en ese envío. Deja margen frente a los 320 s de CPU informados para el servidor; no interrumpe una llamada bloqueante ni garantiza un tiempo en otros equipos/addons. No se cambia la configuración del servidor desde el addon. La prueba aislada mide el ejecutor completo con hash nativo, validaciones y cachés, no la espera entre las 21 bases ni el watchdog del servidor real.
- CSV efímero: `<data_dir>/lafija_credentials/<sha256(nombre_de_base)>/<referencia_aleatoria>.csv`, fuera del filestore de adjuntos. Directorios 0700, archivo 0600, escritura y reemplazo atómicos. Todos los workers que ejecuten cron o atiendan descargas deben ver **el mismo directorio** con el mismo usuario de sistema; no servirlo directamente mediante proxy. La ruta HTTP propia es `/lafija/padron/<id>/credenciales`, sin token público y con `no-store`.
- El archivo sobrevive al reinicio para recuperar la descarga dentro de la ventana; se borra por el cron al vencer, incluidos huérfanos de un proceso interrumpido. **La fecha de vencimiento se comprueba en cada descarga aunque el cron esté detenido**. El borrado físico puede esperar al siguiente cron libre. El administrador del servidor puede leer archivos del proceso: no es un secreto frente al administrador del sistema.
- **Excluir `lafija_credentials` de respaldos, sincronizaciones y artefactos.** Base/filestore no contienen este CSV; si se respalda todo `data_dir`, agregar una exclusión explícita. No adjuntar el CSV al chatter, a evidencia pública ni a un ticket. Si se desinstala o desactiva el cron, el administrador debe eliminar también los temporales; no desinstalar para detener o reintentar un lote.
- Logs propios: `LAFIJA_PADRON_DONE batch=…` y `LAFIJA_PADRON_FAILED batch=… exception_type=…`. No se registra el mensaje ni los argumentos de la excepción para evitar que otra extensión incluya credenciales. Conservar referencia, fecha y tipo de fallo; diagnosticar en copia sintética sin habilitar trazas de valores/contraseñas. El resultado de error guía a validar de nuevo o pedir revisión al administrador.

Pruebas: `tests/test_release_190.py` (métodos, HTTP y puntero), `tests/test_release_192.py` (límites, presupuesto, cron), más `lafija-qa/verify_padron.py` y `verify_padron_concurrency.py` sobre una base descartable. Manuales/ayudas los integra Claude a partir de la tabla editorial de `IMPLEMENTACION-MVP.md`; no hay cambios de facturación ni de la página del empleado en esta entrega.

Desde 1.9.2, `LafijaCommon` fija el reloj de los fixtures en el 14/09/2026 a las 09:00 de La Fija y la zona del administrador en ART. Los menús comunes de esa semana no dependen del reloj real; las pruebas de medianoche, días pasados y caducidad mantienen sus relojes explícitos anidados. Ya no hay que evitar la franja 21:00–00:00 ART para ejecutar la batería.

## Protección implementada

- P1: página propia con proyección de datos permitidos, guardia de cuenta/sitio y ausencia de comunicaciones comerciales automáticas dirigidas al empleado. El catálogo genérico del sitio corporativo no es navegable, incluso sin sesión. Las rutas ajenas al programa conservan su comportamiento.
- P2: clasificación permanente de pedidos/facturas/archivos, protección antes de tokens, streams, reportes, descargas contables y vista previa de la primera página de PDF. Identidad original de sesión o autenticación API nativa conservada antes de cualquier elevación de permisos.
- P3: reglas globales sobre modelos monetarios y archivos; reserva propia; rechazo de credenciales/claves corporativas fuera del login web autorizado. Las ACL de grupos nativos no anulan una regla global. No se añaden reglas de identidad globales sobre contactos/usuarios.

La relación corporativa es un vínculo propio con la empresa. El contacto permanece independiente y sin descendientes; la jerarquía nativa de contactos no se utiliza para otorgar acceso comercial.

En una **copia neutralizada para ARCA**, validar un diario electrónico se rechaza antes del proceso fiscal, incluido el CAE simulado de homologación de ADHOC. La evaluación usa un diario interno sin documentos fiscales (**Ventas X Cafe** en la demo). Este control depende de `database.is_ar_neutralized=true`, no modifica el comportamiento de producción ni sustituye la neutralización de certificados.

## Verificación reproducible

Las pruebas propias se ejecutan **sin `l10n_ar_tax`**. Ese módulo instalado en una copia representativa se evalúa por convivencia, sin ejecutar allí la colección propia. Crear la base nativa limitando addons desde el principio; el árbol completo puede autoinstalar extensiones ADHOC.

Desde ambiente19, después de instalar el conjunto en `lafija_mvp_unit`:

```sh
docker compose run --rm --no-deps -T odoo /usr/bin/odoo \
  -c /etc/odoo/odoo.conf \
  --addons-path=/mnt/dev-addons,/usr/lib/python3/dist-packages/odoo/addons \
  --no-http -d lafija_mvp_unit --http-port 8169 --gevent-port 8173 \
  -u kai_viandas,msb_quick_checkout,msb_lafija_quick_checkout \
  --test-enable --test-tags=/kai_viandas,/msb_quick_checkout,/msb_lafija_quick_checkout \
  --stop-after-init
```

No usar `docker exec` sobre el contenedor de desarrollo para una prueba larga: `--dev all` puede reiniciarlo al cambiar archivos. El contenedor descartable evita esa interferencia.

La cobertura distingue cuatro resultados: **respuesta HTTP**, **ejecución de la acción como operador**, **formulario abierto** e **interacción de puntero**. Un 303 no prueba el aterrizaje; llamar una acción no prueba el formulario; `element.click()` no prueba que el puntero alcance el botón. `test_ux_round2.py` ejecuta los caminos de Hoy/Alta por HTTP y métodos bajo el operador; usa eventos de puntero CDP en un Chrome de pruebas para formulario, radios y plegado. Nunca usa el navegador compartido de evaluación.

Desde **19.0.1.3.3**, los `arch` de vistas mantienen un salto de línea antes del primer hijo: el lector de archivos de Odoo 19 usado por `--dev xml/all` requiere ese texto inicial. `test_dev_xml.py` ejecuta el lector nativo sobre todas las vistas y plantillas y combina vistas como operador en modo XML. El cálculo de novedades al guardar consulta solo las reservas propias de las fechas enviadas; `test_submission_scope.py` lo contrasta con historial adicional y otra persona en esas mismas fechas.

Desde **19.0.1.4.0**, si La Fija cambia la vigente mientras el empleado intenta anular un cambio, **no se guarda ningún día del envío**. La semana vuelve con las elecciones enviadas como borrador, contador «Sin guardar», estado vigente actualizado y el día conflictivo abierto. El empleado revisa y vuelve a guardar todo junto, o descarta explícitamente el borrador. Atrás y Recargar conservan ese borrador mediante POST → 303 → GET; se guarda por cuenta, sitio y semana en la sesión, no como reservas nuevas. No persiste al perder la sesión ni entre dispositivos. Un producto propio que ya no esté permitido se muestra solo como elección anterior, sin imagen, y exige elegir una opción válida. La firma de esa descripción acredita su procedencia; no concede permisos ni evita la revalidación bajo el bloqueo existente.

Los recursos `viandas.css` y `viandas.js` usan una huella SHA-256 de su contenido, calculada una vez por proceso. **Reiniciar todos los procesos al desplegar cambios**; no depende de recordar una versión en la plantilla ni abre `/web/assets`. Las listas vacías tienen ayuda propia; Hoy recuerda consultar pendientes de otras fechas. Un menú nuevo se identifica como tal y ofrece publicar/tomar lista/copiar descripciones solo cuando tiene fecha y sitio, sin exigir un guardado manual adicional. «Mensajes · hora de La Fija» queda dentro de la hoja en menú y reserva.

## Herramientas de evaluación separadas (1.7.0)

Los 14 protocolos que antes estaban en `tools/` se trasladaron al repositorio local independiente
[/data/apps/personal/jmobiol/ambiente19/development/lafija-qa/README.md](/data/apps/personal/jmobiol/ambiente19/development/lafija-qa/README.md).
Allí está la tabla «ruta anterior → nueva receta», con raíz/Compose parametrizados y comprobación
`--check-paths` que no inicia protocolos ni abre bases. El addon no distribuye herramientas, fixtures
ni credenciales. No se reescriben los logs históricos; sus rutas anteriores siguen siendo evidencia.

El contrato de dependencias directas es `website_sale`, `website`, `web`, `sale`, `product`, `account`,
`payment`, `portal`, `auth_signup`, `mail` y `sales_team`. No se agrega lógica comercial ni permisos por
hacer explícitas estas dependencias ya transitivas. Las superficies de Odoo intervenidas están en
[SUPERFICIES-ODOO-INTERVENIDAS.md](/data/apps/personal/jmobiol/newvps19/docs/lafija/SUPERFICIES-ODOO-INTERVENIDAS.md).

Desde 1.7.0, Motivo es optativo en las cinco operaciones de acceso; vacío o espacios registra el texto
correspondiente a la operación efectivamente confirmada. Un motivo escrito se conserva en la nota interna.
Editar pedido conserva la referencia del estado presentado. Si cambió mientras se atendía, no aplica
la actuación: vuelve a mostrar el estado actual y conserva motivo y respuesta para confirmar de nuevo.
Responder sin cerrar es la excepción: envía la respuesta y advierte, conservando pendientes y elección.
Las ayudas se actualizan desde los manuales por separado; esta entrega incluye su tabla editorial.

## Alcance que permanece fuera

Sin confirmación/facturación automática, sincronización comercial, consolidación programada, impresión física validada, gerente externo, segmentación por empresa, horario configurable ni autoservicio de credenciales. La preparación de cotizaciones desde 1.8.0 se inicia expresamente por el operador. Módulos nuevos que agreguen entradas de precios/documentos requieren regresión de las protecciones.

## Cierre por empresa y período

Desde 1.8.1, cambiar empresa, compañía o fechas descarta únicamente el resumen del formulario y vuelve a **Elegir período**; **Ver resumen** recalcula antes de ofrecer Preparar. Si no hay viandas disponibles, Preparar no se ofrece y la validación del servidor se conserva. Desde/Hasta muestran el año y se distribuyen en dos columnas: al teclear, Enter aplica la fecha y cierra su calendario antes de pasar al otro campo. Las consultas de operaciones preparadas dicen **Consulta guardada del …**, con conteos correspondientes a esa consulta; **Actualizar resumen** vuelve a consultar y no altera la selección original ni el anexo. La lista nativa de Pedidos del período muestra el estado del pedido por defecto.

**La Fija → Reservas → Preparar cotización** propone el mes calendario anterior en hora de La Fija. El operador elige una empresa cliente y revisa cantidades por variante, reservas, empleados y fechas, sin importes. Se cuenta cada vianda vigente una sola vez, en la revisión actual de preparación y con la empresa guardada en la reserva. Las consultas abiertas y los antecedentes de pedidos cancelados son avisos. Los días sin lista, las canceladas que figuraron en preparación, los productos incompatibles, los vínculos duplicados y las diferencias posteriores quedan visibles para revisión.

**Preparar cotización** crea un único borrador protegido en Ventas: empresa como cliente, productos y cantidades agrupados, reservas vinculadas y selección/revisiones de origen conservadas. Odoo calcula lista de precios, posición fiscal, impuestos y descuentos; C3 no asigna esos valores ni un sitio web. No confirma ventas ni crea facturas. **Ver pedidos del período** abre los pedidos existentes con sus estados nativos para continuar por el circuito habitual. Una reserva vinculada a un pedido no cancelado se excluye de otra preparación, aunque siga en borrador; eso no acredita facturación ni pago.

La operación se conserva para que el doble clic o reintento abra el mismo pedido. Se coordina con los bloqueos de menús y se vuelve a comparar el resumen mostrado: si cambió, no se crea nada y se pide revisar. Cambiar después una reserva no sincroniza líneas comerciales; el resumen actualizado y la pestaña La Fija del pedido señalan diferencias. Copiar pedidos o modificar vínculos manualmente en Ventas sigue requiriendo revisión humana.

**Imprimir anexo para la empresa** está en el resumen y en la pestaña La Fija del pedido preparado. El PDF no contiene importes; desde un pedido conserva la selección original, aunque después cambien reservas o líneas. Es un documento protegido para entrega por el canal comercial acordado: no se envía al empleado ni se adjunta automáticamente a facturas.

El upgrade añade `lafija.quotation.preparation` y sus campos de vínculo en Ventas; no migra reservas/historia ni modifica permisos de modelos existentes. El nuevo resumen solo está disponible al grupo operativo y a sus compañías habilitadas. Para cantidades, la unidad comercial admitida es **Unidades**; otras unidades quedan a revisar. Se agrupan sitios de la misma compañía vendedora; nunca se mezclan compañías vendedoras en un pedido.

Concurrencia real: protocolo `verify_quotation_concurrency.py` en el repositorio `lafija-qa`, solo sobre `lafija_mvp_quotation_180`, base nativa sintética separada. No ejecutarlo en el demo. Las ayudas v6 se incorporan por separado desde la tabla editorial de `IMPLEMENTACION-MVP.md`.


## Marca, navegación y ayuda (1.5.0)

El espacio del empleado usa crema `#E0DBCF` y carbón `#414141`, con fuentes del sistema. La semana, acceso, detalle y denegaciones comparten el mismo diseño. Guardar sigue en flujo: la semana se desplaza en su región, sin `fixed` ni `sticky` sobre las tarjetas.

El encabezado usa **el logo configurado del sitio corporativo**. Si no tiene logo, o conserva el «Your Logo» nativo, muestra «La Fija». Se entrega por `/viandas/marca/<huella>/logo`, una ruta que solo devuelve el logo del sitio resuelto por Host; no abre `/web/image` ni permite elegir otro registro. La URL cambia con los bytes del logo, con ETag y caché por contenido. PNG/JPEG/WebP/GIF y SVG pasivo son compatibles; un SVG con contenido activo o referencias externas se rechaza. El original guardado no se modifica. La franja blanca superior del raster actual se oculta solo en su presentación.

«Esta semana» vuelve a la semana calendario de hoy según la zona del usuario administrador de Odoo. «Próxima disponible» conserva el aterrizaje existente. Cambiar de semana o abrir ayuda conserva el borrador **ya recuperado de un conflicto** en su sesión; no guarda elecciones nuevas por sí mismo. La zona del usuario administrador de Odoo no debe cambiarse como preferencia personal.

Los textos de ayuda están separados de rutas, permisos y estructura:

- `views/help_employee_content.xml`: manual de empleado; `/my/viandas/ayuda`, solo cuenta corporativa habilitada en su sitio.
- `views/help_access_content.xml`: instrucciones públicas mínimas de acceso; `/viandas/ayuda-acceso`. Sin datos personales, menús ni reservas.
- `views/help_operator_content.xml`: manual del operador, menú **La Fija → Ayuda**. Ficha nativa de lectura, con permiso exclusivo del grupo operativo.
- `views/help_views.xml`: estructura y acción de presentación. No es el archivo para redactar el manual.

El contenido entregado en esta versión es **provisional**. Claude incorpora y revisa los manuales desde `/data/apps/personal/jmobiol/newvps19/docs/lafija/manuales/`. Editar el QWeb correspondiente y actualizar el módulo para publicar un cambio de texto; no hacen falta librerías ni conversión automática de Markdown. El manual técnico `MANUAL-ADMINISTRADOR-ODOO.md` permanece en esa carpeta, fuera de la ayuda pública y de empleados.

### Entrada y presentación · 19.0.1.8.2

La guardia identifica el sitio y la cuenta sin usar el idioma todavía no validado del navegador. Dentro del ámbito corporativo normaliza únicamente el contexto de la petición a un idioma activo; no activa idiomas ni cambia sesión, preferencias o el flujo nativo público. Corrige el 422 reproducido al leer el sitio con cachés frías y contexto es_ES/es_419/zh_CN en una base con solo es_AR activo.

Menú: Hoy · Menús (Menús del día) · Empleados (lista y alta) · Ayuda. En Hoy, «Agregar pedido de cliente» abre el asistente de pedidos de empleados. Las reservas que requieren atención de cualquier fecha se ven con «Ver pendientes de cualquier fecha» desde Hoy. Convivencia de la grilla verificada en una base aislada con web_responsive; no se parchea su barra. Las opciones con foto usan imagen 16:9 a ancho de tarjeta; sin foto, fila compacta. Se conserva la entrega privada por image_1024.

Actualizar un resumen recarga su ficha sin duplicar migas ni cerrar el diálogo. Las fechas se presentan como dd/mm/aaaa; los datos conservados siguen en ISO y no cambian sus huellas. El anexo vacío conserva su explicación sin tablas vacías. No hay cambios de valoración, inclusión ni facturación.
