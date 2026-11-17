import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { onMounted, onWillUnmount } from "@odoo/owl";

class EmployeeBatchController extends FormController {
    setup() {
        super.setup();
        let disposed = false;
        let timer;
        const refresh = async () => {
            try {
                // Solo el lote confirmado: nunca pisar una vista previa editable.
                const data = this.model.root.data;
                const expired = data.state === "done" && data.download_available && data.credentials_until?.toMillis() <= Date.now();
                if (!disposed && (data.state === "queued" || expired)) {
                    await this.model.root.load();
                }
            } finally {
                if (!disposed) timer = setTimeout(refresh, 2000);
            }
        };
        onMounted(() => { timer = setTimeout(refresh, 2000); });
        onWillUnmount(() => { disposed = true; clearTimeout(timer); });
    }
}
registry.category("views").add("lf_employee_batch_form", { ...formView, Controller: EmployeeBatchController });
registry.category("actions").add("lf_batch_reload", async (env, action, options) => {
    if (options.onClose) await options.onClose();
    else await env.services.action.doAction(action.params.form, { stackPosition: "replaceCurrentAction" });
});
