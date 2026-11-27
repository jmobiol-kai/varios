import { reactive, toRaw } from "@odoo/owl";
import { registerMessageAction } from "@mail/core/common/message_actions";
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

const kaiDelete = reactive({ allowed: user.isSystem });
user.hasGroup("om_whatsapp_base.group_om_whatsapp_manager").then((allowed) => {
    kaiDelete.allowed = Boolean(allowed) || user.isSystem;
});

const MESSAGE_BODY = _t(
    "Esto borra el mensaje solo en Odoo. No se borra en el teléfono del cliente."
);
const THREAD_BODY = _t(
    "Esto borra la conversación solo en Odoo. No se borra en el teléfono del cliente. El contacto y la cuenta de WhatsApp se conservan."
);

registerMessageAction("kai-om-whatsapp-delete", {
    condition: ({ message }) => message?.message_type === "om_whatsapp" && kaiDelete.allowed,
    icon: "fa fa-trash",
    name: _t("Eliminar"),
    onSelected: async ({ message, owner }) => {
        const row = toRaw(message);
        owner.env.services.dialog.add(ConfirmationDialog, {
            title: _t("Eliminar"),
            body: MESSAGE_BODY,
            confirmLabel: _t("Eliminar"),
            confirm: async () => {
                await owner.env.services.orm.call("mail.message", "action_om_whatsapp_delete_in_odoo", [
                    [row.id],
                ]);
                row.remove({ removeFromThread: true });
            },
            cancel: () => {},
        });
    },
    sequence: 120,
});

registerThreadAction("kai-om-whatsapp-delete-thread", {
    condition: ({ thread }) => thread?.channel_type === "om_whatsapp" && kaiDelete.allowed,
    icon: "fa fa-trash",
    name: _t("Eliminar conversación"),
    open: async ({ thread, owner }) => {
        const row = toRaw(thread);
        owner.env.services.dialog.add(ConfirmationDialog, {
            title: _t("Eliminar conversación"),
            body: THREAD_BODY,
            confirmLabel: _t("Eliminar"),
            confirm: async () => {
                await owner.env.services.orm.call(
                    "discuss.channel",
                    "action_om_whatsapp_delete_conversation",
                    [[row.id]]
                );
                row.delete();
            },
            cancel: () => {},
        });
    },
    sequence: 40,
});
