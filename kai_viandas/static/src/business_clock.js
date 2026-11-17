import { Message } from "@mail/core/common/message_model";
import { fields } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";

patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        this.lfBusinessTimezone = fields.Attr();
    },
    get datetime() {
        const original = super.datetime;
        return this.lfBusinessTimezone ? original.setZone(this.lfBusinessTimezone) : original;
    },
    get dateDay() {
        return this.lfBusinessTimezone ? this.datetime.toFormat("dd/MM/yyyy") : super.dateDay;
    },
    get dateSimple() {
        return this.lfBusinessTimezone ? this.datetime.toFormat("HH:mm") : super.dateSimple;
    },
    get dateSimpleWithDay() {
        return this.lfBusinessTimezone ? this.datetime.toFormat("dd/MM/yyyy HH:mm") : super.dateSimpleWithDay;
    },
    get datetimeShort() {
        return this.lfBusinessTimezone
            ? `${this.datetime.toFormat("dd/MM/yyyy HH:mm:ss")} · hora de La Fija (${this.lfBusinessTimezone})`
            : super.datetimeShort;
    },
});
