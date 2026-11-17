/** @odoo-module **/

import { Component, useRef, useState, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Solo en el asistente transitorio. El HTTP de la demo no ofrece Clipboard API.
class CredentialsField extends Component {
    static props = { ...standardFieldProps };
    static template = xml`
        <div class="lf_credentials">
            <textarea class="form-control" rows="2" readonly="readonly" aria-label="Acceso para entregar"
                t-ref="text" t-att-value="props.record.data[props.name] || ''"/>
            <button type="button" class="btn btn-secondary mt-2" t-on-click="copy">Copiar acceso</button>
            <small class="d-block mt-1" role="status" t-out="state.message"/>
        </div>`;

    setup() {
        this.text = useRef("text");
        this.state = useState({ message: "Copialo antes de confirmar el alta o el restablecimiento." });
    }

    async copy() {
        const value = this.props.record.data[this.props.name] || "";
        let copied = false;
        if (navigator.clipboard?.writeText) {
            try {
                await navigator.clipboard.writeText(value);
                copied = true;
            } catch { /* Hay un mecanismo local de copia debajo. */ }
        }
        if (!copied) {
            this.text.el.focus();
            this.text.el.select();
            try { copied = document.execCommand("copy"); } catch { /* Conservar selección manual. */ }
        }
        this.state.message = copied ? "Acceso copiado. Ya podés confirmar."
            : "Seleccionamos el acceso: copialo con Ctrl+C o con la opción Copiar de tu dispositivo.";
    }
}

registry.category("fields").add("lf_credentials", {
    component: CredentialsField,
    supportedTypes: ["text"],
});
