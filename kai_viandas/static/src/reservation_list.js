/** @odoo-module **/

import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { WebClient } from "@web/webclient/webclient";

const CLIENT_ORDER_ACTION = "kai_viandas.employee_order_action";
const LINK_CLASS = "lf_add_client_order";
const LINK_LABEL = "Nuevo pedido";
const ROW_CLASS = "lf_nuevo_pedido_row";

function openEmployeeOrderWizard(actionService, context = {}) {
    if (!actionService) {
        return;
    }
    return actionService.doAction(CLIENT_ORDER_ACTION, {
        additionalContext: context,
    });
}

function isLfReservationList(renderer) {
    const archInfo = renderer.props?.archInfo || {};
    const xmlDoc = archInfo.xmlDoc;
    const cls = [archInfo.className, xmlDoc && xmlDoc.getAttribute && xmlDoc.getAttribute("class")]
        .filter(Boolean)
        .join(" ");
    const jsClass =
        (xmlDoc && xmlDoc.getAttribute && xmlDoc.getAttribute("js_class")) ||
        renderer.env?.config?.viewSubType ||
        "";
    if (cls.split(/\s+/).includes("lf-reservations") || jsClass === "lf_reservation_list") {
        return true;
    }
    const el = renderer.tableRef?.el || renderer.rootRef?.el || renderer.el;
    return !!(el && el.closest && el.closest(".lf-reservations, .o_lf_reservation_list_view"));
}

function resolveRoot(renderer) {
    return renderer.tableRef?.el || renderer.rootRef?.el || renderer.el;
}

function resolveScope(root) {
    return root?.classList?.contains("o_list_view") ? root : root?.closest?.(".o_list_view") || root;
}

function weekStart(isoDate) {
    if (!isoDate) {
        return false;
    }
    const [year, month, day] = String(isoDate).slice(0, 10).split("-").map(Number);
    if (!year || !month || !day) {
        return false;
    }
    const date = new Date(Date.UTC(year, month - 1, day));
    const weekday = date.getUTCDay();
    date.setUTCDate(date.getUTCDate() - (weekday === 0 ? 6 : weekday - 1));
    return date.toISOString().slice(0, 10);
}

function toIsoDate(value) {
    if (!value) {
        return false;
    }
    if (typeof value === "string") {
        const match = value.match(/(\d{4}-\d{2}-\d{2})/);
        return match ? match[1] : false;
    }
    if (value instanceof Date && !Number.isNaN(value.getTime())) {
        return value.toISOString().slice(0, 10);
    }
    if (typeof value.toFormat === "function") {
        try {
            return value.toFormat("yyyy-MM-dd");
        } catch {
            /* try other shapes below */
        }
    }
    if (typeof value.toISODate === "function") {
        return value.toISODate();
    }
    if (typeof value.toISO === "function") {
        return String(value.toISO()).slice(0, 10);
    }
    if (value.from) {
        return toIsoDate(value.from);
    }
    return false;
}

function groupFieldName(group) {
    return group?.groupByField?.name || group?.groupBy?.name || group?._groupBy || "";
}

function groupRawValue(group) {
    if (!group) {
        return false;
    }
    const value = group.value !== undefined ? group.value : group.rawValue;
    if (value && typeof value === "object") {
        if (value.id) {
            return value.id;
        }
        if (Array.isArray(value)) {
            return value[0];
        }
        if (value.from) {
            return value.from;
        }
    }
    return value;
}

function groupCompanyId(group) {
    const value = groupRawValue(group);
    const id = Number(value);
    return Number.isInteger(id) && id > 0 ? id : false;
}

function groupDateValue(group) {
    return toIsoDate(group?.range) || toIsoDate(groupRawValue(group)) || toIsoDate(group?.displayName);
}

function nestedGroups(group) {
    const list = group?.list || group?._list;
    return list?.groups || [];
}

function isFolded(group) {
    return Boolean(group?.isFolded ?? group?._isFolded);
}

function tableColumnCount(scope) {
    const ths = scope.querySelectorAll("thead th, tr.o_group_header th, tr.o_group_header td");
    if (!ths.length) {
        return 12;
    }
    let count = 0;
    ths[0].closest("tr")?.querySelectorAll("th, td").forEach((cell) => {
        count += Number(cell.getAttribute("colspan") || 1);
    });
    return count || 12;
}

