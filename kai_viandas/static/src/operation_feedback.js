import { registry } from "@web/core/registry";

// Solo reemplaza nuestras confirmaciones; conserva avisos ajenos y errores.
const previousNotice = new WeakMap();

registry.category("actions").add("lf_operation_feedback", async (env, action, options) => {
    const notification = env.services.notification;
    previousNotice.get(notification)?.();
    previousNotice.set(notification, notification.add(action.params.message, {
        type: action.params.type === "warning" ? "warning" : "success", sticky: false, autocloseDelay: 6000,
        className: action.params.passive ? "lf-quotation-feedback" : "",
    }));
    if (action.params.next) {
        return env.services.action.doAction(action.params.next, options);
    }
    if (action.params.close) {
        // Cerrar por el servicio conserva el onClose del formulario/lista de origen.
        // El aviso se publica antes: una acción anidada puede cancelar la espera
        // de la acción anterior. El servicio global lo conserva al recargar la ficha.
        await env.services.action.doAction({ type: "ir.actions.act_window_close" }, options);
    }
});
