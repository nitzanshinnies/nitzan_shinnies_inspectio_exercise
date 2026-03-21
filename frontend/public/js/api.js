/**
 * HTTP client for the public REST API (same-origin when served behind nginx).
 *
 * @typedef {{ body: string, to?: string }} MessageCreateBody
 * @typedef {{ accepted: number, messageIds: string[] }} RepeatResponse
 * @typedef {{ items: object[] }} OutcomesEnvelope
 * @typedef {{ messageId: string, status: string }} PostMessageResponse
 */

import { DEFAULT_OUTCOME_LIMIT, OUTCOME_LIMIT_MAX, OUTCOME_LIMIT_MIN } from "./constants.js";

/** @returns {string} */
function baseUrl() {
    const fromMeta = document.querySelector('meta[name="inspectio-api-base"]');
    if (fromMeta instanceof HTMLMetaElement && fromMeta.content.trim() !== "") {
        return fromMeta.content.replace(/\/$/, "");
    }
    return "";
}

/**
 * @param {Response} response
 * @returns {Promise<never>}
 */
async function throwForStatus(response) {
    const text = await response.text();
    let detail = text;
    try {
        const parsed = JSON.parse(text);
        if (parsed && typeof parsed === "object" && "detail" in parsed) {
            detail = String(/** @type {{ detail: unknown }} */ (parsed).detail);
        }
    } catch {
        // keep raw text
    }
    const err = new Error(detail || `HTTP ${response.status}`);
    err.name = "ApiError";
    throw err;
}

/**
 * @param {string} path
 * @param {Record<string, string>} [query]
 * @returns {string}
 */
function withQuery(path, query) {
    if (!query || Object.keys(query).length === 0) {
        return path;
    }
    const params = new URLSearchParams(query);
    return `${path}?${params.toString()}`;
}

/**
 * @param {MessageCreateBody} body
 * @returns {Record<string, string>}
 */
function messageJson(body) {
    const payload = { body: body.body };
    if (body.to !== undefined && body.to.trim() !== "") {
        payload.to = body.to.trim();
    }
    return payload;
}

/**
 * @param {MessageCreateBody} body
 * @returns {Promise<PostMessageResponse>}
 */
export async function postMessage(body) {
    const response = await fetch(`${baseUrl()}/messages`, {
        body: JSON.stringify(messageJson(body)),
        headers: { "Content-Type": "application/json" },
        method: "POST",
    });
    if (!response.ok) {
        await throwForStatus(response);
    }
    return /** @type {Promise<PostMessageResponse>} */ (response.json());
}

/**
 * @param {number} count
 * @param {MessageCreateBody} body
 * @returns {Promise<RepeatResponse>}
 */
export async function postMessagesRepeat(count, body) {
    const path = withQuery("/messages/repeat", { count: String(count) });
    const response = await fetch(`${baseUrl()}${path}`, {
        body: JSON.stringify(messageJson(body)),
        headers: { "Content-Type": "application/json" },
        method: "POST",
    });
    if (!response.ok) {
        await throwForStatus(response);
    }
    return /** @type {Promise<RepeatResponse>} */ (response.json());
}

/**
 * @param {number} [limit]
 * @returns {Promise<OutcomesEnvelope>}
 */
export async function getFailedOutcomes(limit = DEFAULT_OUTCOME_LIMIT) {
    const lim = Math.min(Math.max(limit, OUTCOME_LIMIT_MIN), OUTCOME_LIMIT_MAX);
    const path = withQuery("/messages/failed", { limit: String(lim) });
    const response = await fetch(`${baseUrl()}${path}`, { method: "GET" });
    if (!response.ok) {
        await throwForStatus(response);
    }
    return /** @type {Promise<OutcomesEnvelope>} */ (response.json());
}

/**
 * @returns {Promise<Record<string, unknown>>}
 */
export async function getHealthz() {
    const response = await fetch(`${baseUrl()}/healthz`, { method: "GET" });
    if (!response.ok) {
        await throwForStatus(response);
    }
    return /** @type {Promise<Record<string, unknown>>} */ (response.json());
}

/**
 * @param {number} [limit]
 * @returns {Promise<OutcomesEnvelope>}
 */
export async function getSuccessOutcomes(limit = DEFAULT_OUTCOME_LIMIT) {
    const lim = Math.min(Math.max(limit, OUTCOME_LIMIT_MIN), OUTCOME_LIMIT_MAX);
    const path = withQuery("/messages/success", { limit: String(lim) });
    const response = await fetch(`${baseUrl()}${path}`, { method: "GET" });
    if (!response.ok) {
        await throwForStatus(response);
    }
    return /** @type {Promise<OutcomesEnvelope>} */ (response.json());
}
