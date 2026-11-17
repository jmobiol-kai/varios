/** @odoo-module **/

import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

class LfQuotationLinkField extends Component {
    static props = { ...standardFieldProps };
    static template = xml`
        <a href="#" class="o_form_uri lf_quotation_link" t-if="displayName"
           t-on-click.stop.prevent="openOrder" t-esc="displayName"/>`;

    setup() {
        this.action = useService("action");
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    get displayName() {
        const value = this.value;
        if (!value) {
            return "";
        }
        return value.display_name || value[1] || "";
    }

    get orderId() {
        const value = this.value;
        if (!value) {
            return false;
        }
        return value.id || value[0] || false;
    }

    openOrder(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const resId = this.orderId;
        if (!resId) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: resId,
            views: [[false, "form"]],
            view_mode: "form",
            target: "current",
            name: this.displayName,
        });
    }
}

registry.category("fields").add("lf_quotation_link", {
    component: LfQuotationLinkField,
    supportedTypes: ["many2one"],
});
