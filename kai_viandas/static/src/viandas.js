// La página privada no carga los servicios de tienda ni consulta datos comerciales.
(() => {
    "use strict";
    const form = document.querySelector("#lf-week-form");
    if (form && document.querySelector("[data-save-state]")) {
        const days = [...form.querySelectorAll(".day")];
        const saveState = document.querySelector("[data-save-state]");
        let lastChanged = "";
        let pointerDay;
        let pointerAt = 0;
        let openedByUser;

        function selectedValue(day, prefix) {
            return day.querySelector(`input[type=radio][name="${prefix}${day.dataset.menu}"]:checked`)?.value || "";
        }

        function optionName(day, prefix, value) {
            if (!value) return "";
            const radio = day.querySelector(`input[type=radio][name="${prefix}${day.dataset.menu}"][value="${value}"]`);
            return radio?.closest("label")?.querySelector("strong")?.textContent.trim() || "";
        }

        function syncSides(day) {
            const hasPlate = !!selectedValue(day, "menu_");
            for (const group of day.querySelectorAll(".side-group")) {
                group.classList.toggle("sides-disabled", !hasPlate);
                for (const radio of group.querySelectorAll("input[type=radio]")) {
                    radio.disabled = !hasPlate;
                    if (!hasPlate && radio.value === "") radio.checked = true;
                }
            }
        }

        function reflectChoices() {
            let changed = 0;
            for (const day of days) {
                syncSides(day);
                const plate = selectedValue(day, "menu_");
                const dessert = selectedValue(day, "dessert_");
                const drink = selectedValue(day, "drink_");
                const draft = day.querySelector(".draft-choice");
                const dirty = plate !== (day.dataset.selected || "")
                    || dessert !== (day.dataset.selectedDessert || "")
                    || drink !== (day.dataset.selectedDrink || "")
                    || day.dataset.review === "1";
                const currentIntent = day.querySelector('input[type="hidden"][name="withdraw_' + day.dataset.menu + '"]');
                const annulling = dirty && currentIntent && plate === (currentIntent.value || "")
                    && dessert === (day.querySelector('input[type="hidden"][name="withdraw_dessert_' + day.dataset.menu + '"]')?.value || "")
                    && drink === (day.querySelector('input[type="hidden"][name="withdraw_drink_' + day.dataset.menu + '"]')?.value || "");
                draft.hidden = !dirty;
                const parts = [];
                if (plate) {
                    parts.push(optionName(day, "menu_", plate));
                    const dessertName = optionName(day, "dessert_", dessert);
                    const drinkName = optionName(day, "drink_", drink);
                    if (dessertName) parts.push(dessertName);
                    if (drinkName) parts.push(drinkName);
                }
                const name = parts.join(" · ") || "No reservar este día";
                draft.textContent = annulling ? `Sin guardar: anular el cambio pedido. Sigue ${currentIntent.dataset.currentDescription}.`
                    : dirty ? `Sin guardar: ${name}` : "";
                changed += Number(dirty);
            }
            saveState.textContent = changed ? `${changed} ${changed === 1 ? "día sin guardar" : "días sin guardar"}`
                : days.some(day => day.dataset.selected) ? "Sin cambios nuevos." : "Elegí los días que quieras reservar.";
        }

        function restoreServerChoices() {
            // Los ids y la selección del servidor son estables. Nunca se interpreta
            // como una elección nueva el estado de controles restaurado por índice.
            for (const day of days) {
                for (const radio of day.querySelectorAll("input[type=radio]")) {
                    const name = radio.name || "";
                    let expected = day.dataset.initialChoice;
                    if (name.startsWith("dessert_")) expected = day.dataset.initialDessert;
                    else if (name.startsWith("drink_")) expected = day.dataset.initialDrink;
                    radio.checked = radio.value === (expected || "");
                }
                syncSides(day);
            }
            reflectChoices();
        }
        restoreServerChoices();
        window.addEventListener("pageshow", (event) => {
            restoreServerChoices();
            const navigation = performance.getEntriesByType("navigation")[0];
            if (event.persisted || navigation?.type === "back_forward") {
                // Atrás debe consultar la reserva vigente, aunque la página anterior
                // conserve un formulario de antes del POST → GET.
                document.querySelector('button[form="lf-week-form"]').disabled = true;
                location.reload();
            }
        });

        for (const day of days) {
            const summary = day.querySelector("summary");
            summary.addEventListener("click", () => { openedByUser = day; });
            day.addEventListener("toggle", () => {
                if (day.open && openedByUser === day) {
                    openedByUser = null;
                    for (const other of days) {
                        if (other !== day) other.open = false;
                    }
                    day.scrollIntoView({ block: "start" });
                }
            });
            day.addEventListener("pointerdown", (event) => {
                pointerDay = event.target.closest('.option-card') ? day : null;
                pointerAt = performance.now();
            });
            day.addEventListener("change", (event) => {
                if (!event.target.matches("input[type=radio]")) return;
                day.dataset.review = "0";
                const error = day.querySelector('.choice-unavailable-error');
                if (error) error.hidden = event.target.dataset.unavailable !== "1";
                lastChanged = day.dataset.menu;
                reflectChoices();
                const name = event.target.name || "";
                const pickedPlate = name.startsWith("menu_");
                const hasSides = !!day.querySelector(".side-group") && !!selectedValue(day, "menu_");
                // Un toque termina la elección del día, salvo cuando todavía hay
                // postre o bebida para elegir después del plato.
                if (pointerDay === day && performance.now() - pointerAt < 1000 && !(pickedPlate && hasSides)) {
                    day.open = false;
                    summary.focus({ preventScroll: true });
                    // El plegado cambia el alto y puede dejar el borrador arriba
                    // del área desplazable. Alinear lo mínimo, sin animación ni
                    // modificar la navegación con las flechas del teclado.
                    const viewport = day.closest('.week-scroll').getBoundingClientRect();
                    const heading = summary.getBoundingClientRect();
                    if (heading.top < viewport.top + 8 || heading.bottom > viewport.bottom - 8) {
                        summary.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' });
                    }
                }
                pointerDay = null;
            });
        }
        form.addEventListener("submit", (event) => {
            const invalidDay = days.find(day => day.querySelector('input:checked[data-unavailable="1"]'));
            if (invalidDay) {
                event.preventDefault();
                for (const day of days) day.open = day === invalidDay;
                invalidDay.querySelector('.choice-unavailable-error').hidden = false;
                const notice = invalidDay.querySelector('.choice-unavailable-error');
                notice.setAttribute('tabindex', '-1');
                notice.focus({preventScroll: true});
                invalidDay.scrollIntoView({block: "start"});
                return;
            }
            form.elements.open_days.value = lastChanged || days.filter(day => day.open).map(day => day.dataset.menu).join(",");
        });
        if (location.hash === "#resultado") {
            document.getElementById("resultado")?.scrollIntoView({ block: "start" });
            history.replaceState(null, "", location.pathname + location.search);
        }
    }

    for (const toggle of document.querySelectorAll("[data-password-toggle]")) {
        toggle.addEventListener("click", () => {
            const input = document.getElementById(toggle.getAttribute("aria-controls"));
            const show = input.type === "password";
            input.type = show ? "text" : "password";
            toggle.textContent = show ? "Ocultar" : "Mostrar";
            toggle.setAttribute("aria-pressed", String(show));
        });
    }
    for (const input of document.querySelectorAll("input[required]")) {
        const validate = () => input.setCustomValidity(input.value.trim() ? "" : "Completá este campo para continuar.");
        input.addEventListener("input", validate);
        input.addEventListener("invalid", validate);
    }
    for (const correction of document.querySelectorAll(".lf-correction-form")) {
        const input = correction.elements.message;
        const error = correction.querySelector(".correction-error");
        correction.noValidate = true;
        correction.addEventListener("submit", (event) => {
            if (!input.value.trim() || input.value.length > 4000) {
                event.preventDefault();
                error.hidden = false;
                input.setAttribute("aria-invalid", "true");
                input.focus();
            }
        });
        input.addEventListener("input", () => {
            error.hidden = true;
            input.removeAttribute("aria-invalid");
        });
    }

    const leaveDialog = document.querySelector('#lf-leave-dialog');
    if (leaveDialog) {
        let destination;
        let previousFocus;
        let messageSelection;
        let leaving = false;
        const draftDays = () => [...document.querySelectorAll('.draft-choice:not([hidden])')].length;
        const unsentMessage = () => !!document.querySelector('.lf-correction-form textarea')?.value.trim();
        const localEdits = () => unsentMessage() || [...document.querySelectorAll('.day')].some(day => {
            const value = (prefix, initial) => {
                const selected = day.querySelector(`input[type=radio][name="${prefix}${day.dataset.menu}"]:checked`);
                return selected && (selected.value || "") !== (initial || "");
            };
            return value("menu_", day.dataset.initialChoice)
                || value("dessert_", day.dataset.initialDessert)
                || value("drink_", day.dataset.initialDrink);
        });
        document.addEventListener('click', event => {
            const link = event.target.closest('a[href]');
            if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
                    || link.target === '_blank' || link.hasAttribute('download')) return;
            const url = new URL(link.href, location.href);
            if (url.origin !== location.origin || !['http:', 'https:'].includes(url.protocol)
                    || (url.hash && url.pathname === location.pathname && url.search === location.search)) return;
            const count = draftDays();
            if (!count && !unsentMessage()) return;
            event.preventDefault();
            destination = url.href;
            previousFocus = link;
            const input = count ? null : document.querySelector('.lf-correction-form textarea');
            messageSelection = input ? {
                input, start: input.selectionStart, end: input.selectionEnd,
                direction: input.selectionDirection,
            } : null;
            leaveDialog.querySelector('h2').textContent = count
                ? `Tenés ${count} ${count === 1 ? 'día sin guardar' : 'días sin guardar'}`
                : 'Tenés una consulta sin enviar';
            leaveDialog.querySelector('p').textContent = count
                ? 'Vas a salir sin enviar estas elecciones. Los cambios hechos en esta pantalla se perderán.'
                : 'Si salís ahora, el texto de esta consulta no se envía ni se conserva.';
            leaveDialog.querySelector('[data-keep-choosing]').textContent = count ? 'Seguir eligiendo' : 'Seguir escribiendo';
            leaveDialog.showModal();
            leaveDialog.querySelector('[data-keep-choosing]').focus();
        });
        leaveDialog.querySelector('[data-keep-choosing]').addEventListener('click', () => {
            if (messageSelection) previousFocus = messageSelection.input;
            leaveDialog.close();
            if (messageSelection) {
                // Dentro del gesto del usuario: permite recuperar el teclado móvil.
                // El evento close conserva este destino y no vuelve al enlace.
                const { input, start, end, direction } = messageSelection;
                input.focus({preventScroll: true});
                input.setSelectionRange(start, end, direction);
                input.scrollIntoView({block: 'center', inline: 'nearest'});
            }
        });
        leaveDialog.addEventListener('close', () => previousFocus?.focus({preventScroll: true}));
        leaveDialog.querySelector('[data-leave-unsaved]').addEventListener('click', () => {
            leaving = true;
            leaveDialog.close();
            location.assign(destination);
        });
        document.addEventListener('submit', event => {
            if (event.target.matches('#lf-week-form, .lf-correction-form') && !event.defaultPrevented) leaving = true;
        });
        window.addEventListener('pageshow', () => { leaving = false; });
        window.addEventListener('beforeunload', event => {
            // Complemento nativo, no garantía en todos los teléfonos. Los borradores
            // de conflicto ya conservados no necesitan bloquear esta recarga.
            if (!leaving && localEdits()) {
                event.preventDefault();
                event.returnValue = '';
            }
        });
    }
})();