function makeLinkRow(scope, actionService, { scopeName, companyId, date, isListEnd }) {
    const tr = document.createElement("tr");
    tr.className = `${ROW_CLASS} o_field_x2many_list_row_add d-print-none`;
    tr.dataset.lfScope = scopeName;
    if (companyId) {
        tr.dataset.lfCompanyId = String(companyId);
    }
    if (date) {
        tr.dataset.lfDate = date;
    }
    const td = document.createElement("td");
    td.colSpan = tableColumnCount(scope);
    const link = document.createElement("a");
    link.href = "#";
    link.role = "button";
    link.className = `btn btn-link lf_nuevo_pedido${isListEnd ? " " + LINK_CLASS : ""}`;
    link.textContent = LINK_LABEL;
    link.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        ev.stopImmediatePropagation();
        const context = {};
        if (companyId) {
            context.default_customer_company_id = companyId;
        }
        if (date) {
            context.default_date = date;
            context.default_week_start = weekStart(date);
            context.default_focus_date = date;
        }
        openEmployeeOrderWizard(actionService, context);
    });
    td.appendChild(link);
    tr.appendChild(td);
    return tr;
}

function insertAfter(node, row) {
    if (!node || !row) {
        return row;
    }
    node.after(row);
    return row;
}

function removeInjectedRows(scope) {
    scope.querySelectorAll("tr." + ROW_CLASS).forEach((row) => row.remove());
    scope.querySelectorAll(".lf_client_order_footer").forEach((el) => el.remove());
}

function signatureOf(list) {
    const parts = [];
    const walk = (groups, level) => {
        for (const group of groups || []) {
            parts.push(level, groupFieldName(group), groupRawValue(group), isFolded(group) ? 1 : 0);
            if (!isFolded(group)) {
                const nested = nestedGroups(group);
                if (nested.length) {
                    walk(nested, level + 1);
                } else {
                    parts.push("rec", group.list?.records?.length || group.records?.length || 0);
                }
            }
        }
    };
    walk(list?.groups || [], 0);
    return parts.join("|");
}

function injectNuevoPedidoRows(renderer) {
    const root = resolveRoot(renderer);
    const scope = resolveScope(root);
    const actionService = renderer.env?.services?.action;
    if (!root || !scope || !actionService) {
        return;
    }
    for (const el of scope.querySelectorAll("button.o_list_group_add:not(.lf_nuevo_pedido):not(." + LINK_CLASS + ")")) {
        el.remove();
    }
    for (const el of scope.querySelectorAll(".o_list_group_input")) {
        const wrap = el.closest(".input-group");
        (wrap || el).remove();
    }

    const list = renderer.props?.list;
    const companies = list?.groups || [];
    const signature = signatureOf(list);
    if (scope.dataset.lfNuevoPedidoSig === signature && scope.querySelector("tr." + ROW_CLASS + ", ." + LINK_CLASS)) {
        return;
    }

    removeInjectedRows(scope);

    const table = scope.querySelector("table.o_list_table, .o_list_table") || root;
    const tbody = table.querySelector("tbody") || table;
    const rows = [...tbody.querySelectorAll(":scope > tr.o_group_header, :scope > tr.o_data_row")];
    let idx = 0;

    const consumeHeader = () => {
        while (idx < rows.length && !rows[idx].classList.contains("o_group_header")) {
            idx += 1;
        }
        return idx < rows.length ? rows[idx++] : null;
    };
    const consumeDataRows = () => {
        let last = null;
        while (idx < rows.length && rows[idx].classList.contains("o_data_row")) {
            last = rows[idx];
            idx += 1;
        }
        return last;
    };

    let lastInserted = null;

    if (companies.length) {
        for (const company of companies) {
            const companyHeader = consumeHeader();
            const companyId = groupCompanyId(company);
            if (isFolded(company)) {
                lastInserted = companyHeader || lastInserted;
                continue;
            }
            const days = nestedGroups(company);
            if (days.length) {
                for (const day of days) {
                    const dayHeader = consumeHeader();
                    if (isFolded(day)) {
                        lastInserted = dayHeader || lastInserted;
                        continue;
                    }
                    const lastData = consumeDataRows();
                    const anchor = lastData || dayHeader || lastInserted;
                    lastInserted = insertAfter(
                        anchor,
                        makeLinkRow(scope, actionService, {
                            scopeName: "day",
                            companyId,
                            date: groupDateValue(day),
                        }),
                    ) || lastInserted;
                }
                const companyAnchor = lastInserted || companyHeader;
                lastInserted = insertAfter(
                    companyAnchor,
                    makeLinkRow(scope, actionService, { scopeName: "company", companyId }),
                ) || lastInserted;
            } else {
                const lastData = consumeDataRows();
                lastInserted = insertAfter(
                    lastData || companyHeader || lastInserted,
                    makeLinkRow(scope, actionService, { scopeName: "company", companyId }),
                ) || lastInserted;
            }
        }
    } else {
        // Ungrouped list: a single end-of-list link after the last data row.
        const allData = [...tbody.querySelectorAll(":scope > tr.o_data_row")];
        lastInserted = allData[allData.length - 1] || null;
    }

    const listEnd = makeLinkRow(scope, actionService, { scopeName: "list", isListEnd: true });
    if (lastInserted) {
        lastInserted.after(listEnd);
    } else if (tbody) {
        tbody.appendChild(listEnd);
    }
    scope.dataset.lfNuevoPedidoSig = signature;
}

