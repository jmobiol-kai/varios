import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

const NO_FREE_DAY_MESSAGE =
    "No hay más días con menú publicado esta semana; usá Semana siguiente.";

function isSentinelBlocking(root) {
    const blocked = root.querySelector(".lf-cannot-add-line");
    if (!blocked) {
        return false;
    }
    return (
        !blocked.classList.contains("o_invisible_modifier") &&
        !blocked.classList.contains("o_hidden") &&
        !blocked.classList.contains("d-none")
    );
}

function isEmployeeOrderLines(renderer) {
    const el = renderer.tableRef?.el || renderer.rootRef?.el || renderer.el;
    if (el?.closest?.(".lf-employee-order-lines, .lf-employee-order-form")) {
        return true;
    }
    const className = renderer.props?.archInfo?.className || "";
    return String(className).includes("lf-employee-order-lines");
}

function formRoot(renderer) {
    const el = renderer.tableRef?.el || renderer.rootRef?.el || renderer.el;
    return el?.closest?.(".lf-employee-order-form") || document.querySelector(".lf-employee-order-form");
}

// x2many lists hardcode ListRenderer and ignore js_class, so we patch add().
// The view still declares js_class="lf_employee_order_list" for the list arch.
patch(ListRenderer.prototype, {
    add(params) {
        if (isEmployeeOrderLines(this)) {
            const root = formRoot(this);
            if (root && isSentinelBlocking(root)) {
                this.env.services.notification.add(NO_FREE_DAY_MESSAGE, { type: "warning" });
                return;
            }
        }
        return super.add(params);
    },
});
