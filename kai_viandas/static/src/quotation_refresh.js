import { registry } from "@web/core/registry";

// El callback nativo recarga la ficha que disparó el botón, incluso en un
// diálogo. No navegar a otra ventana ni cerrar el formulario de origen.
registry.category("actions").add("lf_quotation_reload", async (env, action, options) => {
    if (options.onClose) {
        await options.onClose();
    } else {
        // Invocación fuera de un botón: reemplazar, nunca acumular otra miga.
        await env.services.action.doAction(action.params.form, { stackPosition: "replaceCurrentAction" });
    }
    if (action.params.feedback) {
        // Después de recargar: mismo aviso breve y reemplazable del operador,
        // sin otra ventana, sin cerrar el diálogo y sin sustituir incidencias.
        await env.services.action.doAction({
            type: "ir.actions.client", tag: "lf_operation_feedback",
            params: { message: action.params.feedback, passive: true },
        });
    }
});