function injectFromRenderer(renderer) {
    if (!isLfReservationList(renderer)) {
        return;
    }
    injectNuevoPedidoRows(renderer);
}

function watchListViews(actionService) {
    const tryInject = () => {
        document
            .querySelectorAll(".o_list_view.lf-reservations, .o_lf_reservation_list_view")
            .forEach((view) => {
                const rendererLike = { props: {}, env: { services: { action: actionService } }, el: view, tableRef: { el: view } };
                // Fallback when OWL hooks missed a re-render: only restore the
                // end-of-list link if every injected row was wiped.
                if (!view.querySelector("." + LINK_CLASS + ", tr." + ROW_CLASS)) {
                    const tbody = view.querySelector("tbody");
                    if (tbody) {
                        tbody.appendChild(makeLinkRow(view, actionService, { scopeName: "list", isListEnd: true }));
                    }
                }
            });
    };
    const start = () => {
        tryInject();
        const obs = new MutationObserver(() => tryInject());
        obs.observe(document.body, { childList: true, subtree: true });
    };
    if (document.body) {
        start();
    } else {
        document.addEventListener("DOMContentLoaded", start);
    }
}

// Hooks are registered on every list (OWL requires a stable hook sequence).
// The native group-create UI is disabled only on the Pedidos / reservation list.
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => injectFromRenderer(this));
        onPatched(() => injectFromRenderer(this));
    },
    get canCreateGroup() {
        if (isLfReservationList(this)) {
            return false;
        }
        return super.canCreateGroup;
    },
});

patch(WebClient.prototype, {
    setup() {
        super.setup(...arguments);
        watchListViews(this.env.services.action);
    },
});

export class LfReservationListController extends ListController {
    static template = "kai_viandas.LfReservationListView";

    async createRecord() {
        return openEmployeeOrderWizard(this.env.services.action || this.actionService);
    }

    onClickAddClientOrder(ev) {
        ev?.preventDefault?.();
        ev?.stopPropagation?.();
        return openEmployeeOrderWizard(this.env.services.action || this.actionService);
    }
}

// Optional columns that already existed before 19.0.1.17.9. Older
// localStorage lists only named the visible ones among these; absence
// still means hidden. Newly optional columns were defaulted to
// optional="show" so they did not disappear for operators who had a
// saved column set. That default must run only once: computeOptionalActiveFields
// is called on every render, and "not in the saved list" is also how a
// later untick is stored. Re-applying the default made Empresa cliente
// (and the other new columns) impossible to hide.
const PREVIOUS_OPTIONAL_FIELDS = new Set([
    "current_dessert_description",
    "current_drink_description",
    "pending_description",
    "fulfillment_state",
    "fulfillment_production_ids",
    "week_label",
    "state",
    "after_reference_time",
    "after_preparation_cut",
]);
const OPTIONAL_FIELDS_MIGRATION_KEY_SUFFIX = ",migrated_11710";

export class LfReservationListRenderer extends ListRenderer {
    computeOptionalActiveFields() {
        const result = super.computeOptionalActiveFields();
        const migratedKey = `${this.keyOptionalFields}${OPTIONAL_FIELDS_MIGRATION_KEY_SUFFIX}`;
        if (browser.localStorage.getItem(migratedKey)) {
            return result;
        }
        const stored = browser.localStorage.getItem(this.keyOptionalFields);
        if (stored === null) {
            // Mark migrated so the first later untick is not treated as a
            // pre-1.17.9 saved list (absence would otherwise restore show).
            browser.localStorage.setItem(migratedKey, "1");
            return result;
        }
        const saved = stored.split(",");
        const newlyOptional = this.allColumns.filter(
            (col) => col.type === "field" && col.optional && !PREVIOUS_OPTIONAL_FIELDS.has(col.name)
        );
        const looksLikeLegacyList = newlyOptional.every((col) => !saved.includes(col.name));
        if (looksLikeLegacyList) {
            for (const col of newlyOptional) {
                result[col.name] = col.optional === "show";
            }
            browser.localStorage.setItem(
                this.keyOptionalFields,
                Object.keys(result)
                    .filter((name) => result[name])
                    .join(",")
            );
        }
        browser.localStorage.setItem(migratedKey, "1");
        return result;
    }
}

registry.category("views").add("lf_reservation_list", {
    ...listView,
    Controller: LfReservationListController,
    Renderer: LfReservationListRenderer,
});
