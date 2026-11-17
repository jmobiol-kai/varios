import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { usePager } from "@web/search/pager_hook";
import { onMounted } from "@odoo/owl";

class PreparationConfirmationDialog extends ConfirmationDialog {
    setup() {
        super.setup();
        onMounted(() => {
            // Solo esta confirmación: Enter inicial vuelve sin tomar la lista.
            // El botón principal y el orden visual nativos se conservan.
            this.modalRef.el.querySelector('.modal-footer .btn-secondary').focus({preventScroll: true});
        });
    }
}

class MenuFormController extends FormController {
    async beforeExecuteActionButton(params) {
        const data = this.model.root.data;
        if (params.name === 'action_take_list' && !data.list_taken) {
            const date = data.date?.toFormat('dd/MM/yyyy') || '';
            const confirmed = await new Promise(resolve => this.dialogService.add(PreparationConfirmationDialog, {
                title: `Tomar lista del ${date}`,
                body: `Vas a tomar la lista para preparar las viandas del ${date}. Hasta las 10:30 de ese día, hora de La Fija, los cambios, agregados o cancelaciones del empleado se aplican en la lista. Después de esa hora ya no pueden modificar ese día en el portal.`,
                confirmLabel: 'Tomar lista', cancelLabel: 'Volver',
                confirm: () => { resolve(true); }, cancel: () => { resolve(false); },
            }, { onClose: () => resolve(false) }));
            if (!confirmed) return false;
        }
        return super.beforeExecuteActionButton(params);
    }
}

class HelpFormController extends FormController {
    setup() {
        super.setup();
        // Solo esta ayuda de un registro; conserva la navegación del backend.
        usePager(() => ({ total: 0 }));
    }
}

registry.category('views').add('lf_menu_form', { ...formView, Controller: MenuFormController });
registry.category('views').add('lf_help_form', { ...formView, Controller: HelpFormController });
