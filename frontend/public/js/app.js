import {
    getFailedOutcomes,
    getHealthz,
    getSuccessOutcomes,
    postMessage,
    postMessagesRepeat,
} from "./api.js";
import { DEFAULT_OUTCOME_LIMIT, OUTCOME_LIMIT_MAX, OUTCOME_LIMIT_MIN } from "./constants.js";

/** @param {HTMLElement} el */
function clearChildren(el) {
    while (el.firstChild) {
        el.removeChild(el.firstChild);
    }
}

/**
 * @param {string} text
 * @param {"info"|"error"} kind
 */
function setBanner(text, kind) {
    const banner = document.getElementById("banner");
    if (!(banner instanceof HTMLElement)) {
        return;
    }
    banner.textContent = text;
    banner.dataset.kind = kind;
    banner.hidden = text === "";
}

/**
 * @param {unknown} err
 * @returns {string}
 */
function formatError(err) {
    if (err instanceof Error) {
        return err.message;
    }
    return String(err);
}

/**
 * @param {object[]} rows
 * @returns {HTMLTableElement}
 */
function buildOutcomesTable(rows) {
    const table = document.createElement("table");
    table.className = "outcomes-table";
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    const columns =
        rows.length === 0
            ? []
            : Object.keys(rows[0]).sort((a, b) => a.localeCompare(b));
    for (const col of columns) {
        const th = document.createElement("th");
        th.textContent = col;
        headerRow.appendChild(th);
    }
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const row of rows) {
        const tr = document.createElement("tr");
        for (const col of columns) {
            const td = document.createElement("td");
            const value = /** @type {Record<string, unknown>} */ (row)[col];
            td.textContent =
                value === null || value === undefined ? "" : JSON.stringify(value);
            tr.appendChild(td);
        }
        tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    return table;
}

/** @param {string} id @returns {HTMLInputElement | null} */
function inputById(id) {
    const el = document.getElementById(id);
    return el instanceof HTMLInputElement ? el : null;
}

/** @param {string} id @returns {HTMLTextAreaElement | null} */
function textareaById(id) {
    const el = document.getElementById(id);
    return el instanceof HTMLTextAreaElement ? el : null;
}

/** @param {string} id @returns {HTMLButtonElement | null} */
function buttonById(id) {
    const el = document.getElementById(id);
    return el instanceof HTMLButtonElement ? el : null;
}

/** @param {string} id @returns {HTMLElement | null} */
function regionById(id) {
    const el = document.getElementById(id);
    return el instanceof HTMLElement ? el : null;
}

function readMessageCreate() {
    const bodyEl = textareaById("message-body");
    const toEl = inputById("message-to");
    if (!bodyEl) {
        throw new Error("message body field missing");
    }
    const body = bodyEl.value.trim();
    const toRaw = toEl?.value.trim() ?? "";
    return toRaw === "" ? { body } : { body, to: toRaw };
}

async function onSubmitMessage(ev) {
    ev.preventDefault();
    setBanner("", "info");
    const out = regionById("send-result");
    if (out) {
        clearChildren(out);
    }
    try {
        const payload = readMessageCreate();
        const data = await postMessage(payload);
        if (out) {
            const pre = document.createElement("pre");
            pre.textContent = JSON.stringify(data, null, 2);
            out.appendChild(pre);
        }
        setBanner("Message accepted.", "info");
    } catch (err) {
        setBanner(formatError(err), "error");
    }
}

async function onSubmitRepeat(ev) {
    ev.preventDefault();
    setBanner("", "info");
    const out = regionById("repeat-result");
    if (out) {
        clearChildren(out);
    }
    const countEl = inputById("repeat-count");
    const count = countEl ? Number.parseInt(countEl.value, 10) : NaN;
    if (!Number.isFinite(count) || count < 1) {
        setBanner("Count must be a positive integer.", "error");
        return;
    }
    try {
        const payload = readMessageCreate();
        const data = await postMessagesRepeat(count, payload);
        if (out) {
            const pre = document.createElement("pre");
            const summary = {
                accepted: data.accepted,
                messageIds: data.messageIds,
                messageIdsPreview: data.messageIds.slice(0, 20),
                messageIdsTruncated: data.messageIds.length > 20,
            };
            pre.textContent = JSON.stringify(summary, null, 2);
            out.appendChild(pre);
        }
        setBanner(`Created ${data.accepted} messages.`, "info");
    } catch (err) {
        setBanner(formatError(err), "error");
    }
}

async function refreshOutcomes(kind) {
    setBanner("", "info");
    const limitEl = inputById("outcomes-limit");
    const raw = limitEl?.value ?? String(DEFAULT_OUTCOME_LIMIT);
    const limit = Number.parseInt(raw, 10);
    const lim = Number.isFinite(limit) ? limit : DEFAULT_OUTCOME_LIMIT;
    const mountId = kind === "success" ? "success-outcomes" : "failed-outcomes";
    const mount = regionById(mountId);
    if (!mount) {
        return;
    }
    clearChildren(mount);
    try {
        const data =
            kind === "success"
                ? await getSuccessOutcomes(lim)
                : await getFailedOutcomes(lim);
        const table = buildOutcomesTable(data.items ?? []);
        mount.appendChild(table);
        setBanner(`Loaded ${(data.items ?? []).length} ${kind} row(s).`, "info");
    } catch (err) {
        setBanner(formatError(err), "error");
    }
}

async function onHealthCheck() {
    setBanner("", "info");
    const out = regionById("health-result");
    if (out) {
        clearChildren(out);
    }
    try {
        const data = await getHealthz();
        if (out) {
            const pre = document.createElement("pre");
            pre.textContent = JSON.stringify(data, null, 2);
            out.appendChild(pre);
        }
        setBanner("Health check OK.", "info");
    } catch (err) {
        setBanner(formatError(err), "error");
    }
}

function wire() {
    const sendForm = document.getElementById("form-send");
    if (sendForm instanceof HTMLFormElement) {
        sendForm.addEventListener("submit", onSubmitMessage);
    }
    const repeatForm = document.getElementById("form-repeat");
    if (repeatForm instanceof HTMLFormElement) {
        repeatForm.addEventListener("submit", onSubmitRepeat);
    }
    const btnSuccess = buttonById("btn-success-refresh");
    btnSuccess?.addEventListener("click", () => {
        void refreshOutcomes("success");
    });
    const btnFailed = buttonById("btn-failed-refresh");
    btnFailed?.addEventListener("click", () => {
        void refreshOutcomes("failed");
    });
    const btnHealth = buttonById("btn-health");
    btnHealth?.addEventListener("click", () => {
        void onHealthCheck();
    });

    const limitEl = inputById("outcomes-limit");
    if (limitEl) {
        limitEl.min = String(OUTCOME_LIMIT_MIN);
        limitEl.max = String(OUTCOME_LIMIT_MAX);
        limitEl.value = String(DEFAULT_OUTCOME_LIMIT);
    }
}

document.addEventListener("DOMContentLoaded", wire);
