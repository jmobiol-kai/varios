"""Etiquetas públicas cerradas. Un motivo interno nunca es un texto de respaldo."""

OLD_LABELS = {
    "note": "Respuesta sin cierre", "accept": "Cambio aplicado", "reject": "Cambio rechazado",
    "replace": "Opción corregida", "restore": "Elección restaurada", "cancel": "Vianda cancelada",
    "reassign": "Atribución corregida", "close_request": "Solicitud cerrada",
    # Entrada histórica: se normaliza al mostrar, sin reescribir el evento guardado.
    "Cambio solicitado retirado por el empleado": "Cambio anulado por el empleado",
}

# Los eventos históricos conservan tanto claves antiguas como títulos de operación.
OPERATION_KEYS = {
    "Aplicar elección pendiente": "accept", "Corregir opción": "replace",
    "Restaurar una elección tomada": "restore", "Rechazar el cambio de opción": "reject",
    "Cancelar vianda": "cancel", "Corregir empresa o día": "reassign",
    "Responder y mantener pendiente": "note", "Responder al empleado": "note",
    "Cerrar solicitud sin cambiar la vianda": "close_request",
}


def safe_operation_label(result):
    prefix = (result or "").partition(": ")[0]
    return OLD_LABELS.get(OPERATION_KEYS.get(prefix, prefix), "Actuación de La Fija registrada")


def pending_label(has_current, has_choice, has_question):
    """El mismo estado de atención en la cola y en la planilla de preparación."""
    choice = ("Cambio de opción" if has_current else "Nueva reserva") if has_choice else ""
    if has_question:
        return f"{choice} y consulta escrita" if choice else "Consulta escrita"
    return choice or "Sin pendientes"
